"""Security and fallback tests for Windows HTTPS TLS errors."""
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import requests

import ortak_piyasa


def successful_response(body=b'{"success": true}'):
    response = requests.Response()
    response.status_code = 200
    response._content = body
    response._content_consumed = True
    return response


class WindowsCurlTlsFallbackTests(unittest.TestCase):
    @patch("ortak_piyasa.sys.platform", "win32")
    @patch("ortak_piyasa.shutil.which", return_value=r"C:\\Windows\\System32\\curl.exe")
    @patch("ortak_piyasa.subprocess.run")
    def test_curl_fallback_keeps_certificate_validation_and_prepares_query(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=["curl.exe"], returncode=0, stdout=b'{"success": true}', stderr=b""
        )
        response = ortak_piyasa._curl_get_fallback(
            "https://api.example.test/api/v3/exchangeInfo",
            params={"symbol": "BTCUSDT"},
            timeout=4.5,
            headers={"User-Agent": "test-client"},
        )
        command = run.call_args.args[0]
        self.assertEqual(response.json(), {"success": True})
        self.assertIn("--disable", command)
        self.assertIn("--fail", command)
        self.assertIn("--location", command)
        self.assertFalse(any(arg in {"-k", "--insecure"} for arg in command))
        self.assertIn("symbol=BTCUSDT", command[-1])
        self.assertTrue(command[-1].startswith("https://"))

    @patch("ortak_piyasa.sys.platform", "win32")
    def test_curl_fallback_refuses_plain_http(self):
        with self.assertRaisesRegex(ValueError, "yalnızca HTTPS"):
            ortak_piyasa._curl_get_fallback(
                "http://api.example.test/data",
                params=None,
                timeout=2.0,
                headers={},
            )

    @patch("ortak_piyasa.sys.platform", "win32")
    @patch("ortak_piyasa._doh_market_get", side_effect=RuntimeError("DoH not available in unit test"))
    @patch("ortak_piyasa.requests.get", side_effect=requests.exceptions.SSLError("TLS WRONG_VERSION_NUMBER"))
    @patch("ortak_piyasa.requests.utils.get_environ_proxies", return_value={})
    @patch("ortak_piyasa.requests.Session")
    @patch("ortak_piyasa._curl_get_fallback", return_value=successful_response())
    def test_windows_tls_error_uses_secure_curl_fallback(
        self, curl_fallback, session_factory, _proxies, _requests_get, _doh_fallback
    ):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = requests.exceptions.SSLError("TLS WRONG_VERSION_NUMBER")
        session_factory.return_value = session
        response = ortak_piyasa._requests_get(
            "https://api.example.test/data",
            params=None,
            timeout=3.0,
            headers={"User-Agent": "test-client"},
        )
        self.assertEqual(response.status_code, 200)
        curl_fallback.assert_called_once()

    @patch("ortak_piyasa.sys.platform", "win32")
    @patch("ortak_piyasa.shutil.which", return_value=r"C:\\Windows\\System32\\curl.exe")
    @patch("ortak_piyasa.subprocess.run")
    def test_failed_curl_request_reports_error(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=["curl.exe"], returncode=35, stdout=b"",
            stderr=b"TLS connect error"
        )
        with self.assertRaisesRegex(RuntimeError, "curl.exe HTTPS yedeği başarısız"):
            ortak_piyasa._curl_get_fallback(
                "https://api.example.test/data",
                params=None,
                timeout=3.0,
                headers={},
            )


if __name__ == "__main__":
    unittest.main()
