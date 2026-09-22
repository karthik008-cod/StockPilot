"""Unit tests for TechnicalFeatureExtractor."""

import unittest
import numpy as np
import pandas as pd

from stockpilot.config import FeatureConfig
from stockpilot.features.technical import TechnicalFeatureExtractor


class TestTechnicalFeatureExtractor(unittest.TestCase):

    def setUp(self):
        np.random.seed(42)
        n = 300
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.015, n)))
        high = close * (1.0 + np.random.uniform(0.002, 0.02, n))
        low = close * (1.0 - np.random.uniform(0.002, 0.02, n))
        open_p = (high + low) / 2.0
        volume = np.random.randint(50000, 500000, n)

        self.df = pd.DataFrame({
            "Date": dates,
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        })
        self.extractor = TechnicalFeatureExtractor(FeatureConfig())
        self.feat = self.extractor.extract_features(self.df)

    def test_returns_and_volatility(self):
        self.assertIn("Return_1d", self.feat.columns)
        self.assertIn("Return_5d", self.feat.columns)
        self.assertIn("Return_21d", self.feat.columns)
        self.assertIn("Log_Return_1d", self.feat.columns)
        self.assertIn("Volatility_20d", self.feat.columns)

        valid_vol = self.feat["Volatility_20d"].dropna()
        self.assertTrue((valid_vol >= 0).all())

    def test_rsi_bounds(self):
        self.assertIn("RSI_14", self.feat.columns)
        valid_rsi = self.feat["RSI_14"].dropna()
        self.assertTrue((valid_rsi >= 0.0).all())
        self.assertTrue((valid_rsi <= 100.0).all())

    def test_macd_relationship(self):
        self.assertIn("MACD_Line", self.feat.columns)
        self.assertIn("MACD_Signal", self.feat.columns)
        self.assertIn("MACD_Hist", self.feat.columns)

        diff = (self.feat["MACD_Hist"] - (self.feat["MACD_Line"] - self.feat["MACD_Signal"])).abs()
        self.assertTrue((diff < 1e-6).all())

    def test_bollinger_bands(self):
        self.assertIn("BB_Upper", self.feat.columns)
        self.assertIn("BB_Lower", self.feat.columns)
        self.assertIn("BB_Bandwidth", self.feat.columns)

        valid = self.feat.dropna(subset=["BB_Upper", "BB_Lower"])
        self.assertTrue((valid["BB_Upper"] >= valid["BB_Lower"]).all())
        self.assertTrue((valid["BB_Bandwidth"] >= 0).all())

    def test_atr_and_adx(self):
        self.assertIn("ATR_14", self.feat.columns)
        self.assertIn("NATR_14", self.feat.columns)
        self.assertIn("ADX_14", self.feat.columns)

        valid_atr = self.feat["ATR_14"].dropna()
        self.assertTrue((valid_atr > 0).all())

        valid_adx = self.feat["ADX_14"].dropna()
        self.assertTrue((valid_adx >= 0.0).all())
        self.assertTrue((valid_adx <= 100.0).all())

    def test_stochastic_bounds(self):
        self.assertIn("Stoch_K", self.feat.columns)
        self.assertIn("Stoch_D", self.feat.columns)
        valid_k = self.feat["Stoch_K"].dropna()
        self.assertTrue((valid_k >= 0.0).all())
        self.assertTrue((valid_k <= 100.0).all())

    def test_52w_extremes(self):
        self.assertIn("Dist_52w_High", self.feat.columns)
        self.assertIn("Dist_52w_Low", self.feat.columns)

        valid = self.feat.dropna(subset=["Dist_52w_High", "Dist_52w_Low"])
        self.assertTrue((valid["Dist_52w_High"] <= 1e-6).all())
        self.assertTrue((valid["Dist_52w_Low"] >= -1e-6).all())


if __name__ == "__main__":
    unittest.main()
