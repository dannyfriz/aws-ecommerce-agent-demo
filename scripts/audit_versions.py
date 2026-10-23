"""Verifica versiones estables y pins reales contra fuentes primarias, sin instalar."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
STABLE = re.compile(r"^\d+\.\d+\.\d+(?:\.post\d+)?$")


def version_key(value):
    return tuple(map(int, re.findall(r"\d+", value)))


def fetch(url, as_json=True):
    headers = {"User-Agent": "aws-ecommerce-identity-lab-version-audit/0.1.0"}
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urlopen(Request(url, headers=headers), timeout=20) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("La fuente excedió el tamaño máximo")
    text = raw.decode("utf-8")
    return json.loads(text) if as_json else text


def latest(values):
    values = [v.removeprefix("v") for v in values if STABLE.fullmatch(v.removeprefix("v"))]
    if not values:
        raise ValueError("La fuente no publicó versiones estables reconocibles")
    return max(values, key=version_key)


def latest_compatible_dateutil(data, dependency):
    """Validar la restricción upstream antes de aceptar una versión compatible."""
    required = dependency["info"].get("requires_dist") or []
    if "python-dateutil<3.0.0,>=2.1" not in required:
        raise ValueError("Revisar excepción: botocore cambió su restricción dateutil")
    return latest(v for v, files in data["releases"].items()
                  if STABLE.fullmatch(v) and (2, 1) <= version_key(v) < (3, 0, 0)
                  and any(not f.get("yanked") for f in files))


def lambda_latest_ga(document):
    """Excluir explícitamente los runtimes que AWS identifica como preview."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", document))
    text = re.sub(r"\s+", " ", text)
    previews = set()
    for match in re.finditer(r"Python\s+(3\.\d+)\s+runtimes?\s+(?:are|is)\s+in\s+public\s+preview", text, re.I):
        previews.add(match.group(1))
    runtimes = set(re.findall(r"\bpython(3\.\d+)\b", text))
    # Si aparece preview y no puede interpretarse, no inferir una GA silenciosamente.
    if "preview" in text.lower() and "Python" in text and not previews:
        raise ValueError("No se pudo interpretar la advertencia preview de AWS")
    candidates = runtimes - previews
    if not candidates:
        raise ValueError("AWS no publicó runtimes GA reconocibles")
    return max(candidates, key=version_key), sorted(previews, key=version_key)


def github_action(repo, pin):
    source = f"https://api.github.com/repos/{repo}/releases/latest"
    release = fetch(source)
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("GitHub devolvió una release no estable")
    tag = release["tag_name"]
    ref = fetch(f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}")["object"]
    for _ in range(5):
        if ref["type"] == "commit":
            return {"version": tag, "sha": ref["sha"], "source": source}
        if ref["type"] != "tag":
            break
        ref = fetch(f"https://api.github.com/repos/{repo}/git/tags/{ref['sha']}")["object"]
    raise ValueError("No se pudo resolver el tag a un commit")


def cli_release_version(module, changelog):
    version = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", module)
    header = re.search(r"^([0-9][^\n]*)\r?\n=+\s*$", changelog, re.M)
    if not version or not header or not STABLE.fullmatch(version.group(1)):
        raise ValueError("No se encontró una versión CLI estable publicada")
    if version.group(1) != header.group(1).strip():
        raise ValueError("La rama CLI difiere del primer encabezado de CHANGELOG")
    return version.group(1)


def verify_trivy_checksums(checksums, pin):
    published = {name: digest for digest, name in
                 re.findall(r"^([a-f0-9]{64})\s+\*?(\S+)\s*$", checksums, re.M)}
    for suffix, key in (("windows-64bit.zip", "windows_sha256"),
                        ("Linux-64bit.tar.gz", "linux_sha256")):
        filename = f"trivy_{pin['version']}_{suffix}"
        if published.get(filename) != pin[key]:
            raise ValueError(f"El checksum Trivy no coincide: {filename}")


def security_wiring_checks(installer, ci):
    """Detectar divergencias de configuración; el escaneo valida su ejecución real."""
    errors = []
    for token in ("toolchain.versions.json", "trivy", "windows_sha256", "linux_sha256", "sha256", "hexdigest"):
        if token not in installer:
            errors.append(f"Instalador Trivy: falta lectura/verificación {token}")
    for script in ("scripts/install_trivy.py", "scripts/security_scan.py"):
        if script not in ci:
            errors.append(f"CI: falta ejecución {script}")
    if "aquasecurity/trivy-action@" in ci:
        errors.append("CI: Trivy debe usar el instalador verificado del repositorio")
    return errors


