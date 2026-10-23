"""Comprueba la selección de CI y que los controles completos sigan siendo obligatorios."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8-sig')
TOOLCHAIN = json.loads((ROOT / 'toolchain.versions.json').read_text(encoding='utf-8-sig'))


def job_source(name):
    """Extrae un trabajo sin añadir un parser YAML a las dependencias del laboratorio."""
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [a-z]+:\n|\Z)', WORKFLOW, re.M | re.S)
    if not match:
        raise AssertionError(f'No existe el trabajo {name}')
    return match.group(1)


def python_block(job, index=0):
    blocks = re.findall(r"^          python3? - <<'PY'\n(.*?)^          PY$", job_source(job), re.M | re.S)
    return textwrap.dedent(blocks[index])


class CiImpactTests(unittest.TestCase):
    def run_impact_step(self, event='push', base='a' * 40, head='b' * 40, full='false', selections=None):
        """Ejecuta el bloque real de CI con un selector local controlado y sin red."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            fixture = {
                'schema_version': 1, 'mode': 'differential', 'changed_files': ['web/styles.css'],
                'reasons': ['Solo presentación'], 'python_tests': [], 'frontend_tests': [],
                'javascript_checks': [], 'terraform_layers': [], 'evaluations': False,
                'package': False, 'versions': False, 'repository_check': True,
            }
            fixture.update(selections or {})
            selector = (
                'import json, pathlib, sys\n'
                "pathlib.Path('.build').mkdir(exist_ok=True)\n"
                f"pathlib.Path('.build/test-impact.json').write_text({json.dumps(json.dumps(fixture))}, encoding='utf-8')\n"
                "pathlib.Path('arguments.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            )
            (root / 'scripts/test_impact.py').write_text(selector, encoding='utf-8')
            environment = dict(os.environ, EVENT_NAME=event, BASE_SHA=base, HEAD_SHA=head,
                               FULL_VALIDATION=full, GITHUB_OUTPUT=str(root / 'outputs.txt'),
                               GITHUB_STEP_SUMMARY=str(root / 'summary.md'))
            result = subprocess.run([sys.executable, '-c', python_block('impacto')], cwd=root,
                                    env=environment, capture_output=True, text=True, check=True)
            self.assertEqual(result.stderr, '')
            arguments = json.loads((root / 'arguments.json').read_text(encoding='utf-8'))
            outputs = dict(line.split('=', 1) for line in (root / 'outputs.txt').read_text().splitlines())
            return arguments, outputs, (root / 'summary.md').read_text(encoding='utf-8')

    def test_pull_request_compares_base_and_head_as_separate_arguments(self):
        arguments, outputs, summary = self.run_impact_step(event='pull_request')
        self.assertEqual(arguments, ['--output', '.build/test-impact.json', '--base', 'a' * 40, '--head', 'b' * 40])
        self.assertEqual(outputs['python'], 'false')
        self.assertEqual(outputs['frontend'], 'false')
        self.assertEqual(outputs['terraform'], 'false')
        self.assertEqual(outputs['python_tests'], '[]')
        self.assertIn('seguridad se ejecuta siempre', summary)

    def test_first_push_delegates_missing_history_to_the_fail_closed_selector(self):
        arguments, _, _ = self.run_impact_step(base='0' * 40)
        self.assertEqual(arguments, ['--output', '.build/test-impact.json', '--base', '0' * 40,
                                     '--head', 'b' * 40])

    def test_selected_layers_and_suites_enable_only_their_jobs(self):
        _, outputs, _ = self.run_impact_step(selections={
            'python_tests': ['tests/test_application.py'],
            'terraform_layers': ['data', 'compute'],
        })
        self.assertEqual(outputs['python'], 'true')
        self.assertEqual(outputs['terraform'], 'true')
        self.assertEqual(outputs['frontend'], 'false')
        self.assertEqual(json.loads(outputs['terraform_layers']), ['data', 'compute'])
        _, outputs, _ = self.run_impact_step(selections={'frontend_tests': ['tests/web-auth.test.mjs']})
        self.assertEqual(outputs['frontend'], 'true')
        self.assertEqual(outputs['python'], 'false')
        self.assertEqual(outputs['terraform'], 'false')

    def test_manual_full_is_explicit_and_manual_default_is_differential(self):
        arguments, _, _ = self.run_impact_step(event='workflow_dispatch', base='', full='true')
        self.assertIn('--full', arguments)
        arguments, _, _ = self.run_impact_step(event='workflow_dispatch', base='')
        self.assertEqual(arguments[-4:], ['--base', 'HEAD^', '--head', 'b' * 40])

    def test_refs_are_environment_values_and_never_shell_commands(self):
        malicious = 'referencia; printf dato-no-ejecutable'
        arguments, _, _ = self.run_impact_step(base=malicious)
        self.assertEqual(arguments[arguments.index('--base') + 1], malicious)
        block = python_block('impacto')
        self.assertNotIn('${{', block)
        self.assertNotIn('shell=True', block)

    def test_security_and_repository_check_are_always_present(self):
        security = job_source('seguridad')
        self.assertNotIn('    if:', security)
        self.assertNotIn('    needs:', security)
        self.assertIn('python scripts/security_scan.py', security)
        self.assertIn('python3 scripts/check_repository.py', job_source('impacto'))
        self.assertNotIn('paths-ignore:', WORKFLOW)

    def test_python_matrix_excludes_frontend_and_packages_only_base_runtime(self):
        application = job_source('aplicacion')
        frontend = job_source('frontend')
        reference = TOOLCHAIN['python']['reference']
        upstream = TOOLCHAIN['python']['upstream']
        self.assertIn(f"python: ['{reference}', '{upstream}']", application)
        self.assertIn('PYTHONPATH: src:tests', application)
        self.assertNotIn('setup-node@', application)
        self.assertNotIn('node tests/', application)
        self.assertNotIn('matrix:', frontend)
        self.assertEqual(WORKFLOW.count('uses: actions/setup-node@'), 1)
        self.assertIn(f"if: matrix.python == '{reference}' && needs.impacto.outputs.package == 'true'", application)
        self.assertIn(f"if: matrix.python == '{reference}' && needs.impacto.outputs.versions == 'true'", application)

    def test_terraform_matrix_uses_only_reported_layers_without_remote_backend(self):
        terraform = job_source('terraform')
        self.assertIn("if: needs.impacto.outputs.terraform == 'true'", terraform)
        self.assertIn('fromJSON(needs.impacto.outputs.terraform_layers)', terraform)
        self.assertIn("'-backend=false', '-input=false', '-lockfile=readonly'", python_block('terraform'))
        self.assertNotIn('apply', terraform)
        self.assertNotIn('${{', python_block('terraform'))

    def test_inline_python_is_valid_and_actions_keep_immutable_pins(self):
        for job in ('impacto', 'aplicacion', 'terraform'):
            ast.parse(python_block(job))
        actions = re.findall(r'uses: ([^\s]+)', WORKFLOW)
        self.assertTrue(actions)
        self.assertTrue(all(re.fullmatch(r'[A-Za-z0-9_/-]+@[a-f0-9]{40}', action) for action in actions))


if __name__ == '__main__':
    unittest.main()
