"""Selecciona validaciones por dependencias, conservando una salida completa ante dudas."""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict, deque
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


LAYERS = ("bootstrap", "foundation", "data", "compute")
VERSION_FILES = {
    ".node-version", ".python-version", ".terraform-version", "toolchain.versions.json",
    "requirements.lock", "build-requirements.lock", "pyproject.toml", "package.json",
    "package-lock.json", "npm-shrinkwrap.json", "scripts/audit_versions.py",
    "scripts/Check-Versions.ps1", "scripts/install_trivy.py",
}
CONTROL_FILES = {
    "scripts/Test.ps1", "scripts/Common.ps1", "scripts/test_impact.py",
    "scripts/check_repository.py",
}
PACKAGE_FILES = {
    "requirements.lock", "build-requirements.lock", "pyproject.toml",
    "scripts/package.py", "scripts/Package.ps1",
}
EVALUATION_FILES = {
    "src/ecommerce_agent/adapters.py", "src/ecommerce_agent/application.py",
    "src/ecommerce_agent/domain.py", "src/ecommerce_agent/conversation_memory.py",
    "scripts/evaluate_agent.py", "scripts/evaluate_agent_managed.py",
    "scripts/fixtures/agent-evaluation-cases.json", "scripts/Evaluate-Agent.ps1",
}
# Los contratos HTTP no aparecen como imports entre Python y el navegador.
CROSS_CONTRACTS = {
    "src/ecommerce_agent/domain.py": ("profiles", "review", "evidence", "conversation", "pending", "order-sync"),
    "src/ecommerce_agent/application.py": ("profiles", "review", "evidence", "conversation", "pending", "order-sync"),
    "src/ecommerce_agent/ports.py": ("profiles", "review", "evidence", "conversation", "pending", "order-sync"),
    "src/ecommerce_agent/handler.py": ("auth", "profiles", "review", "evidence", "conversation", "pending", "order-sync"),
    "src/ecommerce_agent/identity.py": ("auth", "profiles", "review"),
    "src/ecommerce_agent/gateway.py": ("evidence", "conversation", "review"),
    "src/ecommerce_agent/gateway_handler.py": ("evidence", "conversation", "review"),
    "src/ecommerce_agent/adapters.py": ("profiles", "review", "evidence", "conversation"),
    "src/ecommerce_agent/conversation_memory.py": ("conversation",),
    "src/ecommerce_agent/content_guard.py": ("evidence", "conversation"),
    "src/ecommerce_agent/knowledge.py": ("evidence", "conversation"),
}
# Estos adaptadores tienen nombres o cargas dinámicas que no expresa un import.
EXTRA_DEPENDENCIES = {
    "scripts/evaluate_agent.py": ("scripts/fixtures/agent-evaluation-cases.json",),
    "scripts/Sync-Knowledge.ps1": ("scripts/sync_knowledge.py",),
    "scripts/Seed-Demo.ps1": ("scripts/seed_demo.py",),
    "scripts/Evaluate-Agent.ps1": ("scripts/evaluate_agent.py", "scripts/evaluate_agent_managed.py"),
    "docs/politicas-posventa-demo.md": (),
}
DOCUMENT_SUFFIXES = {
    ".md", ".txt", ".rst", ".adoc", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".webp", ".ico", ".pdf", ".pptx", ".potx", ".docx", ".drawio", ".mp4", ".woff", ".woff2",
}


def normalize(path: str) -> str:
    """Rechaza rutas ajenas al repositorio y normaliza separadores de Windows."""
    value = path.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    parsed = PurePosixPath(value)
    if not value or parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"Ruta de cambio fuera del repositorio: {path!r}")
    return str(parsed)


def _files(root: Path, folder: str, pattern: str) -> set[str]:
    return {p.relative_to(root).as_posix() for p in (root / folder).rglob(pattern)
            if p.is_file() and not any(part.startswith(".") or part == "__pycache__"
                                       for part in p.relative_to(root / folder).parts)}


