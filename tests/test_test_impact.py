"""Comprueba la selección diferencial con dependencias reales y repositorios Git aislados."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("test_impact", ROOT / "scripts/test_impact.py")
impact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(impact)


class ImpactTests(unittest.TestCase):
    def test_cli_missing_history_includes_artifact_and_version_validation(self):
        output = io.StringIO()
        with patch.object(impact, 'git_changes', return_value=([], 'Historial insuficiente.')), patch('sys.stdout', output):
            self.assertEqual(impact.main(['--base', '0' * 40]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['mode'], 'full')
        self.assertTrue(plan['package'])
        self.assertTrue(plan['versions'])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        files = {
            "src/ecommerce_agent/__init__.py": "",
            "src/ecommerce_agent/leaf.py": "VALUE = 1\n",
            "src/ecommerce_agent/domain.py": "VALUE = 1\n",
            "src/ecommerce_agent/adapters.py": "from .domain import VALUE\n",
            "src/ecommerce_agent/application.py": "from .domain import VALUE\n",
            "scripts/evaluate_agent.py": "from ecommerce_agent.application import VALUE\nCASES = ROOT / 'scripts' / 'fixtures' / 'agent-evaluation-cases.json'\n",
            "scripts/fixtures/agent-evaluation-cases.json": "{}\n",
            "scripts/seed_demo.py": "VALUE = 1\n",
            "tests/test_leaf.py": "from ecommerce_agent.leaf import VALUE\n",
            "tests/test_application.py": "from ecommerce_agent.application import VALUE\n",
            "tests/test_planner.py": "from ecommerce_agent.adapters import VALUE\n",
            "tests/test_pending.py": "from test_application import VALUE\n",
            "tests/test_unrelated.py": "import unittest\n",
            "tests/test_agent_evaluations.py": "import importlib.util\nSPEC = importlib.util.spec_from_file_location('evaluate', ROOT / 'scripts/evaluate_agent.py')\n",
            "tests/test_seed.py": "SPEC = importlib.util.spec_from_file_location('seed', ROOT / 'scripts/seed_demo.py')\n",
            "web/auth.js": "export const signIn = () => {};\n",
            "web/profiles.js": "export const label = 'cliente';\n",
            "web/app.js": "import {label} from './profiles.js';\n",
            "web/leaf.js": "export const value = 1;\n",
            "web/unrelated.js": "export const value = 2;\n",
            "web/index.html": "<main></main>\n",
            "web/styles.css": "main { color: white; }\n",
            "tests/web-auth.test.mjs": "const auth = await import(new URL('../web/auth.js', import.meta.url));\n",
            "tests/web-leaf.test.mjs": "import {value} from '../web/leaf.js';\n",
            "tests/web-profiles.test.mjs": "import {label} from '../web/profiles.js';\nconst data = readFileSync(new URL('../scripts/fixtures/agent-evaluation-cases.json', import.meta.url));\nconst html = readFileSync(new URL('../web/index.html', import.meta.url));\n",
            "tests/web-review.test.mjs": "const source = readFileSync(new URL('../web/app.js', import.meta.url));\n",
            "tests/web-conversation.test.mjs": "const source = readFileSync(new URL('../web/app.js', import.meta.url));\n",
            "tests/web-evidence.test.mjs": "// Contrato de errores del servidor.\n",
        }
        for name, content in files.items():
            self.write(name, content)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def plan(self, *paths, full=False):
        return impact.build_plan(self.root, list(paths), full=full)

    def assert_no_runtime(self, plan):
        self.assertEqual(plan["mode"], "differential")
        for key in ("python_tests", "frontend_tests", "javascript_checks", "terraform_layers"):
            self.assertEqual(plan[key], [], key)
        for key in ("evaluations", "package", "versions"):
            self.assertFalse(plan[key], key)
        self.assertTrue(plan["repository_check"])

    def test_documentation_and_deleted_presentation_skip_runtime(self):
        self.assert_no_runtime(self.plan("README.md", "docs/presentaciones/demo.pptx", "docs/diagrama.svg"))

    def test_no_changes_still_checks_repository(self):
        self.assert_no_runtime(self.plan())

    def test_python_leaf_only_runs_its_consumers_and_packages_source(self):
        plan = self.plan("src/ecommerce_agent/leaf.py")
        self.assertEqual(plan["python_tests"], ["tests/test_leaf.py"])
        self.assertEqual(plan["frontend_tests"], [])
        self.assertEqual(plan["terraform_layers"], [])
        self.assertTrue(plan["package"])
        self.assertFalse(plan["evaluations"])

    def test_relative_python_imports_and_test_helpers_are_transitive(self):
        plan = self.plan("src/ecommerce_agent/application.py")
        self.assertEqual(plan["python_tests"], ["tests/test_agent_evaluations.py", "tests/test_application.py", "tests/test_pending.py"])
        self.assertTrue(plan["evaluations"])
        self.assertIn("tests/web-review.test.mjs", plan["frontend_tests"])
        self.assertIn("tests/web-evidence.test.mjs", plan["frontend_tests"])
        self.assertNotIn("tests/web-auth.test.mjs", plan["frontend_tests"])

    def test_changed_test_includes_only_itself_and_test_helper_consumers(self):
        plan = self.plan("tests/test_application.py")
        self.assertEqual(plan["python_tests"], ["tests/test_application.py", "tests/test_pending.py"])
        self.assertFalse(plan["package"])
        self.assertFalse(plan["evaluations"])

    def test_package_initializer_is_dependency_of_submodule_imports(self):
        plan = self.plan("src/ecommerce_agent/__init__.py")
        self.assertIn("tests/test_leaf.py", plan["python_tests"])
        self.assertIn("tests/test_pending.py", plan["python_tests"])

    def test_static_importlib_path_selects_script_tests(self):
        plan = self.plan("scripts/seed_demo.py")
        self.assertEqual(plan["mode"], "differential")
        self.assertEqual(plan["python_tests"], ["tests/test_seed.py"])
        self.assertEqual(plan["frontend_tests"], [])
        self.assertFalse(plan["package"])

    def test_literal_import_module_selects_dynamic_consumer(self):
        self.write("tests/test_dynamic.py", "import importlib\nmodule = importlib.import_module('ecommerce_agent.leaf')\n")
        self.assertEqual(self.plan("src/ecommerce_agent/leaf.py")["python_tests"],
                         ["tests/test_dynamic.py", "tests/test_leaf.py"])

    def test_canonical_module_preserves_script_package_for_relative_imports(self):
        self.write("scripts/shared.py", "VALUE = 1\n")
        self.write("scripts/seed_demo.py", "from .shared import VALUE\n")
        self.assertEqual(impact._canonical_module("scripts/seed_demo.py"), "scripts.seed_demo")
        self.assertEqual(impact._canonical_module("src/ecommerce_agent/__init__.py"), "ecommerce_agent")
        self.assertEqual(self.plan("scripts/shared.py")["python_tests"], ["tests/test_seed.py"])

    def test_packaging_helper_changes_require_package_transitively(self):
        self.write("scripts/package_support.py", "VALUE = 1\n")
        self.write("scripts/package.py", "from .package_support import VALUE\n")
        self.write("tests/test_package.py", "SPEC = importlib.util.spec_from_file_location('package', ROOT / 'scripts/package.py')\n")
        plan = self.plan("scripts/package_support.py")
        self.assertEqual(plan["mode"], "differential")
        self.assertEqual(plan["python_tests"], ["tests/test_package.py"])
        self.assertTrue(plan["package"])
        self.assertFalse(plan["versions"])

    def test_planner_changes_include_evaluations_and_frontend_contracts(self):
        plan = self.plan("src/ecommerce_agent/adapters.py")
        self.assertEqual(plan["mode"], "differential")
        self.assertEqual(plan["python_tests"], ["tests/test_planner.py"])
        self.assertTrue(plan["evaluations"])
        self.assertIn("tests/web-review.test.mjs", plan["frontend_tests"])
        self.assertTrue(plan["package"])

    def test_contract_mapping_does_not_hide_missing_python_coverage(self):
        self.write("src/ecommerce_agent/identity.py", "VALUE = 1\n")
        self.assertEqual(self.plan("src/ecommerce_agent/identity.py")["mode"], "full")

    def test_frontend_leaf_only_runs_its_test_and_syntax_check(self):
        plan = self.plan("web/leaf.js")
        self.assertEqual(plan["frontend_tests"], ["tests/web-leaf.test.mjs"])
        self.assertEqual(plan["javascript_checks"], ["web/leaf.js"])
        self.assertEqual(plan["python_tests"], [])
        self.assertEqual(plan["terraform_layers"], [])
        self.assertFalse(plan["package"])

    def test_dynamic_javascript_import_is_not_missed(self):
        plan = self.plan("web/auth.js")
        self.assertEqual(plan["frontend_tests"], ["tests/web-auth.test.mjs"])

    def test_frontend_transitive_imports_include_vm_suites(self):
        plan = self.plan("web/profiles.js")
        self.assertEqual(plan["frontend_tests"], ["tests/web-conversation.test.mjs", "tests/web-profiles.test.mjs", "tests/web-review.test.mjs"])
        self.assertEqual(plan["javascript_checks"], ["web/app.js", "web/profiles.js"])
        self.assertEqual(plan["python_tests"], [])

    def test_app_source_changes_select_suites_that_load_it_in_vm(self):
        plan = self.plan("web/app.js")
        self.assertEqual(plan["frontend_tests"], ["tests/web-conversation.test.mjs", "tests/web-review.test.mjs"])
        self.assertEqual(plan["python_tests"], [])

    def test_html_selects_real_consumer_but_styles_do_not_invent_suites(self):
        self.assertEqual(self.plan("web/index.html")["frontend_tests"], ["tests/web-profiles.test.mjs"])
        self.assert_no_runtime(self.plan("web/styles.css"))

    def test_fixtures_select_evaluator_and_browser_contract(self):
        plan = self.plan("scripts/fixtures/agent-evaluation-cases.json")
        self.assertEqual(plan["python_tests"], ["tests/test_agent_evaluations.py"])
        self.assertEqual(plan["frontend_tests"], ["tests/web-profiles.test.mjs"])
        self.assertTrue(plan["evaluations"])
        self.assertFalse(plan["package"])

    def test_policy_document_is_not_treated_as_unrelated_documentation(self):
        plan = self.plan("docs/politicas-posventa-demo.md")
        self.assertTrue(plan["evaluations"])
        self.assertIn("tests/test_agent_evaluations.py", plan["python_tests"])

    def test_terraform_downstream_layers_follow_remote_state(self):
        for layer, expected in (("compute", ["compute"]), ("data", ["data", "compute"]),
                                ("foundation", ["foundation", "data", "compute"]),
                                ("bootstrap", list(impact.LAYERS))):
            with self.subTest(layer=layer):
                plan = self.plan(f"infra/{layer}/main.tf")
                self.assertEqual(plan["mode"], "differential")
                self.assertEqual(plan["terraform_layers"], expected)
                self.assertEqual(plan["python_tests"], [])

    def test_changed_terraform_test_does_not_expand_downstream(self):
        plan = self.plan("infra/foundation/tests/security.tftest.hcl")
        self.assertEqual(plan["terraform_layers"], ["foundation"])

    def test_validation_controls_and_pins_force_full_with_version_audit_only_when_needed(self):
        for path in ("scripts/Test.ps1", "scripts/test_impact.py", ".github/workflows/ci.yml",
                     "requirements.lock", "toolchain.versions.json", "infra/compute/versions.tf"):
            with self.subTest(path=path):
                plan = self.plan(path)
                self.assertEqual(plan["mode"], "full")
                self.assertEqual(plan["terraform_layers"], list(impact.LAYERS))
                self.assertEqual(plan["versions"], path in {
                    ".github/workflows/ci.yml", "requirements.lock", "toolchain.versions.json",
                    "infra/compute/versions.tf"})

    def test_unknown_executable_and_uncovered_new_module_force_full(self):
        self.write("src/ecommerce_agent/new_feature.py", "VALUE = 1\n")
        for path in ("scripts/new_runner.ps1", "src/ecommerce_agent/new_feature.py", "runtime-config.yaml"):
            with self.subTest(path=path):
                self.assertEqual(self.plan(path)["mode"], "full")

    def test_deleted_module_remains_resolvable_from_live_imports(self):
        (self.root / "src/ecommerce_agent/leaf.py").unlink()
        plan = self.plan("src/ecommerce_agent/leaf.py")
        self.assertEqual(plan["mode"], "differential")
        self.assertEqual(plan["python_tests"], ["tests/test_leaf.py"])

    def test_new_test_has_coverage_by_itself(self):
        self.write("tests/test_new.py", "import unittest\n")
        plan = self.plan("tests/test_new.py")
        self.assertEqual(plan["mode"], "differential")
        self.assertEqual(plan["python_tests"], ["tests/test_new.py"])

    def test_parse_error_falls_back_to_full_instead_of_hiding_dependencies(self):
        self.write("src/ecommerce_agent/leaf.py", "def broken(:\n")
        plan = self.plan("src/ecommerce_agent/leaf.py")
        self.assertEqual(plan["mode"], "full")
        self.assertTrue(any("SyntaxError" in reason for reason in plan["reasons"]))

    def test_explicit_full_preserves_schema_and_does_not_invent_version_changes(self):
        plan = self.plan("README.md", full=True)
        self.assertEqual(set(plan), {"schema_version", "mode", "changed_files", "reasons", "python_tests",
                                     "frontend_tests", "javascript_checks", "terraform_layers", "evaluations",
                                     "package", "versions", "repository_check"})
        self.assertEqual(plan["mode"], "full")
        self.assertTrue(plan["python_tests"])
        self.assertTrue(plan["frontend_tests"])
        self.assertFalse(plan["versions"])
        self.assertFalse(plan["package"])

    def test_paths_are_normalized_and_escape_is_rejected(self):
        self.assertEqual(self.plan(r".\web\leaf.js")["changed_files"], ["web/leaf.js"])
        for path in ("../outside.py", "/outside.py", r"C:\outside.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.plan(path)

    def test_cli_explicit_files_writes_json_without_stdout(self):
        output = self.root / "plan.json"
        with patch.object(impact, "__file__", str(self.root / "scripts/test_impact.py")), patch("sys.stdout") as stdout:
            self.assertEqual(impact.main(["--files", "README.md", "--output", str(output)]), 0)
        stdout.write.assert_not_called()
        self.assert_no_runtime(json.loads(output.read_text(encoding="utf-8")))


class GitImpactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Pruebas diferenciales")
        self.git("config", "user.email", "tests@example.test")
        self.git("config", "commit.gpgsign", "false")
        self.write("docs/base.md", "base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "docs: preparar prueba aislada")
        self.base = self.git("rev-parse", "HEAD").strip()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    def test_local_diff_includes_staged_unstaged_untracked_and_unicode(self):
        self.write("docs/base.md", "modificado\n")
        self.write("docs/con espacios y ñ.md", "nuevo\n")
        self.git("add", "docs/con espacios y ñ.md")
        self.write("web/nuevo.js", "export const value = 1;\n")
        paths, fallback = impact.git_changes(self.root)
        self.assertIsNone(fallback)
        self.assertEqual(paths, ["docs/base.md", "docs/con espacios y ñ.md", "web/nuevo.js"])

    def test_committed_base_diff_keeps_both_sides_of_rename_and_deletions(self):
        self.write("docs/borrar.md", "borrar\n")
        self.git("add", ".")
        self.git("commit", "-qm", "docs: preparar eliminación")
        base = self.git("rev-parse", "HEAD").strip()
        self.git("mv", "docs/base.md", "docs/nuevo nombre.md")
        self.git("rm", "docs/borrar.md")
        self.git("commit", "-qm", "docs: mover y retirar documentos")
        paths, fallback = impact.git_changes(self.root, base)
        self.assertIsNone(fallback)
        self.assertEqual(paths, ["docs/base.md", "docs/borrar.md", "docs/nuevo nombre.md"])
        self.assertEqual(impact.build_plan(self.root, paths)["mode"], "differential")

    def test_merge_base_excludes_changes_that_only_happen_on_base_branch(self):
        self.git("checkout", "-qb", "base_branch")
        self.write("docs/solo-base.md", "base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "docs: cambiar base")
        self.git("checkout", "-qb", "feature", self.base)
        self.write("docs/solo-feature.md", "feature\n")
        self.git("add", ".")
        self.git("commit", "-qm", "docs: cambiar feature")
        self.assertEqual(impact.git_changes(self.root, "base_branch"), (["docs/solo-feature.md"], None))

    def test_zero_or_missing_base_returns_explicit_full_fallback(self):
        for base in ("0" * 40, "not-a-real-ref", ""):
            with self.subTest(base=base):
                paths, fallback = impact.git_changes(self.root, base)
                self.assertEqual(paths, [])
                self.assertIn("validación completa", fallback)

    def test_repository_without_history_has_full_fallback(self):
        empty = self.root / "empty"
        empty.mkdir()
        subprocess.run(["git", "-C", str(empty), "init", "-q"], check=True)
        paths, fallback = impact.git_changes(empty)
        self.assertEqual(paths, [])
        self.assertIn("Historial Git insuficiente", fallback)


if __name__ == "__main__":
    unittest.main()
