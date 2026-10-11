"""Institutional labeling techniques for financial machine learning.

Implements:
1. Triple Barrier Method (Upper Profit Barrier, Lower Stop-Loss Barrier, Vertical Time Barrier).
2. Meta-Labeling (Separating trade direction from trade approval and sizing).
3. Sample Uniqueness & Concurrency Weighting to prevent backtest overfitting.
"""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TripleBarrierLabeler:
    """Labels financial time series using the Triple Barrier Method.
    
    Barriers:
    - Upper Barrier: Target return hit (+k_target * ATR or volatility). Label = +1.
    - Lower Barrier: Stop loss hit (-k_stop * ATR or volatility). Label = -1.
    - Vertical Barrier: Max holding period elapsed (max_holding_days). Label = 0.
    """

    def __init__(
        self,
        k_target: float = 2.0,
        k_stop: float = 1.0,
        max_holding_days: int = 21,
    ):
        self.k_target = k_target
        self.k_stop = k_stop
        self.max_holding_days = max_holding_days

    def generate_labels(
        self,
        df: pd.DataFrame,
        entry_indices: Optional[List[int]] = None,
        daily_vol: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """Evaluates triple barriers for each entry index."""
        if df.empty:
            return pd.DataFrame()

        df = df.sort_values("Date").reset_index(drop=True)
        closes = df["Close"].values
        highs = df["High"].values if "High" in df.columns else closes
        lows = df["Low"].values if "Low" in df.columns else closes
        n = len(closes)

        # Estimate daily volatility if not provided
        if daily_vol is None or len(daily_vol) != n:
            ret_series = df["Close"].pct_change().fillna(0)
            vol = ret_series.rolling(window=20, min_periods=5).std().fillna(0.015).values
        else:
            vol = daily_vol.values

        # If no specific entry indices, label every possible index with forward runway
        if entry_indices is None:
            entry_indices = list(range(20, n - self.max_holding_days))

        records = []
        for idx in entry_indices:
            if idx >= n - 1:
                continue

            entry_price = float(closes[idx])
            entry_date = df["Date"].iloc[idx]
            v = max(float(vol[idx]), 0.005)

            target_pct = self.k_target * v
            stop_pct = self.k_stop * v

            upper_barrier = entry_price * (1.0 + target_pct)
            lower_barrier = entry_price * (1.0 - stop_pct)

            end_idx = min(idx + self.max_holding_days, n - 1)
            touch_label = 0
            exit_idx = end_idx
            exit_price = closes[end_idx]

            # Walk forward step-by-step
            for step in range(idx + 1, end_idx + 1):
                cur_high = highs[step]
                cur_low = lows[step]

                # Check upper target
                hit_upper = cur_high >= upper_barrier
                # Check lower stop
                hit_lower = cur_low <= lower_barrier

                if hit_upper and hit_lower:
                    # In rare dual breach in one session, conservative rule: Stop hit first
                    touch_label = -1
                    exit_idx = step
                    exit_price = lower_barrier
                    break
                elif hit_upper:
                    touch_label = 1
                    exit_idx = step
                    exit_price = upper_barrier
                    break
                elif hit_lower:
                    touch_label = -1
                    exit_idx = step
                    exit_price = lower_barrier
                    break

            holding_days = exit_idx - idx
            realized_return = (exit_price - entry_price) / entry_price

            records.append({
                "entry_idx": idx,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_idx": exit_idx,
                "exit_date": df["Date"].iloc[exit_idx],
                "exit_price": exit_price,
                "holding_days": holding_days,
                "upper_barrier": upper_barrier,
                "lower_barrier": lower_barrier,
                "triple_barrier_label": touch_label,
                "realized_return": realized_return,
                # Binary meta-label: 1 if hit profit target, 0 otherwise
                "meta_label": 1 if touch_label == 1 else 0
            })

        return pd.DataFrame(records)


def compute_sample_uniqueness(labels_df: pd.DataFrame, num_bars: int) -> np.ndarray:
    """Computes sample uniqueness weights to correct for label concurrency."""
    if labels_df.empty:
        return np.array([])

    # Construct indicator matrix of active intervals
    m = np.zeros((num_bars, len(labels_df)))
    for j, row in labels_df.iterrows():
        start = int(row["entry_idx"])
        end = int(row["exit_idx"])
        m[start: end + 1, j] = 1.0

    # Number of concurrent labels per bar
    concurrency = m.sum(axis=1)
    concurrency[concurrency == 0] = 1.0

    # Average uniqueness per label
    uniqueness = np.zeros(len(labels_df))
    for j in range(len(labels_df)):
        active_bars = m[:, j] > 0
        if active_bars.any():
            uniqueness[j] = np.mean(1.0 / concurrency[active_bars])
        else:
            uniqueness[j] = 1.0

    return uniqueness
