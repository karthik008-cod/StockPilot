"""Tests for StockRecommender and ML Smart Picks selection."""

import unittest
import pandas as pd
import numpy as np

from stockpilot.ml.recommender import (
    StockRecommender,
    StockScore,
    MIN_RISK_REWARD_RATIO,
    _score_risk_reward,
)
from stockpilot.trade.planner import TradePlanner


class TestStockRecommender(unittest.TestCase):

    def setUp(self):
        self.recommender = StockRecommender()

    def test_min_risk_reward_constant(self):
        """Verify minimum risk-to-reward ratio threshold is at least 1.0."""
        self.assertGreaterEqual(MIN_RISK_REWARD_RATIO, 1.0)

    def test_score_risk_reward(self):
        """Verify R:R scoring returns 0 for R:R < 1.0 and rewards higher R:R."""
        self.assertEqual(_score_risk_reward(0.8), 0.0)
        self.assertEqual(_score_risk_reward(1.0), 50.0)
        self.assertEqual(_score_risk_reward(1.5), 75.0)
        self.assertEqual(_score_risk_reward(2.0), 90.0)
        self.assertEqual(_score_risk_reward(2.5), 100.0)
        self.assertEqual(_score_risk_reward(3.0), 100.0)

    def test_trade_planner_strictly_enforces_1_to_1_rr(self):
        """Verify TradePlanner never produces a trade plan with R:R < 1.0."""
        planner = TradePlanner()
        # Create a mock dataframe
        n = 30
        dates = pd.date_range("2026-09-01", periods=n, freq="B")
        close = np.linspace(100.0, 120.0, n)
        high = close + 2.0
        low = close - 2.0
        df = pd.DataFrame({
            "Date": dates,
            "Open": close,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": 100000,
        })
        for term in ["short", "medium", "long"]:
            plan = planner.plan_full_trade(
                df=df,
                ticker="TEST.NS",
                trade_term=term,
            )
            self.assertGreaterEqual(plan.risk_reward_ratio, 1.0, f"R:R ratio failed for term {term}")
            self.assertGreaterEqual(
                round(plan.target_1 - plan.entry_price, 2),
                round(plan.entry_price - plan.stop_loss, 2),
                f"Reward < Risk for term {term}"
            )


if __name__ == "__main__":
    unittest.main()
