"""Tests for privacy-conscious network diagnostics."""
import unittest

from ortak_piyasa import _classify_tls_first_response, _safe_proxy_endpoint


class WindowsNetworkDiagnosticsTests(unittest.TestCase):
    def test_proxy_summary_redacts_credentials_path_and_query(self):
        value = "http://user:secret@proxy.example:8080/private/path?token=hidden"
        summary = _safe_proxy_endpoint(value)
        self.assertEqual(summary, "http://proxy.example:8080")
        for private_value in ("user", "secret", "private", "hidden"):
            self.assertNotIn(private_value, summary)

    def test_proxy_summary_handles_missing_scheme(self):
        self.assertEqual(
            _safe_proxy_endpoint("proxy.example:3128"),
            "scheme-unspecified://proxy.example:3128",
        )

    def test_plain_http_response_is_not_misreported_as_tls(self):
        raw = b"HTTP/1.1 407 Proxy Authentication Required\r\nX-Private: secret\r\n\r\nprivate body"
        summary = _classify_tls_first_response(raw)
        self.assertEqual(
            summary, "plain_http_response_instead_of_tls:HTTP/1.1 407"
        )
        self.assertNotIn("secret", summary)
        self.assertNotIn("private", summary)

    def test_redirect_diagnostics_expose_host_but_hide_sensitive_url_parts(self):
        raw = (
            b"HTTP/1.1 307 Temporary Redirect\r\n"
            b"Location: http://filter.example.invalid:8080/blocked?device=private\r\n"
            b"Server: Home Gateway/1.2\r\n"
            b"Via: 1.1 local-filter\r\n"
            b"\r\n"
        )
        summary = _classify_tls_first_response(raw)
        self.assertIn("plain_http_response_instead_of_tls:HTTP/1.1 307", summary)
        self.assertIn("redirect_target=http://filter.example.invalid:8080", summary)
        self.assertIn("server_header=Home_Gateway/1.2", summary)
        self.assertIn("via_header=present", summary)
        self.assertNotIn("/blocked", summary)
        self.assertNotIn("device=private", summary)

    def test_winhttp_diagnostic_failure_does_not_abort(self):
        from unittest.mock import patch
        import ortak_piyasa

        with patch.object(ortak_piyasa.sys, "platform", "win32"):
            with patch.object(ortak_piyasa.shutil, "which", side_effect=AttributeError):
                self.assertEqual(
                    ortak_piyasa._winhttp_proxy_status(),
                    "query_failed:AttributeError",
                )

    def test_tls_record_header_is_recognized(self):
        summary = _classify_tls_first_response(b"\x16\x03\x03\x00\x05hello")
        self.assertEqual(
            summary,
            "tls_record_header_received:content_type=0x16:version=0x0303",
        )

    def test_unknown_response_logs_only_hex_prefix(self):
        summary = _classify_tls_first_response(b"gateway-error-private-data")
        self.assertEqual(
            summary, "non_tls_or_unknown_response:first8_hex=676174657761792d"
        )
        self.assertNotIn("gateway-error", summary)


if __name__ == "__main__":
    unittest.main()
