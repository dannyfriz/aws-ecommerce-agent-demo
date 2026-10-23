"""Verificación offline del auditor de fuentes y pins efectivos."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("audit_versions", ROOT / "scripts/audit_versions.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class VersionAuditTests(unittest.TestCase):
    def test_stable_selection_ignores_release_candidates(self):
        self.assertEqual(AUDIT.latest(["1.16.6", "1.17.0-rc1", "1.9.9"]), "1.16.6")
        with self.assertRaises(ValueError):
            AUDIT.latest(["3.16.0rc1", "3.16.0b1"])

    def test_lambda_preview_is_excluded_from_ga(self):
        text = "<p>Node.js 26 and Python 3.15 runtimes are in public preview.</p><table>python3.15 python3.14 python3.13</table>"
        self.assertEqual(AUDIT.lambda_latest_ga(text), ("3.14", ["3.15"]))

    def test_lambda_unrecognized_preview_fails_closed(self):
        with self.assertRaises(ValueError):
            AUDIT.lambda_latest_ga("Python: preview changed. python3.15 python3.14")

    def test_annotated_action_tag_is_resolved_to_commit(self):
        with patch.object(AUDIT, "fetch", side_effect=[{"tag_name": "v7.0.1"},
                  {"object": {"type": "tag", "sha": "a" * 40}},
                  {"object": {"type": "commit", "sha": "b" * 40}}]):
            result = AUDIT.github_action("actions/checkout", {})
        self.assertEqual(result["sha"], "b" * 40)

    def test_changed_manifest_does_not_hide_different_actual_ci_pin(self):
        manifest = json.loads((ROOT / "toolchain.versions.json").read_text(encoding="utf-8"))
        altered = copy.deepcopy(manifest)
        altered["actions"]["actions/checkout"]["sha"] = "0" * 40
        errors = AUDIT.local_checks(altered, {})
        self.assertTrue(any("SHA distinto para actions/checkout" in e for e in errors))

    def test_unknown_wheel_hash_is_rejected(self):
        manifest = json.loads((ROOT / "toolchain.versions.json").read_text(encoding="utf-8"))
        metadata = {"boto3": {"urls": [{"packagetype": "bdist_wheel", "digests": {"sha256": "0" * 64}}]}}
        errors = AUDIT.local_checks(manifest, metadata)
        self.assertTrue(any("hash wheel no verificado para boto3" in e for e in errors))

    def test_cli_branch_requires_matching_stable_changelog(self):
        self.assertEqual(AUDIT.cli_release_version("__version__ = '2.38.1'", "2.38.1\n======\n"), "2.38.1")
        for version, changelog in (("2.38.2", "2.38.1\n======\n"), ("2.39.0rc1", "2.39.0rc1\n=========\n")):
            with self.assertRaises(ValueError):
                AUDIT.cli_release_version(f"__version__ = '{version}'", changelog)

    def test_reference_version_file_mismatch_is_reported(self):
        manifest = json.loads((ROOT / "toolchain.versions.json").read_text(encoding="utf-8"))
        manifest["python"]["reference"] = "3.14.0"
        errors = AUDIT.local_checks(manifest, {})
        self.assertTrue(any(".python-version: pin distinto" in error for error in errors))

    def test_trivy_both_platform_checksums_must_match_official_release(self):
        pin = {"version": "0.76.0", "windows_sha256": "a" * 64, "linux_sha256": "b" * 64}
        checksums = "a" * 64 + "  trivy_0.76.0_windows-64bit.zip\n" + "b" * 64 + "  trivy_0.76.0_Linux-64bit.tar.gz\n"
        AUDIT.verify_trivy_checksums(checksums, pin)
        for changed in (checksums.replace("a" * 64, "c" * 64), checksums.splitlines()[0]):
            with self.assertRaises(ValueError):
                AUDIT.verify_trivy_checksums(changed, pin)

    def test_dateutil_uses_latest_compatible_not_latest_upstream(self):
        data = {"releases": {"2.9.0.post0": [{}], "2.9.1": [{"yanked": True}],
                             "3.0.0": [{}], "2.10.0rc1": [{}]}}
        dependency = {"info": {"requires_dist": ["python-dateutil<3.0.0,>=2.1"]}}
        self.assertEqual(AUDIT.latest_compatible_dateutil(data, dependency), "2.9.0.post0")
        dependency["info"]["requires_dist"] = ["python-dateutil<4.0.0,>=2.1"]
        with self.assertRaises(ValueError):
            AUDIT.latest_compatible_dateutil(data, dependency)

    def test_security_installer_must_use_manifest_and_digest(self):
        installer = "toolchain.versions.json trivy windows_sha256 linux_sha256 hashlib.sha256().hexdigest()"
        ci = "python scripts/install_trivy.py\npython scripts/security_scan.py"
        self.assertEqual(AUDIT.security_wiring_checks(installer, ci), [])
        errors = AUDIT.security_wiring_checks(installer.replace("hexdigest", "unchecked"), ci)
        self.assertTrue(any("hexdigest" in error for error in errors))
        self.assertTrue(AUDIT.security_wiring_checks(installer, "aquasecurity/trivy-action@abc"))


if __name__ == "__main__":
    unittest.main()
