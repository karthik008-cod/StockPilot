"""Unit tests for leakage prevention, target shifts, and split embargoes."""

import unittest
import numpy as np
import pandas as pd

from stockpilot.config import MLConfig
from stockpilot.ml.targets import TargetGenerator
from stockpilot.ml.split import TimeSeriesSplitter
from stockpilot.ml.scaler import LeakageFreeScaler
from stockpilot.ml.leakage_audit import LeakageAuditor


class TestLeakagePrevention(unittest.TestCase):

    def setUp(self):
        np.random.seed(42)
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = 100.0 + np.cumsum(np.random.normal(0, 1, n))
        self.df = pd.DataFrame({
            "Date": dates,
            "Close": close,
            "SMA_20": pd.Series(close).rolling(20, min_periods=1).mean(),
            "RSI_14": np.random.uniform(20, 80, n),
        })
        self.config = MLConfig(target_horizons=[5, 10, 20], embargo_days=20)

    def test_target_backward_shift_and_tail_nans(self):
        gen = TargetGenerator(self.config)
        with_targets = gen.generate_targets(self.df)

        for h in [5, 10, 20]:
            col = f"Target_Return_{h}d"
            self.assertIn(col, with_targets.columns)

            expected = (self.df.loc[10 + h, "Close"] - self.df.loc[10, "Close"]) / self.df.loc[10, "Close"]
            actual = with_targets.loc[10, col]
            self.assertAlmostEqual(actual, expected, places=5)

            self.assertTrue(with_targets[col].iloc[-h:].isna().all())

    def test_chronological_split_and_embargo(self):
        splitter = TimeSeriesSplitter(self.config)
        res = splitter.split(self.df)

        self.assertTrue(res.train_dates[1] < res.val_dates[0])
        self.assertTrue(res.val_dates[1] < res.test_dates[0])

        embargo_train_val = (res.val_dates[0] - res.train_dates[1]).days
        embargo_val_test = (res.test_dates[0] - res.val_dates[1]).days
        self.assertGreaterEqual(embargo_train_val, self.config.embargo_days)
        self.assertGreaterEqual(embargo_val_test, self.config.embargo_days)

    def test_scaler_train_only_fitting(self):
        splitter = TimeSeriesSplitter(self.config)
        res = splitter.split(self.df)

        scaler = LeakageFreeScaler(method="robust")
        train_scaled, val_scaled, test_scaled = scaler.fit_transform_splits(
            res.train, res.val, res.test, ticker="TEST"
        )

        for col in scaler.feature_columns:
            train_col_median = res.train[col].median()
            col_idx = scaler.feature_columns.index(col)
            scaler_center = scaler.scaler.center_[col_idx]
            self.assertAlmostEqual(train_col_median, scaler_center, places=5)

        for c in scaler.feature_columns:
            self.assertFalse(c.startswith("Target_"))

    def test_full_leakage_audit_passes(self):
        gen = TargetGenerator(self.config)
        with_targets = gen.generate_targets(self.df)

        splitter = TimeSeriesSplitter(self.config)
        res = splitter.split(with_targets)

        scaler = LeakageFreeScaler(method="robust")
        scaler.fit_transform_splits(res.train, res.val, res.test, ticker="TEST")

        auditor = LeakageAuditor()
        report = auditor.run_full_audit(with_targets, res, scaler, horizons=[5, 10, 20])
        self.assertTrue(report.passed_all)


if __name__ == "__main__":
    unittest.main()
