import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from analysis_report import (
    CONFIG_NAME,
    READ_URL,
    UPLOAD_URL,
    _report_endpoint,
    load_connection_config,
)


class CredentialMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.legacy_path = self.root / CONFIG_NAME

    def write_legacy(self, token="test-upload-token", upload_url=UPLOAD_URL):
        self.legacy_path.write_text(
            json.dumps({
                "upload_url": upload_url,
                "upload_token": token,
                "read_url": "https://old-or-custom-read-url.invalid/latest",
            }),
            encoding="utf-8",
        )

    @mock.patch("analysis_report._write_windows_credential", return_value=True)
    @mock.patch("analysis_report._read_windows_credential", side_effect=[None, "test-upload-token"])
    def test_migration_verifies_saved_value_before_removing_legacy_file(self, read_credential, write_credential):
        self.write_legacy()

        config = load_connection_config(self.root)

        self.assertEqual(config["upload_url"], UPLOAD_URL)
        self.assertEqual(config["read_url"], READ_URL)
        self.assertEqual(config["upload_token"], "test-upload-token")
        write_credential.assert_called_once_with("test-upload-token")
        self.assertFalse(self.legacy_path.exists())

    @mock.patch("analysis_report._write_windows_credential", return_value=False)
    @mock.patch("analysis_report._read_windows_credential", return_value=None)
    def test_failed_credential_write_preserves_legacy_file(self, read_credential, write_credential):
        self.write_legacy()

        self.assertIsNone(load_connection_config(self.root))

        write_credential.assert_called_once_with("test-upload-token")
        self.assertTrue(self.legacy_path.exists())

    @mock.patch("analysis_report._write_windows_credential", return_value=True)
    @mock.patch("analysis_report._read_windows_credential", side_effect=[None, "different-token"])
    def test_mismatched_readback_preserves_legacy_file(self, read_credential, write_credential):
        self.write_legacy()

        self.assertIsNone(load_connection_config(self.root))

        self.assertTrue(self.legacy_path.exists())

    @mock.patch("analysis_report._write_windows_credential")
    @mock.patch("analysis_report._read_windows_credential", return_value=None)
    def test_untrusted_legacy_url_is_not_migrated(self, read_credential, write_credential):
        self.write_legacy(upload_url="https://attacker.example/api/report")

        self.assertIsNone(load_connection_config(self.root))

        write_credential.assert_not_called()
        self.assertTrue(self.legacy_path.exists())

    @mock.patch("analysis_report._write_windows_credential")
    @mock.patch("analysis_report._read_windows_credential", return_value="test-upload-token")
    def test_existing_credential_is_used_and_matching_legacy_file_is_removed(self, read_credential, write_credential):
        self.write_legacy()

        config = load_connection_config(self.root)

        self.assertEqual(config["upload_token"], "test-upload-token")
        self.assertEqual(config["upload_url"], UPLOAD_URL)
        write_credential.assert_not_called()
        self.assertFalse(self.legacy_path.exists())

    @mock.patch("analysis_report._write_windows_credential")
    @mock.patch("analysis_report._read_windows_credential", return_value="vault-token")
    def test_existing_credential_wins_but_different_legacy_file_is_preserved(self, read_credential, write_credential):
        self.write_legacy(token="older-token")

        config = load_connection_config(self.root)

        self.assertEqual(config["upload_token"], "vault-token")
        self.assertTrue(self.legacy_path.exists())
        write_credential.assert_not_called()

    @mock.patch("analysis_report._write_windows_credential")
    @mock.patch("analysis_report._read_windows_credential", return_value=None)
    def test_missing_legacy_file_and_credential_returns_none(self, read_credential, write_credential):
        self.assertIsNone(load_connection_config(self.root))
        write_credential.assert_not_called()

    @mock.patch("analysis_report._read_windows_credential", return_value="test-upload-token")
    def test_upload_endpoint_rejects_another_host(self, read_credential):
        with self.assertRaises(ValueError):
            _report_endpoint({
                "upload_url": "https://attacker.example/api/report",
                "upload_token": "test-upload-token",
                "read_url": READ_URL,
            })

    def test_upload_endpoint_keeps_report_routes_on_fixed_worker(self):
        config = {"upload_url": UPLOAD_URL, "upload_token": "test-upload-token", "read_url": READ_URL}
        self.assertEqual(_report_endpoint(config), UPLOAD_URL)
        self.assertEqual(_report_endpoint(config, "daily"), UPLOAD_URL + "/daily")
        self.assertEqual(_report_endpoint(config, "troubleshooting-zip"), UPLOAD_URL + "/troubleshooting-zip")


if __name__ == "__main__":
    unittest.main()
