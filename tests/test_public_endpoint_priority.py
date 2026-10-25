"""Regression tests for public-data endpoint priority and documented fallbacks."""
import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "binance_erken_firsat_radari.py"


def module_constant(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Top-level constant {name} not found")


class PublicEndpointPriorityTests(unittest.TestCase):
    def test_all_documented_binance_rest_bases_are_kept(self):
        from ortak_piyasa import BINANCE_REST_BASES

        self.assertEqual(
            BINANCE_REST_BASES,
            (
                "https://data-api.binance.vision",
                "https://api.binance.com",
                "https://api-gcp.binance.com",
                "https://api1.binance.com",
                "https://api2.binance.com",
                "https://api3.binance.com",
                "https://api4.binance.com",
            ),
        )

    def test_public_market_data_websocket_is_first(self):
        self.assertEqual(
            module_constant("WS_BASES")[0],
            "wss://data-stream.binance.vision:443/stream?streams=",
        )

    def test_standard_websocket_alternatives_are_preserved(self):
        self.assertEqual(
            module_constant("WS_BASES"),
            (
                "wss://data-stream.binance.vision:443/stream?streams=",
                "wss://stream.binance.com:443/stream?streams=",
                "wss://stream.binance.com:9443/stream?streams=",
            ),
        )


if __name__ == "__main__":
    unittest.main()