def _module_names(path: str) -> set[str]:
    parts = PurePosixPath(path).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = {".".join(parts)} if parts else set()
    if parts and parts[0] in {"src", "scripts", "tests"}:
        names.add(".".join(parts[1:]))
    return names - {""}


def _canonical_module(path: str) -> str:
    """Conserva el paquete real y elimina únicamente la raíz de instalación src."""
    parts = PurePosixPath(path).with_suffix("").parts
    if parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _path_fragments(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _path_fragments(node.left), _path_fragments(node.right)
        if right is not None:
            return f"{left}/{right}" if left is not None else right
    return None


def _local_reference(owner: str, value: str, known: set[str]) -> set[str]:
    """Resuelve literales de rutas sin ejecutar el código que se está validando."""
    if not value or "\n" in value or "\x00" in value or len(value) > 300:
        return set()
    value = value.replace("\\", "/")
    candidates = [value, str(PurePosixPath(owner).parent / value)]
    matches = set()
    for candidate in candidates:
        parts = []
        for part in PurePosixPath(candidate).parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        resolved = "/".join(parts)
        if resolved in known:
            matches.add(resolved)
    return matches


def _dependency_graph(root: Path, changed: set[str]) -> tuple[dict[str, set[str]], list[str]]:
    python = set().union(*(_files(root, folder, "*.py") for folder in ("src", "scripts", "tests")))
    javascript = _files(root, "web", "*.js") | _files(root, "tests", "*.mjs")
    existing = python | javascript
    known = existing | changed | _files(root, "web", "*.html") | _files(root, "scripts/fixtures", "*")
    # Las rutas borradas también deben poder ser el destino de un import vigente.
    modules = {}
    for path in sorted(python | {p for p in changed if p.endswith(".py")}):
        for module in _module_names(path):
            modules[module] = path
    dependencies = defaultdict(set)
    errors = []
    for path in sorted(existing):
        try:
            source = (root / path).read_text(encoding="utf-8-sig")
            if path.endswith(".py"):
                tree = ast.parse(source, filename=path)
                current = _canonical_module(path)
                package = current if path.endswith("/__init__.py") else current.rpartition(".")[0]
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        base = node.module or ""
                        if node.level:
                            pieces = package.split(".") if package else []
                            base = ".".join(pieces[:len(pieces) - node.level + 1] + ([base] if base else []))
                        names = [base] + [f"{base}.{alias.name}".strip(".") for alias in node.names]
                    elif isinstance(node, ast.Call):
                        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                        if name in {"import_module", "__import__"} and node.args:
                            module = _path_fragments(node.args[0])
                            if module:
                                names = [module]
                    for name in names:
                        pieces = name.split(".")
                        for length in range(1, len(pieces) + 1):
                            module = ".".join(pieces[:length])
                            if module in modules and modules[module] != path:
                                dependencies[path].add(modules[module])
                    # Las rutas de fixtures escritas como datos de una prueba no son lecturas.
                    values = []
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                        values.append(_path_fragments(node))
                    elif isinstance(node, ast.Call):
                        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                        if name in {"Path", "open", "spec_from_file_location", "read_text", "read_bytes", "load_cases"}:
                            values.extend(_path_fragments(arg) for arg in node.args)
                    for value in values:
                        if value is not None:
                            dependencies[path].update(_local_reference(path, value, known) - {path})
            else:
                # Incluye imports dinámicos, new URL y readFileSync de las suites VM.
                for match in re.finditer(r"['\"]([^'\"\r\n]+)['\"]", source):
                    dependencies[path].update(_local_reference(path, match.group(1), known) - {path})
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"No se pudieron analizar las dependencias de {path}: {type(error).__name__}.")
    for owner, required in EXTRA_DEPENDENCIES.items():
        if (root / owner).is_file():
            dependencies[owner].update(path for path in required if path in known)
    # La política cargada en Knowledge Bases forma parte del contrato de evaluación.
    if "docs/politicas-posventa-demo.md" in changed:
        dependencies["scripts/evaluate_agent.py"].add("docs/politicas-posventa-demo.md")
        dependencies["tests/test_knowledge_sync.py"].add("docs/politicas-posventa-demo.md")
    return dict(dependencies), errors