def local_checks(manifest, pypi_metadata):
    """Contrastar versiones y hashes con los archivos que realmente se usan."""
    errors = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8-sig"))
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8-sig")
    package_script = (ROOT / "scripts/package.py").read_text(encoding="utf-8-sig")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8-sig"))
    installer_path = ROOT / "scripts/install_trivy.py"
    installer = installer_path.read_text(encoding="utf-8-sig") if installer_path.is_file() else ""
    errors.extend(security_wiring_checks(installer, ci))
    for file, expected in ((".python-version", manifest["python"]["reference"]),
                           (".node-version", manifest["node"]["version"]),
                           (".terraform-version", manifest["terraform"]["version"])):
        if (ROOT / file).read_text(encoding="utf-8-sig").strip() != expected:
            errors.append(f"{file}: pin distinto del manifiesto")
    runners = re.findall(r"runs-on:\s*([^\s]+)", ci)
    if not runners or set(runners) != {manifest["ci_runner"]}:
        errors.append("CI: runner distinto del manifiesto")
    expected_files = {"requirements.lock": set(manifest["pypi"]) - {"setuptools", "pip"},
                      "build-requirements.lock": {"setuptools"}}
    for file, names in expected_files.items():
        text = (ROOT / file).read_text(encoding="utf-8-sig")
        found = dict(re.findall(r"^([\w-]+)==([^\s]+)", text, re.M))
        if set(found) != names:
            errors.append(f"{file}: conjunto de paquetes inesperado")
        for name in names:
            if found.get(name) != manifest["pypi"][name]:
                errors.append(f"{file}: pin distinto para {name}")
            metadata = pypi_metadata.get(name)
            if metadata:
                hashes = {x["digests"]["sha256"] for x in metadata["urls"] if x["packagetype"] == "bdist_wheel" and not x.get("yanked")}
                line = next((line for line in text.splitlines() if line.startswith(name + "==")), "")
                locked_hashes = set(re.findall(r"--hash=sha256:([a-f0-9]{64})", line))
                if not locked_hashes or not locked_hashes <= hashes:
                    errors.append(f"{file}: hash wheel no verificado para {name}")
    if project["project"]["dependencies"] != [f"boto3=={manifest['pypi']['boto3']}"]:
        errors.append("pyproject.toml: dependencia runtime diferente")
    if project["build-system"]["requires"] != [f"setuptools=={manifest['pypi']['setuptools']}"]:
        errors.append("pyproject.toml: backend de construcción diferente")
    if project["project"]["requires-python"] != ">=3.14,<3.16":
        errors.append("pyproject.toml: compatibilidad Python diferente")
    for value in (manifest["python"]["reference"], manifest["python"]["upstream"], manifest["node"]["version"], manifest["terraform"]["version"]):
        if value not in ci:
            errors.append(f"CI: falta pin {value}")
    for tool in ("pip", "npm"):
        version = manifest["pypi"][tool] if tool == "pip" else manifest["npm"]["version"]
        expected = f"pip=={version}" if tool == "pip" else f"npm@{version}"
        if expected not in ci:
            errors.append(f"CI: falta instalación explícita {expected}")
    if package.get("packageManager") != f"npm@{manifest['npm']['version']}" or package.get("engines") != {"node": manifest["node"]["version"], "npm": manifest["npm"]["version"]}:
        errors.append("package.json: versiones Node/npm distintas")
    runtime = manifest["python"]["lambda_ga"]
    if f"'--python-version', '{runtime}'" not in package_script or f"'--abi', 'cp{runtime.replace('.', '')}'" not in package_script:
        errors.append("package.py: runtime o ABI distinto de Lambda GA")
    for layer in ("bootstrap", "foundation", "data", "compute"):
        folder = ROOT / "infra" / layer
        lock = (folder / ".terraform.lock.hcl").read_text(encoding="utf-8-sig")
        source = "\n".join(p.read_text(encoding="utf-8-sig") for p in folder.glob("*.tf"))
        if not re.search(r'version\s*=\s*"' + re.escape(manifest["aws_provider"]["version"]) + '"', lock):
            errors.append(f"{layer}: lock AWS provider distinto")
        if manifest["terraform"]["version"] not in source or manifest["aws_provider"]["version"] not in source:
            errors.append(f"{layer}: restricciones Terraform/provider distintas")
    lambdas = "\n".join(p.read_text(encoding="utf-8-sig") for p in (ROOT / "infra/compute").glob("*.tf"))
    actual_runtimes = re.findall(r'runtime\s*=\s*"(python[^\"]+)"', lambdas)
    if len(actual_runtimes) != 2 or set(actual_runtimes) != {"python" + runtime}:
        errors.append("Infraestructura Lambda: runtime diferente o cantidad inesperada")
    for repo, pin in manifest["actions"].items():
        used = re.findall(re.escape(repo) + r"@([a-f0-9]{40})", ci)
        if not used or set(used) != {pin["sha"]}:
            errors.append(f"CI: SHA distinto para {repo}")
    return errors


