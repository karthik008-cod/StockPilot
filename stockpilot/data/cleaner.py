"""Data cleaning, validation, and outlier handling for StockPilot."""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataCleaner:
    """Performs chronological sorting, deduplication, OHLCV validation,

    missing value handling, and non-destructive outlier tagging.
    """

    def __init__(
        self,
        max_ffill_gap: int = 5,
        outlier_zscore_thresh: float = 4.0,
    ):
        self.max_ffill_gap = max_ffill_gap
        self.outlier_zscore_thresh = outlier_zscore_thresh

    def clean_ohlcv(self, df: pd.DataFrame, ticker_name: str = "TICKER") -> pd.DataFrame:
        """Cleans and validates OHLCV data.

        Returns a cleaned DataFrame with validated columns and audit metadata.
        """
        if df.empty:
            logger.warning("Empty dataframe passed to clean_ohlcv for %s", ticker_name)
            return df

        cleaned = df.copy()

        # 1. Normalize Date column
        if "Date" not in cleaned.columns:
            if isinstance(cleaned.index, pd.DatetimeIndex):
                cleaned = cleaned.reset_index()
                cleaned = cleaned.rename(columns={cleaned.columns[0]: "Date"})
            else:
                raise ValueError("DataFrame must contain a 'Date' column or DatetimeIndex")

        cleaned["Date"] = pd.to_datetime(cleaned["Date"]).dt.tz_localize(None)
        cleaned["Date"] = pd.to_datetime(cleaned["Date"].dt.date)

        # 2. Sort chronologically
        initial_len = len(cleaned)
        cleaned = cleaned.sort_values("Date").reset_index(drop=True)

        # 3. Deduplication
        cleaned = cleaned.drop_duplicates(subset=["Date"], keep="last").reset_index(drop=True)
        dedup_count = initial_len - len(cleaned)
        if dedup_count > 0:
            logger.info("[%s] Dropped %d duplicate dates", ticker_name, dedup_count)

        # 4. Handle missing values and detect column prefix
        prefix = ""
        for p in ["", "Benchmark_", "Sector_"]:
            if f"{p}Close" in cleaned.columns:
                prefix = p
                break

        open_col = f"{prefix}Open"
        high_col = f"{prefix}High"
        low_col = f"{prefix}Low"
        close_col = f"{prefix}Close"
        adj_col = f"{prefix}Adj Close"
        vol_col = f"{prefix}Volume"

        price_cols = [c for c in [open_col, high_col, low_col, close_col, adj_col] if c in cleaned.columns]
        for col in price_cols:
            missing_count = cleaned[col].isna().sum()
            if missing_count > 0:
                logger.info("[%s] Forward-filling %d missing values in %s (max gap %d)",
                            ticker_name, missing_count, col, self.max_ffill_gap)
                cleaned[col] = cleaned[col].ffill(limit=self.max_ffill_gap)

        if vol_col in cleaned.columns:
            cleaned[vol_col] = cleaned[vol_col].fillna(0.0)

        for action_col in ["Dividends", "Stock Splits"]:
            if action_col in cleaned.columns:
                cleaned[action_col] = cleaned[action_col].fillna(0.0)

        # Drop any remaining rows with NaN prices at the very beginning of the series
        cleaned = cleaned.dropna(subset=price_cols).reset_index(drop=True)

        # 5. OHLCV Integrity Validation and Repair
        # Ensure prices are strictly positive
        for col in price_cols:
            non_positive = (cleaned[col] <= 0)
            if non_positive.any():
                logger.warning("[%s] Found %d non-positive prices in %s. Fixing with ffill.",
                               ticker_name, non_positive.sum(), col)
                cleaned.loc[non_positive, col] = np.nan
                cleaned[col] = cleaned[col].ffill()

        # Check: High >= Low, High >= Open, High >= Close, Low <= Open, Low <= Close
        if high_col in cleaned.columns and low_col in cleaned.columns and open_col in cleaned.columns and close_col in cleaned.columns:
            invalid_high = (cleaned[high_col] < cleaned[open_col]) | (cleaned[high_col] < cleaned[close_col]) | (cleaned[high_col] < cleaned[low_col])
            invalid_low = (cleaned[low_col] > cleaned[open_col]) | (cleaned[low_col] > cleaned[close_col]) | (cleaned[low_col] > cleaned[high_col])

            if invalid_high.any() or invalid_low.any():
                num_violations = invalid_high.sum() + invalid_low.sum()
                logger.warning("[%s] Detected %d OHLC consistency violations. Repairing bad ticks.",
                               ticker_name, num_violations)
                cleaned[high_col] = cleaned[[open_col, high_col, close_col]].max(axis=1)
                cleaned[low_col] = cleaned[[open_col, low_col, close_col]].min(axis=1)

        # Volume must be non-negative
        if vol_col in cleaned.columns:
            neg_vol = (cleaned[vol_col] < 0)
            if neg_vol.any():
                logger.warning("[%s] Found %d negative volume entries. Setting to 0.", ticker_name, neg_vol.sum())
                cleaned.loc[neg_vol, vol_col] = 0.0

        # 6. Corporate Action & Adjusted Price Ratios
        if close_col in cleaned.columns and adj_col in cleaned.columns:
            cleaned[f"{prefix}Adj_Factor"] = cleaned[adj_col] / cleaned[close_col]
        else:
            cleaned[f"{prefix}Adj_Factor"] = 1.0

        # 7. Non-destructive Outlier Tagging
        cleaned = self.tag_outliers(cleaned, ticker_name=ticker_name, close_col=close_col)

        return cleaned

    def tag_outliers(self, df: pd.DataFrame, ticker_name: str = "TICKER", close_col: str = "Close") -> pd.DataFrame:
        """Tags extreme return moves without deleting data rows.

        Keeps genuine market events intact (e.g. COVID crash, election days)
        while providing outlier tags and winsorized features.
        """
        df = df.copy()
        if close_col not in df.columns or len(df) < 30:
            df["is_outlier_return"] = False
            return df

        # Daily percentage return
        ret = df[close_col].pct_change()

        # Rolling 60-day median and median absolute deviation
        rolling_median = ret.rolling(window=60, min_periods=20).median()
        rolling_mad = (ret - rolling_median).abs().rolling(window=60, min_periods=20).median()
        rolling_std = rolling_mad * 1.4826 + 1e-8

        zscore = (ret - rolling_median).abs() / rolling_std
        is_outlier = zscore > self.outlier_zscore_thresh

        df["is_outlier_return"] = is_outlier.fillna(False)

        outlier_count = df["is_outlier_return"].sum()
        if outlier_count > 0:
            outlier_dates = df.loc[df["is_outlier_return"], "Date"].dt.strftime("%Y-%m-%d").tolist()
            logger.info("[%s] Tagged %d market extreme / outlier days: %s",
                        ticker_name, outlier_count, outlier_dates[:5])

        return df