def _affected(dependencies: dict[str, set[str]], changed: set[str]) -> set[str]:
    reverse = defaultdict(set)
    for owner, requirements in dependencies.items():
        for requirement in requirements:
            reverse[requirement].add(owner)
    affected, pending = set(changed), deque(changed)
    while pending:
        for owner in reverse[pending.popleft()]:
            if owner not in affected:
                affected.add(owner)
                pending.append(owner)
    return affected


def _is_version_file(path: str) -> bool:
    return (path in VERSION_FILES or path.startswith(".github/workflows/")
            or path.endswith(("/.terraform.lock.hcl", "/versions.tf")))


def _is_document(path: str) -> bool:
    return (PurePosixPath(path).suffix.lower() in DOCUMENT_SUFFIXES
            or path in {"AGENTS.md", ".gitignore", ".gitattributes", ".editorconfig", "LICENSE", "NOTICE"}
            or path.startswith(".github/ISSUE_TEMPLATE/"))


def build_plan(root: Path, changed_files: list[str], full: bool = False) -> dict:
    """Devuelve el contrato de selección consumido por el runner local y GitHub Actions."""
    root = root.resolve()
    changed = set(map(normalize, changed_files))
    all_python = _files(root, "tests", "test_*.py")
    all_frontend = _files(root, "tests", "web-*.test.mjs")
    all_checks = _files(root, "web", "*.js")
    dependencies, errors = _dependency_graph(root, changed)
    affected = _affected(dependencies, changed)
    reasons = ["Se solicitó ejecutar la validación completa."] if full else []
    for path in sorted(changed):
        if path in CONTROL_FILES or path.startswith(".github/workflows/") or _is_version_file(path):
            full = True
            reasons.append(f"{path}: cambia dependencias, versiones o el control de validación; se comprueba todo.")
    if errors:
        full = True
        reasons.extend(errors)
    python_tests = all_python & affected
    frontend_tests = all_frontend & affected
    javascript_checks = all_checks & affected
    layers = set()
    for path in sorted(changed):
        parts = PurePosixPath(path).parts
        if len(parts) >= 3 and parts[0] == "infra" and parts[1] in LAYERS:
            layer = parts[1]
            if path.endswith(".tftest.hcl"):
                layers.add(layer)
            else:
                layers.update(LAYERS[LAYERS.index(layer):])
            reasons.append(f"{path}: se validan las capas Terraform afectadas y sus consumidores.")
        elif path in CROSS_CONTRACTS:
            frontend_tests.update(f"tests/web-{name}.test.mjs" for name in CROSS_CONTRACTS[path]
                                  if f"tests/web-{name}.test.mjs" in all_frontend)
            reasons.append(f"{path}: se verifican consumidores Python y el contrato con el navegador.")
            if not (all_python & _affected(dependencies, {path})):
                full = True
                reasons.append(f"{path}: no hay cobertura Python demostrable del contrato; se comprueba todo.")
        elif path in affected and (path.endswith((".py", ".js", ".mjs"))):
            consumers = (all_python | all_frontend) & _affected(dependencies, {path})
            if not consumers and path not in CONTROL_FILES:
                full = True
                reasons.append(f"{path}: no hay cobertura de dependencias demostrable; se comprueba todo.")
            else:
                reasons.append(f"{path}: se seleccionan sus pruebas y consumidores transitivos.")
        elif path.startswith("web/") and path.endswith((".html", ".css")):
            reasons.append(f"{path}: se verifican los consumidores del recurso web y la estructura del repositorio.")
        elif path in EVALUATION_FILES or path in EXTRA_DEPENDENCIES or path == "docs/politicas-posventa-demo.md":
            reasons.append(f"{path}: se verifican los escenarios que consumen este recurso.")
        elif _is_document(path):
            reasons.append(f"{path}: documentación o recurso estático; basta el control del repositorio.")
        elif path not in CONTROL_FILES and not _is_version_file(path) and not path.startswith(".github/workflows/"):
            full = True
            reasons.append(f"{path}: impacto desconocido; se conserva la validación completa.")
    if not changed and not full:
        reasons.append("No hay archivos modificados; basta el control del repositorio.")
    if full:
        python_tests, frontend_tests, javascript_checks = all_python, all_frontend, all_checks
        layers = set(LAYERS)
    return {
        "schema_version": 1,
        "mode": "full" if full else "differential",
        "changed_files": sorted(changed),
        "reasons": list(dict.fromkeys(reasons)),
        "python_tests": sorted(python_tests),
        "frontend_tests": sorted(frontend_tests),
        "javascript_checks": sorted(javascript_checks),
        "terraform_layers": [layer for layer in LAYERS if layer in layers],
        "evaluations": full or bool(affected & EVALUATION_FILES),
        "package": bool(affected & PACKAGE_FILES) or any(path.startswith("src/") and path.endswith(".py") for path in changed),
        "versions": any(_is_version_file(path) for path in changed),
        "repository_check": True,
    }


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("No se pudo consultar el historial Git necesario para seleccionar pruebas.")
    return result.stdout


