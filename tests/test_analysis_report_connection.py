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
                    "metrics": {"rsi_14": 61.2, "macd_histogram": 0.02, "unused_blob": "drop"},
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
