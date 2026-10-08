"""Unit tests for StockPilot Multi-Timeframe Strategy Scanner Engine.

Verifies:
1. Wilder-style RSI(14) calculation accuracy and bounds.
2. Weekly and Monthly price candle resampling (OHLCV aggregation).
3. In-progress current candle handling vs completed candles.
4. Strict look-ahead bias prevention (point-in-time evaluation).
5. All 4 strategy condition evaluations:
   - Strategy 1: HTF_BULLISH_DEEP_DAILY_PULLBACK (Monthly > 60, Weekly > 60, 39 < Daily < 45)
   - Strategy 2: HTF_BULLISH_DAILY_MOMENTUM_ZONE (Monthly > 60, Weekly > 60, 58 < Daily < 63)
   - Strategy 3: WEEKLY_RSI_CROSS_ABOVE_60 (Crossover event: Weekly[t] > 60 and Weekly[t-1] <= 60)
   - Strategy 4: MONTHLY_RSI_40_43_ZONE (40 <= Monthly <= 43)
6. Declarative strategy definition and audit evidence emission.
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from stockpilot.strategy.models import (
    Timeframe,
    Operator,
    Condition,
    StrategyDefinition,
    ConditionEvidence,
    ScanCandidate,
)
from stockpilot.strategy.resampler import (
    compute_wilder_rsi,
    resample_to_timeframe,
    extract_multi_timeframe_indicators,
)
from stockpilot.strategy.registry import (
    STRATEGY_REGISTRY,
    get_strategy,
    list_strategies,
    STRATEGY_1,
    STRATEGY_2,
    STRATEGY_3,
    STRATEGY_4,
)
from stockpilot.strategy.scanner import StrategyScannerEngine


def generate_synthetic_ohlcv(days: int = 300, seed: int = 42) -> pd.DataFrame:
    """Generates realistic synthetic daily OHLCV dataframe."""
    np.random.seed(seed)
    # Generate business dates ending recently
    base_date = pd.to_datetime("2023-01-01")
    dates = pd.bdate_range(start=base_date, periods=days)
    
    # Geometric Brownian motion prices
    returns = np.random.normal(0.0005, 0.015, size=days)
    price = 100.0 * np.cumprod(1.0 + returns)
    
    highs = price * (1.0 + np.abs(np.random.normal(0, 0.008, size=days)))
    lows = price * (1.0 - np.abs(np.random.normal(0, 0.008, size=days)))
    opens = np.clip((highs + lows) / 2.0 + np.random.normal(0, 0.1, size=days), lows, highs)
    volume = np.random.randint(100000, 5000000, size=days)
    
    return pd.DataFrame({
        "Date": dates,
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": price,
        "Adj_Close": price,
        "Volume": volume,
    })


class TestWilderRSI(unittest.TestCase):
    """Tests for Wilder-style RSI(14) computation."""

    def test_wilder_rsi_series_length_and_bounds(self):
        df = generate_synthetic_ohlcv(days=100)
        rsi = compute_wilder_rsi(df["Close"], period=14)
        
        self.assertEqual(len(rsi), len(df))
        # First 14 rows should be NaN due to warmup period
        self.assertTrue(rsi.iloc[:14].isna().all())
        
        valid_rsi = rsi.dropna()
        self.assertGreater(len(valid_rsi), 50)
        self.assertTrue((valid_rsi >= 0.0).all())
        self.assertTrue((valid_rsi <= 100.0).all())

    def test_wilder_rsi_monotonic_increase_reaches_high(self):
        # Monotonically increasing prices should have RSI close to 100
        dates = pd.bdate_range("2023-01-01", periods=50)
        closes = pd.Series([100.0 + i * 2.0 for i in range(50)], index=dates)
        rsi = compute_wilder_rsi(closes, period=14)
        latest_rsi = rsi.iloc[-1]
        self.assertGreater(latest_rsi, 95.0)

    def test_wilder_rsi_monotonic_decrease_reaches_low(self):
        # Monotonically decreasing prices should have RSI close to 0
        dates = pd.bdate_range("2023-01-01", periods=50)
        closes = pd.Series([200.0 - i * 2.0 for i in range(50)], index=dates)
        rsi = compute_wilder_rsi(closes, period=14)
        latest_rsi = rsi.iloc[-1]
        self.assertLess(latest_rsi, 5.0)


class TestTimeframeResampler(unittest.TestCase):
    """Tests for Weekly & Monthly candle aggregation and current candle handling."""

    def setUp(self):
        self.df = generate_synthetic_ohlcv(days=500)

    def test_weekly_candle_ohlcv_integrity(self):
        weekly = resample_to_timeframe(self.df, Timeframe.WEEKLY, compute_rsi=True)
        self.assertFalse(weekly.empty)
        self.assertIn("RSI_14", weekly.columns)
        
        # Check OHLC relationships
        self.assertTrue((weekly["High"] >= weekly["Low"]).all())
        self.assertTrue((weekly["High"] >= weekly["Open"]).all())
        self.assertTrue((weekly["High"] >= weekly["Close"]).all())
        self.assertTrue((weekly["Low"] <= weekly["Open"]).all())
        self.assertTrue((weekly["Low"] <= weekly["Close"]).all())
        self.assertTrue((weekly["Volume"] > 0).all())

    def test_monthly_candle_ohlcv_integrity(self):
        monthly = resample_to_timeframe(self.df, Timeframe.MONTHLY, compute_rsi=True)
        self.assertFalse(monthly.empty)
        self.assertIn("RSI_14", monthly.columns)
        
        self.assertTrue((monthly["High"] >= monthly["Low"]).all())
        self.assertTrue((monthly["High"] >= monthly["Close"]).all())
        self.assertTrue((monthly["Low"] <= monthly["Close"]).all())

    def test_current_forming_candle_close_matches_latest_daily_close(self):
        """The latest weekly/monthly candle must reflect the latest daily closing price."""
        weekly = resample_to_timeframe(self.df, Timeframe.WEEKLY)
        monthly = resample_to_timeframe(self.df, Timeframe.MONTHLY)
        
        latest_daily_close = self.df.iloc[-1]["Close"]
        self.assertAlmostEqual(weekly.iloc[-1]["Close"], latest_daily_close, places=4)
        self.assertAlmostEqual(monthly.iloc[-1]["Close"], latest_daily_close, places=4)

    def test_lookahead_bias_safeguard(self):
        """Extracting indicators with as_of_date must NEVER see data after that date."""
        full_df = self.df.copy()
        cutoff_date = "2023-08-15"
        
        indicators_cutoff = extract_multi_timeframe_indicators(full_df, as_of_date=cutoff_date)
        
        # Modify all data after cutoff_date drastically
        tampered_df = full_df.copy()
        mask_future = tampered_df["Date"] > pd.to_datetime(cutoff_date)
        tampered_df.loc[mask_future, "Close"] = tampered_df.loc[mask_future, "Close"] * 5.0
        
        indicators_tampered = extract_multi_timeframe_indicators(tampered_df, as_of_date=cutoff_date)
        
        # RSI values at cutoff must be IDENTICAL despite drastic future changes
        self.assertAlmostEqual(
            indicators_cutoff["daily_rsi_14"],
            indicators_tampered["daily_rsi_14"],
            places=6,
            msg="Look-ahead bias detected in daily RSI!",
        )
        self.assertAlmostEqual(
            indicators_cutoff["weekly_rsi_14"],
            indicators_tampered["weekly_rsi_14"],
            places=6,
            msg="Look-ahead bias detected in weekly RSI!",
        )
        self.assertAlmostEqual(
            indicators_cutoff["monthly_rsi_14"],
            indicators_tampered["monthly_rsi_14"],
            places=6,
            msg="Look-ahead bias detected in monthly RSI!",
        )


class TestStrategyConditions(unittest.TestCase):
    """Unit tests for the 4 specific strategy logic rules."""

    def setUp(self):
        self.engine = StrategyScannerEngine()

    def test_registry_contains_all_four_strategies(self):
        strats = list_strategies()
        self.assertGreaterEqual(len(strats), 4)
        ids = [s["strategy_id"] for s in strats]
        self.assertIn("HTF_BULLISH_DEEP_DAILY_PULLBACK", ids)
        self.assertIn("HTF_BULLISH_DAILY_MOMENTUM_ZONE", ids)
        self.assertIn("WEEKLY_RSI_CROSS_ABOVE_60", ids)
        self.assertIn("MONTHLY_RSI_40_43_ZONE", ids)

    def test_strategy_1_logic(self):
        """Strategy 1: Monthly > 60 AND Weekly > 60 AND 39 < Daily < 45."""
        strat = get_strategy("HTF_BULLISH_DEEP_DAILY_PULLBACK")
        self.assertIsNotNone(strat)
        self.assertEqual(strat.universe, "NIFTY 500")

        cond_m = strat.conditions[0] # Monthly > 60
        cond_w = strat.conditions[1] # Weekly > 60
        cond_d_gt = strat.conditions[2] # Daily > 39
        cond_d_lt = strat.conditions[3] # Daily < 45

        # Passing case
        self.assertTrue(cond_m.evaluate(62.5)[0])
        self.assertTrue(cond_w.evaluate(61.0)[0])
        self.assertTrue(cond_d_gt.evaluate(42.0)[0])
        self.assertTrue(cond_d_lt.evaluate(42.0)[0])

        # Failing case: Daily too low (<= 39)
        self.assertFalse(cond_d_gt.evaluate(38.5)[0])
        self.assertFalse(cond_d_gt.evaluate(39.0)[0])

        # Failing case: Daily too high (>= 45)
        self.assertFalse(cond_d_lt.evaluate(45.5)[0])
        self.assertFalse(cond_d_lt.evaluate(45.0)[0])

        # Failing case: Weekly <= 60
        self.assertFalse(cond_w.evaluate(59.9)[0])

    def test_strategy_2_logic(self):
        """Strategy 2: Monthly > 60 AND Weekly > 60 AND 58 < Daily < 63."""
        strat = get_strategy("HTF_BULLISH_DAILY_MOMENTUM_ZONE")
        self.assertIsNotNone(strat)
        self.assertEqual(strat.universe, "NIFTY 500")

        cond_d_gt = strat.conditions[2] # Daily > 58
        cond_d_lt = strat.conditions[3] # Daily < 63

        # Passing case: Daily 60.5
        self.assertTrue(cond_d_gt.evaluate(60.5)[0])
        self.assertTrue(cond_d_lt.evaluate(60.5)[0])

        # Failing case: Daily 57.0 (below 58)
        self.assertFalse(cond_d_gt.evaluate(57.0)[0])

        # Failing case: Daily 64.0 (above 63)
        self.assertFalse(cond_d_lt.evaluate(64.0)[0])

    def test_strategy_3_crossover_event_logic(self):
        """Strategy 3: Weekly RSI > 60 AND Previous Week Weekly RSI <= 60."""
        strat = get_strategy("WEEKLY_RSI_CROSS_ABOVE_60")
        self.assertIsNotNone(strat)
        self.assertEqual(strat.universe, "NIFTY 50")
        self.assertEqual(len(strat.conditions), 2)

        cond_curr = strat.conditions[0] # Current Weekly RSI > 60 (shift 0)
        cond_prev = strat.conditions[1] # Previous Weekly RSI <= 60 (shift 1)

        self.assertEqual(cond_curr.operator, Operator.GT)
        self.assertEqual(cond_curr.value, 60.0)
        self.assertEqual(cond_prev.operator, Operator.LTE)
        self.assertEqual(cond_prev.value, 60.0)

        # Passing case: Crossed from 58.2 to 61.5
        pass_curr, _ = cond_curr.evaluate(61.5)
        pass_prev, _ = cond_prev.evaluate(58.2)
        self.assertTrue(pass_curr and pass_prev)

        # Boundary case: Crossed from exactly 60.0 to 60.5
        pass_curr, _ = cond_curr.evaluate(60.5)
        pass_prev, _ = cond_prev.evaluate(60.0)
        self.assertTrue(pass_curr and pass_prev)

        # Failing case: Was already above 60 last week (continuation, NOT crossover)
        pass_curr, _ = cond_curr.evaluate(65.0)
        pass_prev, _ = cond_prev.evaluate(62.0)
        self.assertFalse(pass_curr and pass_prev)

        # Failing case: Did not reach above 60
        pass_curr, _ = cond_curr.evaluate(59.5)
        pass_prev, _ = cond_prev.evaluate(55.0)
        self.assertFalse(pass_curr and pass_prev)

    def test_strategy_4_monthly_zone_logic(self):
        """Strategy 4: 40 <= Monthly RSI <= 43."""
        strat = get_strategy("MONTHLY_RSI_40_43_ZONE")
        self.assertIsNotNone(strat)
        self.assertEqual(strat.universe, "NIFTY 200")
        self.assertEqual(len(strat.conditions), 2)

        cond_gte = strat.conditions[0] # Monthly >= 40
        cond_lte = strat.conditions[1] # Monthly <= 43

        self.assertEqual(cond_gte.operator, Operator.GTE)
        self.assertEqual(cond_gte.value, 40.0)
        self.assertEqual(cond_lte.operator, Operator.LTE)
        self.assertEqual(cond_lte.value, 43.0)

        # Passing cases
        self.assertTrue(cond_gte.evaluate(40.0)[0] and cond_lte.evaluate(40.0)[0]) # Boundary
        self.assertTrue(cond_gte.evaluate(41.5)[0] and cond_lte.evaluate(41.5)[0]) # Mid
        self.assertTrue(cond_gte.evaluate(43.0)[0] and cond_lte.evaluate(43.0)[0]) # Boundary

        # Failing cases
        self.assertFalse(cond_gte.evaluate(39.99)[0] and cond_lte.evaluate(39.99)[0]) # Below
        self.assertFalse(cond_gte.evaluate(43.01)[0] and cond_lte.evaluate(43.01)[0]) # Above
        self.assertFalse(cond_gte.evaluate(65.0)[0] and cond_lte.evaluate(65.0)[0])  # Bullish stock


class TestScannerOutputStructure(unittest.TestCase):
    """Verifies that scanner output contains structured evidence rather than just tickers."""

    def test_scan_candidate_evidence_structure(self):
        engine = StrategyScannerEngine()
        strat = get_strategy("HTF_BULLISH_DEEP_DAILY_PULLBACK")
        df = generate_synthetic_ohlcv(days=400)
        
        candidate = engine.evaluate_dataframe(
            df,
            strategy=strat,
            symbol="TEST.NS",
            name="Test Stock",
            sector="Finance",
        )

        d = candidate.to_dict()
        self.assertIn("symbol", d)
        self.assertIn("strategy_id", d)
        self.assertIn("passed", d)
        self.assertIn("indicators", d)
        self.assertIn("conditions", d)
        
        # Check indicator payload
        indicators = d["indicators"]
        self.assertIn("daily_rsi_14", indicators)
        self.assertIn("weekly_rsi_14", indicators)
        self.assertIn("monthly_rsi_14", indicators)

class TestCustomStrategyCRUD(unittest.TestCase):
    """Tests custom strategy creation, customization, resetting, and deletion."""

    def test_custom_strategy_lifecycle(self):
        from stockpilot.strategy.registry import (
            create_custom_strategy,
            update_strategy,
            reset_strategy,
            delete_strategy,
        )

        # 1. Create Custom Strategy
        strat = create_custom_strategy({
            "name": "Breakout Momentum Test",
            "universe": "NIFTY 50",
            "description": "Custom test strategy",
            "conditions": [
                {"timeframe": "DAILY", "indicator": "RSI", "period": 14, "operator": ">", "value": 55.0},
                {"timeframe": "DAILY", "indicator": "CLOSE", "period": 1, "operator": ">", "value": 100.0},
            ],
        })
        self.assertFalse(strat.is_builtin)
        self.assertFalse(strat.is_customized)
        self.assertIn(strat.strategy_id, [s["strategy_id"] for s in list_strategies()])

        # 2. Customize Built-in Strategy
        updated = update_strategy("HTF_BULLISH_DEEP_DAILY_PULLBACK", {
            "name": "HTF Pullback Customized",
            "universe": "NIFTY 100",
            "description": "Adjusted threshold",
            "conditions": [
                {"timeframe": "MONTHLY", "indicator": "RSI", "period": 14, "operator": ">", "value": 55.0},
            ],
        })
        self.assertTrue(updated.is_builtin)
        self.assertTrue(updated.is_customized)
        self.assertEqual(updated.universe, "NIFTY 100")

        # 3. Reset Built-in Strategy
        restored = reset_strategy("HTF_BULLISH_DEEP_DAILY_PULLBACK")
        self.assertTrue(restored.is_builtin)
        self.assertFalse(restored.is_customized)
        self.assertEqual(restored.universe, "NIFTY 500")

        # 4. Cannot delete built-in strategy
        with self.assertRaises(ValueError):
            delete_strategy("HTF_BULLISH_DEEP_DAILY_PULLBACK")

        # 5. Delete Custom Strategy
        res = delete_strategy(strat.strategy_id)
        self.assertTrue(res)
        self.assertNotIn(strat.strategy_id, [s["strategy_id"] for s in list_strategies()])


if __name__ == "__main__":
    unittest.main()