def _diff_paths(raw: bytes) -> list[str]:
    values = raw.decode("utf-8", errors="surrogateescape").split("\0")
    paths, index = [], 0
    while index < len(values) and values[index]:
        status = values[index]
        index += 1
        count = 2 if status.startswith(("R", "C")) else 1
        if index + count > len(values) or not all(values[index:index + count]):
            raise ValueError("La lista de cambios Git está incompleta.")
        paths.extend(values[index:index + count])
        index += count
    return paths


def git_changes(root: Path, base: str | None = None, head: str = "HEAD") -> tuple[list[str], str | None]:
    """Incluye ambos lados de renames y usa NUL para respetar espacios y Unicode."""
    try:
        if base is not None:
            if not base or set(base) == {"0"}:
                raise ValueError("La referencia base está vacía o corresponde a un primer push.")
            merge_base = _git(root, "merge-base", base, head).decode("ascii").strip()
            if not merge_base:
                raise ValueError("No hay un ancestro común disponible en el historial.")
            return sorted(set(_diff_paths(_git(root, "diff", "--name-status", "-z", "--find-renames", merge_base, head, "--")))), None
        paths = _diff_paths(_git(root, "diff", "--name-status", "-z", "--find-renames", "HEAD", "--"))
        paths.extend(path for path in _git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8", errors="surrogateescape").split("\0") if path)
        return sorted(set(paths)), None
    except (ValueError, OSError) as error:
        return [], f"Historial Git insuficiente: {error} Se ejecuta la validación completa."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Referencia base de la comparación con ancestro común")
    parser.add_argument("--head", default="HEAD", help="Referencia final; por defecto HEAD")
    parser.add_argument("--files", nargs="*", help="Rutas explícitas; omite el descubrimiento Git")
    parser.add_argument("--full", action="store_true", help="Ejecuta todas las suites")
    parser.add_argument("--output", type=Path, help="Archivo JSON de salida; si falta, usa stdout")
    args = parser.parse_args(argv)
    if args.files is not None and args.base is not None:
        parser.error("--files y --base no se pueden combinar")
    root = Path(__file__).resolve().parents[1]
    changed, fallback = (args.files, None) if args.files is not None else git_changes(root, args.base, args.head)
    try:
        plan = build_plan(root, changed, full=args.full or fallback is not None)
    except ValueError as error:
        parser.error(str(error))
    if fallback:
        plan["reasons"].insert(0, fallback)
        # Sin historia tampoco puede demostrarse que las dependencias y el paquete no cambiaron.
        plan["package"] = True
        plan["versions"] = True
    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
