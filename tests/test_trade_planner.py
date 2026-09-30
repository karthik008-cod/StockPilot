"""Unit tests for TradePlanner (Option A: Full Trade vs Option B: Deadline-Constrained).

Tests position sizing, trade term configurations, and trading type classification.
"""

from datetime import date, timedelta
import unittest
import numpy as np
import pandas as pd

from stockpilot.trade.planner import (
    DeadlineTradePlan,
    FullTradePlan,
    PositionSizing,
    TradePlanner,
    TERM_CONFIGS,
    VALID_TRADING_TYPES,
)


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

    def test_plan_full_trade_option_a_default_medium(self):
        plan = self.planner.plan_full_trade(
            self.df, ticker="RELIANCE.NS",
            available_capital=100000, max_acceptable_loss=2000,
        )
        self.assertIsInstance(plan, FullTradePlan)
        self.assertEqual(plan.mode, "full_trade")
        self.assertEqual(plan.trade_term, "medium")
        self.assertEqual(plan.trade_term_label, "Medium-Term")
        self.assertEqual(plan.trading_type, "swing")

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

        # Expected holding days within medium term bounds
        self.assertGreaterEqual(plan.expected_holding_days, 5)
        self.assertLessEqual(plan.expected_holding_days, 45)

        # ATR & Trend
        self.assertGreater(plan.atr_14, 0.0)
        self.assertIn(plan.trend, ["Strong Bullish", "Mild Bullish", "Strong Bearish", "Mild Bearish", "Consolidation"])

        # Position Sizing
        self.assertIn("position_size_shares", plan.position_sizing)
        self.assertIn("capital_required", plan.position_sizing)
        self.assertIn("max_loss_actual", plan.position_sizing)
        self.assertGreaterEqual(plan.position_sizing["position_size_shares"], 0)

        # Strategy summary & exit rule
        self.assertIn("RELIANCE.NS", plan.strategy_summary)
        self.assertIn("Target Price or Stop-Loss", plan.exit_rule)

    def test_plan_full_trade_short_term(self):
        plan = self.planner.plan_full_trade(
            self.df, ticker="TCS.NS", trade_term="short",
            available_capital=50000, max_acceptable_loss=1000,
        )
        self.assertEqual(plan.trade_term, "short")
        self.assertEqual(plan.trade_term_label, "Short-Term")
        self.assertGreaterEqual(plan.expected_holding_days, 2)
        self.assertLessEqual(plan.expected_holding_days, 15)
        # Short-term stop loss max should be 3%
        self.assertGreaterEqual(plan.stop_loss_pct, -3.01)

    def test_plan_full_trade_long_term(self):
        plan = self.planner.plan_full_trade(
            self.df, ticker="HDFC.NS", trade_term="long", trading_type="investing",
            available_capital=500000, max_acceptable_loss=10000,
        )
        self.assertEqual(plan.trade_term, "long")
        self.assertEqual(plan.trade_term_label, "Long-Term")
        self.assertEqual(plan.trading_type, "investing")
        self.assertGreaterEqual(plan.expected_holding_days, 20)
        self.assertLessEqual(plan.expected_holding_days, 180)

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
            available_capital=200000,
            max_acceptable_loss=5000,
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
        self.assertGreaterEqual(plan.stop_loss_pct, -4.01)

        # Borrowed Capital & Financing cost calculation
        expected_cost = round(capital * (rate / 100.0) * (30 / 365.0), 2)
        self.assertAlmostEqual(plan.accrued_borrowing_cost, expected_cost, places=1)
        self.assertEqual(plan.borrowed_capital, capital)
        self.assertEqual(plan.annual_interest_rate, rate)

        # Net PnL = Gross PnL - Financing Cost
        self.assertAlmostEqual(plan.net_projected_pnl, plan.gross_projected_pnl - plan.accrued_borrowing_cost, places=1)

        # Mandatory exit rule
        self.assertIn("MUST be", plan.mandatory_exit_rule)
        self.assertIn("borrowed funds", plan.mandatory_exit_rule)

        # Position sizing should be present
        self.assertIn("position_size_shares", plan.position_sizing)

    def test_generate_both_options(self):
        setup = self.planner.generate_both_options(
            self.df,
            ticker="INFY.NS",
            trade_term="short",
            trading_type="positional",
            available_capital=75000,
            max_acceptable_loss=1500,
            deadline_date=(date.today() + timedelta(days=15)).strftime("%Y-%m-%d"),
            borrowed_capital=50000.0,
            annual_interest_rate=9.5,
        )
        self.assertIn("ticker", setup)
        self.assertEqual(setup["ticker"], "INFY.NS")
        self.assertEqual(setup["trading_type"], "positional")
        self.assertEqual(setup["trade_term"], "short")
        self.assertIn("current_market_price", setup)
        self.assertIn("option_a_full_trade", setup)
        self.assertIn("option_b_deadline", setup)

        # Verify Option A
        opt_a = setup["option_a_full_trade"]
        self.assertEqual(opt_a["mode"], "full_trade")
        self.assertEqual(opt_a["trade_term"], "short")
        self.assertEqual(opt_a["trading_type"], "positional")
        self.assertIn("target_1", opt_a)
        self.assertIn("target_2", opt_a)
        self.assertIn("position_sizing", opt_a)

        # Verify Option B
        opt_b = setup["option_b_deadline"]
        self.assertEqual(opt_b["mode"], "deadline_constrained")
        self.assertEqual(opt_b["borrowed_capital"], 50000.0)
        self.assertEqual(opt_b["calendar_days_remaining"], 15)
        self.assertIn("position_sizing", opt_b)

    def test_edge_case_past_deadline(self):
        past_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        plan = self.planner.plan_deadline_trade(self.df, ticker="RELIANCE.NS", deadline_date=past_date)
        self.assertGreater(plan.calendar_days_remaining, 0)
        self.assertGreater(plan.trading_days_remaining, 0)

    def test_edge_case_short_history_exception(self):
        short_df = self.df.head(5)
        with self.assertRaises(ValueError):
            self.planner.plan_full_trade(short_df, ticker="SHORT.NS")


