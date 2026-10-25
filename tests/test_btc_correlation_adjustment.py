"""Unit tests for the conditional BTC-correlation risk adjustment."""
import unittest

from radar_core import btc_correlation_risk_adjustment, score_opportunity


def corr(value, observations=72, minimum_required=60):
    return {"value": value, "observations": observations, "minimum_required": minimum_required}


RISKY_BTC = {
    "data_completeness": "TAM",
    "direction_score": 1.0,
    "critical_level_score": 1.0,
    "volatility_score": 1.0,
    "relative_volatility_ratio": 1.2,
    "critical_level_loss_timeframes": [],
}

HEALTHY_BTC = {
    "data_completeness": "TAM",
    "direction_score": 4.0,
    "critical_level_score": 3.0,
    "volatility_score": 3.0,
    "relative_volatility_ratio": 1.1,
    "critical_level_loss_timeframes": [],
}


class BtcCorrelationRiskAdjustmentTests(unittest.TestCase):
    def test_high_positive_correlation_in_risky_btc_context_gets_six_point_penalty(self):
        result = btc_correlation_risk_adjustment(
            {"1h": corr(0.90), "4h": corr(0.80, 42, 34)}, RISKY_BTC
        )
        self.assertEqual(result["score_adjustment"], -6)
        self.assertAlmostEqual(result["mean_correlation"], 0.85)
        self.assertTrue(result["risk_condition"])

    def test_moderate_positive_correlation_in_risky_btc_context_gets_three_point_penalty(self):
        result = btc_correlation_risk_adjustment(
            {"1h": corr(0.70), "4h": corr(0.70, 42, 34)}, RISKY_BTC
        )
        self.assertEqual(result["score_adjustment"], -3)

    def test_high_correlation_alone_does_not_penalize_when_btc_context_is_healthy(self):
        result = btc_correlation_risk_adjustment(
            {"1h": corr(0.95), "4h": corr(0.88, 42, 34)}, HEALTHY_BTC
        )
        self.assertEqual(result["score_adjustment"], 0)
        self.assertFalse(result["risk_condition"])

    def test_stale_btc_context_disables_correlation_adjustment(self):
        result = btc_correlation_risk_adjustment(
            {"1h": corr(0.95), "4h": corr(0.88, 42, 34)}, RISKY_BTC, stale=True
        )
        self.assertEqual(result["score_adjustment"], 0)
        self.assertIn("eski/eksik", result["summary"])

    def test_insufficient_synchronized_observations_are_ignored(self):
        result = btc_correlation_risk_adjustment(
            {"1h": corr(0.95, 59, 60), "4h": corr(0.90, 33, 34)}, RISKY_BTC
        )
        self.assertEqual(result["score_adjustment"], 0)
        self.assertEqual(result["timeframes_used"], [])

    def test_negative_correlation_is_not_assumed_safe_or_penalized(self):
        result = btc_correlation_risk_adjustment(
            {"1h": corr(-0.90), "4h": corr(-0.80, 42, 34)}, RISKY_BTC
        )
        self.assertEqual(result["score_adjustment"], 0)

    def test_missing_btc_completeness_never_earns_an_adjustment(self):
        context = dict(RISKY_BTC)
        context.pop("data_completeness")
        result = btc_correlation_risk_adjustment(
            {"1h": corr(0.95)}, context
        )
        self.assertEqual(result["score_adjustment"], 0)
        self.assertIn("tam değil", result["summary"])

    def test_adjustment_is_included_in_candidate_score_components(self):
        candidate = {
            "data_freshness": "CANLI AKIŞ GÜNCEL",
            "btc_market_context_freshness": "CANLI AKIŞ GÜNCEL",
            "btc_return_correlation": {"1h": corr(0.95), "4h": corr(0.90, 42, 34)},
            "phase": "A",
        }
        result = score_opportunity(candidate, btc_context=RISKY_BTC)
        self.assertEqual(result["score_components"]["btc_correlation_risk_adjustment"], -6)
        self.assertEqual(result["btc_correlation_assessment"]["score_adjustment"], -6)


if __name__ == "__main__":
    unittest.main()
