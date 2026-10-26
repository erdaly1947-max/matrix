import unittest
from unittest.mock import patch

from ortak_piyasa import fetch_btcturk_usdt_last_prices


class BtcTurkPriceTests(unittest.TestCase):
    def test_only_exact_usdt_spot_pairs_with_positive_finite_last_are_returned(self):
        payload = {
            "success": True,
            "data": [
                {"pair": "BTCUSDT", "numeratorSymbol": "BTC", "denominatorSymbol": "USDT", "last": "67250.5"},
                {"pair": "ETHUSDT", "numeratorSymbol": "ETH", "denominatorSymbol": "USDT", "last": 2500},
                {"pair": "BTCTRY", "numeratorSymbol": "BTC", "denominatorSymbol": "TRY", "last": 1000000},
                {"pair": "BADUSDT", "numeratorSymbol": "BAD", "denominatorSymbol": "USDT", "last": 0},
                {"pair": "NANUSDT", "numeratorSymbol": "NAN", "denominatorSymbol": "USDT", "last": "nan"},
                {"pair": "BTCUSDC", "numeratorSymbol": "BTC", "denominatorSymbol": "USDC", "last": 67000},
            ],
        }
        with patch("ortak_piyasa._json_get", return_value=payload) as get_json:
            prices = fetch_btcturk_usdt_last_prices()
        self.assertEqual(prices, {"BTCUSDT": 67250.5, "ETHUSDT": 2500.0})
        get_json.assert_called_once()

    def test_uses_fallback_ticker_when_primary_has_no_usable_prices(self):
        empty = {"success": True, "data": []}
        fallback = {
            "success": True,
            "data": [
                {"pair": "SOLUSDT", "numeratorSymbol": "SOL", "denominatorSymbol": "USDT", "last": "145.25"}
            ],
        }
        with patch("ortak_piyasa._json_get", side_effect=[empty, fallback]) as get_json:
            prices = fetch_btcturk_usdt_last_prices()
        self.assertEqual(prices, {"SOLUSDT": 145.25})
        self.assertEqual(get_json.call_count, 2)

    def test_raises_clear_error_when_both_ticker_endpoints_fail(self):
        with patch("ortak_piyasa._json_get", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "BtcTurk güncel USDT fiyatları alınamadı"):
                fetch_btcturk_usdt_last_prices()


if __name__ == "__main__":
    unittest.main()
