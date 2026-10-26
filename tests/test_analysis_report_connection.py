import gzip
import json
import unittest

from analysis_report import build_analysis_report, compress_analysis_report


class AnalysisReportTests(unittest.TestCase):
    def test_report_keeps_decision_and_risk_plan_but_drops_raw_candles(self):
        state = {
            "application_version": "00",
            "generated_at_utc": "2026-10-26T12:00:00Z",
            "status": "RUNNING",
            "runtime_diagnostics": {"secret": "must-not-appear"},
            "btc_market_context": {"status": "BULLISH"},
            "candidates": [{
                "symbol": "ABCUSDT",
                "opportunity_score": 82,
                "final_decision": "GİRİŞ KOŞULU BEKLE",
                "risk_plan": {"entry_zone_low": 1.2, "stop_loss": 1.1, "targets": [{"price": 1.4}]},
                "recent_closed_candles": {"1h": [{"close": 1.0}]},
                "btc_market_context": {"duplicated": True},
                "timeframes": {"1h": {
                    "phase": "B",
                    "data_sufficient": True,
                    "findings": ["yükselen dipler"],
                    "metrics": {"rsi_14": 61.2, "macd_histogram": 0.02, "unused_blob": "drop",
                    "fibonacci": {"status": "TEYİTLİ SALINIM", "available": True, "direction": "down",
                        "retracements": {"retracement_0_618": 1.78}, "raw_blob": "drop"},
                    "support_resistance_zones": [{"kind": "support", "center": 1.2, "lower": 1.19,
                        "upper": 1.21, "touch_count": 3, "strong": True, "raw_blob": "drop"}],
                    "confirmed_channel": {"status": "TEYİTLİ KANAL", "available": True,
                        "direction": "YÜKSELEN", "upper_now": 1.4, "lower_now": 1.2, "raw_blob": "drop"}},
                }},
            }],
        }
        report = build_analysis_report(state)
        self.assertEqual(report["report_type"], "analysis")
        self.assertEqual(report["candidate_count"], 1)
        candidate = report["candidates"][0]
        self.assertEqual(candidate["final_decision"], "GİRİŞ KOŞULU BEKLE")
        self.assertEqual(candidate["risk_plan"]["stop_loss"], 1.1)
        self.assertNotIn("recent_closed_candles", candidate)
        self.assertNotIn("btc_market_context", candidate)
        self.assertNotIn("runtime_diagnostics", report)
        self.assertEqual(candidate["timeframes"]["1h"]["metrics"]["rsi_14"], 61.2)
        self.assertNotIn("unused_blob", candidate["timeframes"]["1h"]["metrics"])
        metrics = candidate["timeframes"]["1h"]["metrics"]
        self.assertEqual(metrics["fibonacci"]["retracements"]["retracement_0_618"], 1.78)
        self.assertNotIn("raw_blob", metrics["fibonacci"])
        self.assertEqual(metrics["support_resistance_zones"][0]["center"], 1.2)
        self.assertNotIn("raw_blob", metrics["support_resistance_zones"][0])
        self.assertEqual(metrics["confirmed_channel"]["direction"], "YÜKSELEN")
        self.assertNotIn("raw_blob", metrics["confirmed_channel"])

    def test_gzip_round_trip_and_size_reduction(self):
        state = {"candidates": [{"symbol": "ABCUSDT", "findings": ["yükselen dip"] * 100}]}
        payload = build_analysis_report(state)
        compressed = compress_analysis_report(payload)
        decoded = json.loads(gzip.decompress(compressed).decode("utf-8"))
        self.assertEqual(decoded["candidate_count"], 1)
        self.assertLess(len(compressed), len(json.dumps(payload, ensure_ascii=False).encode("utf-8")))

    def test_invalid_nan_is_not_silently_serialized(self):
        with self.assertRaises(ValueError):
            compress_analysis_report({"report_type": "analysis", "bad": float("nan")})


if __name__ == "__main__":
    unittest.main()
