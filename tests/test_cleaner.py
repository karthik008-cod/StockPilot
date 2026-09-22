"""Unit tests for DataCleaner."""

import unittest
import numpy as np
import pandas as pd

from stockpilot.data.cleaner import DataCleaner


class TestDataCleaner(unittest.TestCase):

    def setUp(self):
        self.cleaner = DataCleaner(max_ffill_gap=3, outlier_zscore_thresh=3.0)

    def test_chronological_sorting_and_deduplication(self):
        dates = pd.date_range("2023-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Date": [dates[3], dates[1], dates[0], dates[2], dates[1]],
            "Open": [103.0, 101.0, 100.0, 102.0, 101.5],
            "High": [105.0, 103.0, 102.0, 104.0, 103.5],
            "Low": [101.0, 99.0, 98.0, 100.0, 99.5],
            "Close": [104.0, 102.0, 101.0, 103.0, 102.5],
            "Adj Close": [104.0, 102.0, 101.0, 103.0, 102.5],
            "Volume": [1000, 1200, 1100, 1300, 1250],
        })

        cleaned = self.cleaner.clean_ohlcv(df, "TEST")
        self.assertEqual(len(cleaned), 4)
        self.assertTrue(cleaned["Date"].is_monotonic_increasing)

    def test_ohlcv_integrity_repair(self):
        df = pd.DataFrame({
            "Date": pd.date_range("2023-01-01", periods=3, freq="D"),
            "Open": [100.0, 110.0, 100.0],
            "High": [95.0, 105.0, 120.0],
            "Low": [105.0, 90.0, 105.0],
            "Close": [102.0, 95.0, 102.0],
            "Adj Close": [102.0, 95.0, 102.0],
            "Volume": [1000, -500, 1500],
        })

        cleaned = self.cleaner.clean_ohlcv(df, "TEST")
        self.assertTrue((cleaned["High"] >= cleaned["Low"]).all())
        self.assertTrue((cleaned["High"] >= cleaned["Open"]).all())
        self.assertTrue((cleaned["High"] >= cleaned["Close"]).all())
        self.assertTrue((cleaned["Low"] <= cleaned["Open"]).all())
        self.assertTrue((cleaned["Low"] <= cleaned["Close"]).all())
        self.assertTrue((cleaned["Volume"] >= 0).all())

    def test_outlier_tagging_preserves_rows(self):
        np.random.seed(42)
        n = 70
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        prices = [100.0]
        for _ in range(n - 1):
            prices.append(prices[-1] * (1.0 + np.random.normal(0, 0.01)))
        prices[50] = prices[49] * 1.25

        df = pd.DataFrame({
            "Date": dates,
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Adj Close": prices,
            "Volume": [10000] * n,
        })

        cleaned = self.cleaner.clean_ohlcv(df, "TEST")
        self.assertEqual(len(cleaned), n)
        self.assertIn("is_outlier_return", cleaned.columns)
        self.assertTrue(cleaned.loc[50, "is_outlier_return"])


if __name__ == "__main__":
    unittest.main()
