"""Tests for privacy-conscious network diagnostics."""
import unittest

from ortak_piyasa import _classify_tls_first_response, _safe_proxy_endpoint


class WindowsNetworkDiagnosticsTests(unittest.TestCase):
    def test_doh_parser_accepts_global_ipv4_and_ignores_private_answers(self):
        payload = {
            "Status": 0,
            "Answer": [
                {"name": "api.binance.com.", "type": 5, "TTL": 300, "data": "edge.example."},
                {"name": "api.binance.com.", "type": 1, "TTL": 30, "data": "192.168.1.1"},
                {"name": "api.binance.com.", "type": 1, "TTL": 120, "data": "1.1.1.1"},
            ],
        }
        addresses, ttl = ortak_piyasa._parse_doh_ipv4_response(payload)
        self.assertEqual(addresses, ["1.1.1.1"])
        self.assertEqual(ttl, 120)

    def test_doh_parser_rejects_empty_or_non_global_address_set(self):
        with self.assertRaisesRegex(ValueError, "genel kullanıma açık IPv4"):
            ortak_piyasa._parse_doh_ipv4_response({
                "Status": 0,
                "Answer": [{"type": 1, "TTL": 60, "data": "192.168.0.1"}],
            })

    def test_doh_fallback_is_limited_to_approved_market_hosts(self):
        with self.assertRaisesRegex(ValueError, "yalnızca"):
            ortak_piyasa._resolve_market_host_doh("example.com")

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

    def test_http_307_response_keeps_redirect_host_and_server_fingerprint_only(self):
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
