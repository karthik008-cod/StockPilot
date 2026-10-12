"""Tests for StockRecommender and ML Smart Picks selection."""

import unittest
from unittest.mock import MagicMock
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

    def test_trade_planner_strictly_enforces_1_to_1_rr_and_supports(self):
        """Verify TradePlanner detects chart support/resistance and enforces R:R >= 1.0."""
        planner = TradePlanner()
        n = 50
        dates = pd.date_range("2026-08-01", periods=n, freq="B")
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
                market_regime={"nifty_trend": "Bullish", "vix_level": 14.5},
            )
            self.assertGreaterEqual(plan.risk_reward_ratio, 1.0, f"R:R ratio failed for term {term}")
            self.assertGreaterEqual(
                round(plan.target_1 - plan.entry_price, 2),
                round(plan.entry_price - plan.stop_loss, 2),
                f"Reward < Risk for term {term}"
            )
            self.assertIn("price", plan.support_1)
            self.assertIn("price", plan.resistance_1)
            self.assertGreater(plan.resistance_1["price"], 0)
            self.assertGreater(plan.support_1["price"], 0)
            self.assertIn("INR", plan.technical_reasoning)

    def test_market_regime_and_news_analysis(self):
        """Verify market regime and news analysis structure in recommender."""
        regime = self.recommender._get_market_regime()
        self.assertIn("nifty_trend", regime)
        self.assertIn("vix_level", regime)
        self.assertIn("market_bias", regime)

        # Mock news loader
        self.recommender.loader.load_news = MagicMock(return_value=[
            {"title": "Company reports record profit surge in Q2", "date": "2026-10-12"}
        ])
        news_res = self.recommender._analyze_stock_news("TEST.NS")
        self.assertEqual(news_res["news_count"], 1)
        self.assertGreater(news_res["sentiment_score"], 0.0)
        self.assertEqual(news_res["catalyst_impact"], "Positive")


if __name__ == "__main__":
    unittest.main()