class TestPositionSizing(unittest.TestCase):

    def test_basic_position_sizing(self):
        """₹100,000 capital, ₹1,000 max loss, entry ₹250, SL ₹240 → 100 shares"""
        ps = TradePlanner.compute_position_sizing(
            entry_price=250.0,
            stop_loss=240.0,
            target_1=280.0,
            target_2=300.0,
            available_capital=100000.0,
            max_acceptable_loss=1000.0,
        )
        self.assertEqual(ps.risk_per_share, 10.0)
        self.assertEqual(ps.position_size_shares, 100)
        self.assertEqual(ps.capital_required, 25000.0)
        self.assertEqual(ps.max_loss_actual, 1000.0)
        self.assertEqual(ps.potential_profit_t1, 3000.0)
        self.assertEqual(ps.potential_profit_t2, 5000.0)
        self.assertTrue(ps.is_affordable)

    def test_capital_limited_sizing(self):
        """When capital is the limiting factor, not risk tolerance"""
        ps = TradePlanner.compute_position_sizing(
            entry_price=5000.0,
            stop_loss=4900.0,
            target_1=5300.0,
            target_2=5500.0,
            available_capital=10000.0,
            max_acceptable_loss=5000.0,
        )
        # Can afford only 2 shares (10000/5000 = 2)
        # Risk allows 50 shares (5000/100 = 50), but capital limits to 2
        self.assertEqual(ps.position_size_shares, 2)
        self.assertEqual(ps.capital_required, 10000.0)
        self.assertTrue(ps.is_affordable)

    def test_zero_capital(self):
        ps = TradePlanner.compute_position_sizing(
            entry_price=250.0,
            stop_loss=240.0,
            target_1=280.0,
            target_2=300.0,
            available_capital=0.0,
            max_acceptable_loss=1000.0,
        )
        self.assertEqual(ps.position_size_shares, 100)
        # Still computed from risk, but capital_required > available
        self.assertFalse(ps.is_affordable)

    def test_invalid_trading_type_fallback(self):
        planner = TradePlanner()
        plan = planner.plan_full_trade(
            _make_test_df(), ticker="TEST.NS", trading_type="crypto",
            available_capital=50000, max_acceptable_loss=1000,
        )
        # Should fall back to "swing"
        self.assertEqual(plan.trading_type, "swing")

    def test_invalid_trade_term_fallback(self):
        planner = TradePlanner()
        plan = planner.plan_full_trade(
            _make_test_df(), ticker="TEST.NS", trade_term="ultra_short",
            available_capital=50000, max_acceptable_loss=1000,
        )
        # Should fall back to "medium"
        self.assertEqual(plan.trade_term, "medium")


class TestTermConfigs(unittest.TestCase):

    def test_all_terms_present(self):
        self.assertIn("short", TERM_CONFIGS)
        self.assertIn("medium", TERM_CONFIGS)
        self.assertIn("long", TERM_CONFIGS)

    def test_target_multipliers_increase_with_term(self):
        self.assertLess(
            TERM_CONFIGS["short"]["atr_target_mult"],
            TERM_CONFIGS["medium"]["atr_target_mult"],
        )
        self.assertLess(
            TERM_CONFIGS["medium"]["atr_target_mult"],
            TERM_CONFIGS["long"]["atr_target_mult"],
        )

    def test_sl_max_pct_increases_with_term(self):
        self.assertLess(
            TERM_CONFIGS["short"]["sl_max_pct"],
            TERM_CONFIGS["medium"]["sl_max_pct"],
        )
        self.assertLess(
            TERM_CONFIGS["medium"]["sl_max_pct"],
            TERM_CONFIGS["long"]["sl_max_pct"],
        )


class TestValidTradingTypes(unittest.TestCase):

    def test_trading_types_list(self):
        expected = ["swing", "positional", "investing", "intraday", "futures", "options"]
        for t in expected:
            self.assertIn(t, VALID_TRADING_TYPES)


def _make_test_df(n=100):
    """Helper: generate a synthetic OHLCV DataFrame for testing."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    base = 250.0
    close = base + np.cumsum(np.random.normal(0.5, 3.0, n))
    high = close + np.random.uniform(1.0, 5.0, n)
    low = close - np.random.uniform(1.0, 5.0, n)
    return pd.DataFrame({
        "Date": dates,
        "Open": (high + low) / 2.0,
        "High": high,
        "Low": low,
        "Close": close,
        "Adj Close": close,
        "Volume": np.random.randint(50000, 500000, n),
    })


if __name__ == "__main__":
    unittest.main()