def audit(manifest):
    results, metadata = [], {}
    jobs = {}
    for name, version in manifest["pypi"].items():
        jobs["pypi:" + name] = (manifest["pypi_source"].format(name=name), True)
    for name in ("python", "node", "terraform", "aws_provider", "npm", "powershell", "git_windows", "trivy", "aws_cli"):
        jobs[name] = (manifest[name]["source"], name != "aws_cli")
    jobs["lambda"] = (manifest["python"]["lambda_source"], False)

    def check(item):
        name, (url, as_json) = item
        try:
            data = fetch(url, as_json)
            extra = {}
            if name.startswith("pypi:"):
                package = name.split(":", 1)[1]
                current, pinned = data["info"]["version"], manifest["pypi"][package]
                if not STABLE.fullmatch(current):
                    raise ValueError("PyPI latest no es una versión estable")
                if package == "python-dateutil" and package in manifest.get("compatibility", {}):
                    dependency = fetch("https://pypi.org/pypi/botocore/" + manifest["pypi"]["botocore"] + "/json")
                    compatible = latest_compatible_dateutil(data, dependency)
                    extra["upstream_latest"] = current
                    extra["compatibility_reason"] = manifest["compatibility"][package]["reason"]
                    current = compatible
                    data = fetch(f"https://pypi.org/pypi/{package}/{pinned}/json")
                extra["metadata"] = (package, data)
            elif name == "python":
                versions = [r["name"].removeprefix("Python ") for r in data if r.get("is_published") and not r.get("pre_release") and r["name"].startswith("Python 3.")]
                current, pinned = latest(versions), manifest["python"]["upstream"]
                branch = manifest["python"]["lambda_ga"] + "."
                extra["branch_latest"] = latest(v for v in versions if v.startswith(branch))
                if extra["branch_latest"] != manifest["python"]["reference"]:
                    raise ValueError(f"La rama Lambda requiere {extra['branch_latest']}")
            elif name == "lambda":
                current, previews = lambda_latest_ga(data)
                pinned = manifest["python"]["lambda_ga"]
                extra["excluded_previews"] = previews
            elif name == "node":
                current, pinned = latest(r["version"] for r in data), manifest[name]["version"]
                bundled = next(r["npm"] for r in data if r["version"] == "v" + pinned)
                if bundled != manifest["node"]["bundled_npm"]:
                    raise ValueError("El npm incluido en Node cambió")
            elif name == "terraform":
                current, pinned = latest(data["versions"]), manifest[name]["version"]
            elif name in ("powershell", "git_windows", "trivy"):
                if data.get("prerelease") or data.get("draft"):
                    raise ValueError("Release no estable")
                current, pinned = data["tag_name"].removeprefix("v"), manifest[name]["version"]
                if name == "trivy":
                    if not STABLE.fullmatch(current):
                        raise ValueError("La versión Trivy no es estable")
                    checksum_url = next((asset["browser_download_url"] for asset in data["assets"]
                                         if asset["name"] == f"trivy_{current}_checksums.txt"), None)
                    if not checksum_url:
                        raise ValueError("Trivy no publicó el archivo oficial de checksums")
                    checksums = fetch(checksum_url, False)
                    verify_trivy_checksums(checksums, manifest[name])
                    extra["checksums_source"] = checksum_url
            elif name == "aws_cli":
                changelog = fetch(manifest[name]["changelog_source"], False)
                current, pinned = cli_release_version(data, changelog), manifest[name]["version"]
                extra["changelog_source"] = manifest[name]["changelog_source"]
            else:
                current, pinned = data["version"], manifest[name]["version"]
            return {"name": name, "pinned": pinned, "latest": current, "ok": current == pinned, "source": url, **extra}
        except Exception as exc:
            return {"name": name, "ok": False, "source": url, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(check, jobs.items()):
            pair = result.pop("metadata", None)
            if pair:
                metadata[pair[0]] = pair[1]
            results.append(result)
    for repo, pin in manifest["actions"].items():
        try:
            actual = github_action(repo, pin)
            results.append({"name": repo, "pinned": pin, "latest": actual,
                            "ok": actual["version"] == pin["version"] and actual["sha"] == pin["sha"]})
        except Exception as exc:
            results.append({"name": repo, "ok": False, "error": str(exc)})
    try:
        errors = local_checks(manifest, metadata)
    except Exception as exc:
        errors = [str(exc)]
    results.append({"name": "pins_en_archivos", "ok": not errors, "errors": errors})
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "ok": all(r["ok"] for r in results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "toolchain.versions.json").read_text(encoding="utf-8-sig"))
    report = audit(manifest)
    for result in report["results"]:
        print(("OK " if result["ok"] else "ERROR ") + result["name"] + ": " + str(result.get("latest", result.get("error", result.get("errors", "")))))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
