"""Unit tests for TradePlanner (Option A: Full Trade vs Option B: Deadline-Constrained)."""

from datetime import date, timedelta
import unittest
import numpy as np
import pandas as pd

from stockpilot.trade.planner import DeadlineTradePlan, FullTradePlan, TradePlanner


class TestTradePlanner(unittest.TestCase):

    def setUp(self):
        np.random.seed(42)
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        # Steady uptrend with realistic daily volatility
        base = 2500.0
        close = base + np.cumsum(np.random.normal(1.5, 12.0, n))
        high = close + np.random.uniform(5.0, 20.0, n)
        low = close - np.random.uniform(5.0, 20.0, n)
        open_p = (high + low) / 2.0
        volume = np.random.randint(100000, 2000000, n)

        self.df = pd.DataFrame({
            "Date": dates,
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        })
        self.planner = TradePlanner(atr_window=14)

    def test_plan_full_trade_option_a(self):
        plan = self.planner.plan_full_trade(self.df, ticker="RELIANCE.NS")
        self.assertIsInstance(plan, FullTradePlan)
        self.assertEqual(plan.mode, "full_trade")

        # Entry Zone checks
        self.assertLessEqual(plan.entry_zone_min, plan.entry_price)
        self.assertGreaterEqual(plan.entry_zone_max, plan.entry_price)

        # Target hierarchy: Target 2 > Target 1 > Entry Price
        self.assertGreater(plan.target_1, plan.entry_price)
        self.assertGreater(plan.target_2, plan.target_1)
        self.assertGreater(plan.target_1_pct, 0.0)
        self.assertGreater(plan.target_2_pct, plan.target_1_pct)

        # Stop-loss checks
        self.assertLess(plan.stop_loss, plan.entry_price)
        self.assertLess(plan.stop_loss_pct, 0.0)

        # Risk-to-reward ratio
        self.assertGreater(plan.risk_reward_ratio, 0.5)

        # Expected holding days
        self.assertGreaterEqual(plan.expected_holding_days, 5)
        self.assertLessEqual(plan.expected_holding_days, 45)

        # ATR & Trend
        self.assertGreater(plan.atr_14, 0.0)
        self.assertIn(plan.trend, ["Strong Bullish", "Mild Bullish", "Strong Bearish", "Mild Bearish", "Consolidation"])

        # Strategy summary & exit rule
        self.assertIn("RELIANCE.NS", plan.strategy_summary)
        self.assertIn("Target Price or Stop-Loss", plan.exit_rule)

    def test_plan_deadline_trade_option_b(self):
        target_deadline = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
        capital = 200000.0
        rate = 12.0

        plan = self.planner.plan_deadline_trade(
            self.df,
            ticker="TCS.NS",
            deadline_date=target_deadline,
            capital=capital,
            annual_interest_rate=rate,
        )
        self.assertIsInstance(plan, DeadlineTradePlan)
        self.assertEqual(plan.mode, "deadline_constrained")

        # Calendar and trading days
        self.assertEqual(plan.calendar_days_remaining, 30)
        self.assertGreater(plan.trading_days_remaining, 0)
        self.assertLessEqual(plan.trading_days_remaining, 30)

        # Realizable Target
        self.assertGreater(plan.time_constrained_target, plan.entry_price)
        self.assertGreater(plan.target_pct, 0.0)

        # Tightened Stop-Loss for capital protection
        self.assertLess(plan.tightened_stop_loss, plan.entry_price)
        self.assertLess(plan.stop_loss_pct, 0.0)
        # Tightened stop loss must not exceed 4% default boundary for borrowed funds
        self.assertGreaterEqual(plan.stop_loss_pct, -4.01)

        # Borrowed Capital & Financing cost calculation
        # Formula: P * (R/100) * (D/365)
        expected_cost = round(capital * (rate / 100.0) * (30 / 365.0), 2)
        self.assertAlmostEqual(plan.accrued_borrowing_cost, expected_cost, places=1)
        self.assertEqual(plan.borrowed_capital, capital)
        self.assertEqual(plan.annual_interest_rate, rate)

        # Net PnL = Gross PnL - Financing Cost
        self.assertAlmostEqual(plan.net_projected_pnl, plan.gross_projected_pnl - plan.accrued_borrowing_cost, places=1)

        # Mandatory exit rule
        self.assertIn("MUST be", plan.mandatory_exit_rule)
        self.assertIn("borrowed funds", plan.mandatory_exit_rule)

    def test_generate_both_options(self):
        setup = self.planner.generate_both_options(
            self.df,
            ticker="INFY.NS",
            deadline_date=(date.today() + timedelta(days=15)).strftime("%Y-%m-%d"),
            capital=50000.0,
            annual_interest_rate=9.5,
        )
        self.assertIn("ticker", setup)
        self.assertEqual(setup["ticker"], "INFY.NS")
        self.assertIn("current_market_price", setup)
        self.assertIn("option_a_full_trade", setup)
        self.assertIn("option_b_deadline", setup)

        # Verify Option A
        opt_a = setup["option_a_full_trade"]
        self.assertEqual(opt_a["mode"], "full_trade")
        self.assertIn("target_1", opt_a)
        self.assertIn("target_2", opt_a)

        # Verify Option B
        opt_b = setup["option_b_deadline"]
        self.assertEqual(opt_b["mode"], "deadline_constrained")
        self.assertEqual(opt_b["borrowed_capital"], 50000.0)
        self.assertEqual(opt_b["calendar_days_remaining"], 15)

    def test_edge_case_past_deadline(self):
        # A past deadline date should be auto-adjusted to a future date (+7 days)
        past_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        plan = self.planner.plan_deadline_trade(self.df, ticker="RELIANCE.NS", deadline_date=past_date)
        self.assertGreater(plan.calendar_days_remaining, 0)
        self.assertGreater(plan.trading_days_remaining, 0)

    def test_edge_case_short_history_exception(self):
        short_df = self.df.head(5)
        with self.assertRaises(ValueError):
            self.planner.plan_full_trade(short_df, ticker="SHORT.NS")


if __name__ == "__main__":
    unittest.main()
