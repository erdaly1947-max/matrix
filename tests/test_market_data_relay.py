"""Tests for the optional cloud market-data relay routing."""
import unittest

import ortak_piyasa


class MarketDataRelayTests(unittest.TestCase):
    def test_blank_relay_keeps_official_direct_hosts(self):
        self.assertIsNone(ortak_piyasa.get_market_data_relay_url({}))
        self.assertEqual(ortak_piyasa.get_binance_rest_bases({}), ortak_piyasa.BINANCE_REST_BASES)
        self.assertEqual(
            ortak_piyasa.get_binance_ws_bases({})[0],
            "wss://data-stream.binance.vision:443/stream?streams=",
        )

    def test_relay_origin_is_normalized(self):
        self.assertEqual(
            ortak_piyasa.get_market_data_relay_url({"market_data_relay_url": "https://example.workers.dev/"}),
            "https://example.workers.dev",
        )

    def test_unsafe_relay_origins_are_rejected(self):
        for value in (
            "http://example.workers.dev",
            "https://user:pass@example.workers.dev",
            "https://example.workers.dev/base-path",
            "https://example.workers.dev/?url=hidden",
            "https://api.binance.com",
            "https://api.btcturk.com",
            "https://example.workers.dev:8443",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ortak_piyasa.get_market_data_relay_url({"market_data_relay_url": value})

    def test_rest_and_websocket_bases_use_relay_exclusively(self):
        settings = {"market_data_relay_url": "https://firsat.example.workers.dev"}
        self.assertEqual(
            ortak_piyasa.get_binance_rest_bases(settings),
            ("https://firsat.example.workers.dev/binance",),
        )
        self.assertEqual(
            ortak_piyasa.get_binance_ws_bases(settings),
            ("wss://firsat.example.workers.dev/ws/binance/stream?streams=",),
        )

    def test_only_allowlisted_exchange_urls_are_rewritten(self):
        relay = "https://firsat.example.workers.dev"
        self.assertEqual(
            ortak_piyasa._relay_public_exchange_url(
                "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m", relay
            ),
            "https://firsat.example.workers.dev/binance/api/v3/klines?symbol=BTCUSDT&interval=5m",
        )
        self.assertEqual(
            ortak_piyasa._relay_public_exchange_url(
                "https://api.btcturk.com/api/v2/server/exchangeinfo", relay
            ),
            "https://firsat.example.workers.dev/btcturk/api/v2/server/exchangeinfo",
        )
        with self.assertRaisesRegex(ValueError, "izin listesinden"):
            ortak_piyasa._relay_public_exchange_url(
                "https://api.binance.com/api/v3/account", relay
            )

    def test_non_exchange_urls_are_not_rewritten(self):
        value = "https://example.org/data?x=1"
        self.assertEqual(ortak_piyasa._relay_public_exchange_url(value, "https://firsat.example.workers.dev"), value)


if __name__ == "__main__":
    unittest.main()
