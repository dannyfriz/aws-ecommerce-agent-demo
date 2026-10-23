"""El gate de seguridad conserva evidencia y falla ante análisis incompletos."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('security_scan', ROOT / 'scripts/security_scan.py')
SCAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCAN)


class SecurityScanTests(unittest.TestCase):
    def summarize(self, result):
        records = list(SCAN.findings({'Results': [result]}))
        return SCAN.build_summary(records, {}, '0.76.0', checked_at='2026-10-17T00:00:00Z')

    def test_high_unfixed_vulnerability_blocks(self):
        summary = self.summarize({'Target': 'requirements.txt', 'Vulnerabilities': [
            {'VulnerabilityID': 'CVE-TEST', 'Severity': 'HIGH', 'PkgName': 'package',
             'InstalledVersion': '1.0.0', 'FixedVersion': ''}]})
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['blocking_count'], 1)
        self.assertEqual(summary['findings'][0]['fixed'], '')

    def test_medium_is_reported_without_blocking(self):
        summary = self.summarize({'Target': 'main.tf', 'Misconfigurations': [
            {'ID': 'AVD-TEST', 'Severity': 'MEDIUM', 'Status': 'FAIL', 'Title': 'Revisar control'}]})
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['counts'], {'MEDIUM': 1})
        self.assertEqual(len(summary['findings']), 1)

    def test_high_secret_blocks_without_exposing_secret(self):
        summary = self.summarize({'Target': 'sample.py', 'Secrets': [
            {'RuleID': 'test-token', 'Severity': 'HIGH', 'Title': 'Token detectado',
             'Match': 'sensitive-value', 'Code': {'Lines': ['sensitive-value']}}]})
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['findings'][0]['type'], 'Secrets')
        self.assertNotIn('sensitive-value', str(summary))
        self.assertNotIn('sensitive-value', SCAN.render_markdown(summary))

    def test_pass_misconfiguration_is_not_a_finding(self):
        summary = self.summarize({'Target': 'main.tf', 'Misconfigurations': [
            {'ID': 'AVD-PASS', 'Severity': 'HIGH', 'Status': 'PASS'},
            {'ID': 'AVD-FAIL', 'Severity': 'LOW', 'Status': 'FAIL'}]})
        self.assertTrue(summary['passed'])
        self.assertEqual([item['id'] for item in summary['findings']], ['AVD-FAIL'])

    def test_missing_pip_target_is_incomplete_even_with_no_vulnerabilities(self):
        for report in ({}, {'Results': []}, {'Results': [{'Type': 'terraform'}]}):
            with self.assertRaises(ValueError):
                SCAN.validate_dependency_report(report)
        SCAN.validate_dependency_report({'Results': [{'Target': 'requirements.txt', 'Type': 'pip'}]})

    def test_inventory_requires_all_pins_and_exact_versions(self):
        expected = {'boto3': '1.43.114', 'python-dateutil': '2.9.0.post0'}
        packages = [{'Name': 'boto3', 'Version': '1.43.114'}, {'Name': 'python_dateutil', 'Version': '2.9.0.post0'}]
        report = {'Results': [{'Type': 'pip', 'Packages': packages}]}
        self.assertEqual(SCAN.validate_dependency_report(report, expected), 2)
        with self.assertRaises(ValueError):
            SCAN.validate_dependency_report({'Results': [{'Type': 'pip'}]}, expected)
        with self.assertRaises(ValueError):
            SCAN.validate_dependency_report(report, {'boto3': '0.0.0'})
        with self.assertRaises(ValueError):
            SCAN.validate_dependency_report(report, {**expected, 'pip': '26.2.1'})

    def test_markdown_keeps_medium_and_escapes_untrusted_fields(self):
        summary = self.summarize({'Target': 'file|<bad>\nsecond', 'Vulnerabilities': [
            {'VulnerabilityID': 'CVE-MEDIUM', 'Severity': 'MEDIUM', 'PkgName': 'example'}]})
        markdown = SCAN.render_markdown(summary)
        self.assertIn('CVE-MEDIUM', markdown)
        self.assertIn('| MEDIUM | 1 |', markdown)
        self.assertIn('file&#124;&lt;bad&gt; second', markdown)
        self.assertIn('Gate aprobado', markdown)


if __name__ == '__main__':
    unittest.main()
