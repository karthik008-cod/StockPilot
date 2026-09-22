"""Market and sector relative strength, beta, and correlation features."""

import logging
from typing import Optional
import numpy as np
import pandas as pd

from stockpilot.config import FeatureConfig

logger = logging.getLogger(__name__)


class MarketRelativeFeatureExtractor:
    """Computes relative strength against benchmark (NIFTY 50), sector index,

    and rolling market beta & correlation.
    """

    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()

    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Computes relative strength, beta, and correlation features."""
        if df.empty:
            return df

        feat = df.copy()
        stock_close = feat["Close"]
        stock_ret_1d = stock_close.pct_change()

        # 1. Benchmark Relative Features (NIFTY 50)
        if "Benchmark_Close" in feat.columns:
            bench_close = feat["Benchmark_Close"]
            bench_ret_1d = bench_close.pct_change()

            feat["RS_Benchmark_Ratio"] = stock_close / (bench_close + 1e-10)

            stock_ret_20d = stock_close.pct_change(20)
            bench_ret_20d = bench_close.pct_change(20)
            feat["RS_Benchmark_Alpha_20d"] = stock_ret_20d - bench_ret_20d

            stock_ret_60d = stock_close.pct_change(60)
            bench_ret_60d = bench_close.pct_change(60)
            feat["RS_Benchmark_Alpha_60d"] = stock_ret_60d - bench_ret_60d

            beta_win = self.config.beta_window
            rolling_cov = stock_ret_1d.rolling(window=beta_win, min_periods=20).cov(bench_ret_1d)
            rolling_bench_var = bench_ret_1d.rolling(window=beta_win, min_periods=20).var()
            feat["Rolling_Beta_60d"] = rolling_cov / (rolling_bench_var + 1e-10)

            feat["Rolling_Corr_Benchmark_60d"] = stock_ret_1d.rolling(
                window=beta_win, min_periods=20
            ).corr(bench_ret_1d)
        else:
            feat["RS_Benchmark_Ratio"] = np.nan
            feat["RS_Benchmark_Alpha_20d"] = np.nan
            feat["RS_Benchmark_Alpha_60d"] = np.nan
            feat["Rolling_Beta_60d"] = np.nan
            feat["Rolling_Corr_Benchmark_60d"] = np.nan

        # 2. Sector Relative Features
        if "Sector_Close" in feat.columns:
            sec_close = feat["Sector_Close"]
            sec_ret_20d = sec_close.pct_change(20)
            feat["RS_Sector_Ratio"] = stock_close / (sec_close + 1e-10)
            feat["RS_Sector_Alpha_20d"] = stock_close.pct_change(20) - sec_ret_20d
        else:
            feat["RS_Sector_Ratio"] = np.nan
            feat["RS_Sector_Alpha_20d"] = np.nan

        return feat
