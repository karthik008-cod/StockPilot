"""Chronological time-series splitting with embargo/purging buffers."""

from dataclasses import dataclass
import logging
from typing import Optional, Tuple
import pandas as pd

from stockpilot.config import MLConfig

logger = logging.getLogger(__name__)


@dataclass
class SplitResult:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame
    train_dates: Tuple[pd.Timestamp, pd.Timestamp]
    val_dates: Tuple[pd.Timestamp, pd.Timestamp]
    test_dates: Tuple[pd.Timestamp, pd.Timestamp]
    embargo_days: int


class TimeSeriesSplitter:
    """Performs chronological splitting into Train, Validation, and Test sets

    with an embargo buffer to prevent overlapping multi-day target leakage.
    """

    def __init__(self, config: Optional[MLConfig] = None):
        self.config = config or MLConfig()

    def split(self, df: pd.DataFrame) -> SplitResult:
        """Splits the DataFrame chronologically into train, val, and test sets.

        Applies an embargo buffer between splits.
        """
        if df.empty:
            raise ValueError("Cannot split an empty DataFrame")

        data = df.sort_values("Date").reset_index(drop=True)
        total_rows = len(data)

        train_ratio = self.config.train_ratio
        val_ratio = self.config.val_ratio
        embargo = self.config.embargo_days

        train_end_idx = int(total_rows * train_ratio)
        val_start_idx = train_end_idx + embargo
        val_end_idx = int(total_rows * (train_ratio + val_ratio))
        test_start_idx = val_end_idx + embargo

        if val_start_idx >= val_end_idx or test_start_idx >= total_rows:
            logger.warning(
                "Dataset size (%d) too small for full embargo of %d days. Adjusting split.",
                total_rows, embargo
            )
            train_df = data.iloc[:train_end_idx].copy()
            val_df = data.iloc[train_end_idx:val_end_idx].copy()
            test_df = data.iloc[val_end_idx:].copy()
            embargo_applied = 0
        else:
            train_df = data.iloc[:train_end_idx].copy()
            val_df = data.iloc[val_start_idx:val_end_idx].copy()
            test_df = data.iloc[test_start_idx:].copy()
            embargo_applied = embargo

        train_dates = (train_df["Date"].min(), train_df["Date"].max())
        val_dates = (val_df["Date"].min(), val_df["Date"].max())
        test_dates = (test_df["Date"].min(), test_df["Date"].max())

        logger.info(
            "Split completed: Train=%d rows (%s to %s), Val=%d rows (%s to %s), Test=%d rows (%s to %s), Embargo=%d days",
            len(train_df), str(train_dates[0].date()), str(train_dates[1].date()),
            len(val_df), str(val_dates[0].date()), str(val_dates[1].date()),
            len(test_df), str(test_dates[0].date()), str(test_dates[1].date()),
            embargo_applied,
        )

        return SplitResult(
            train=train_df.reset_index(drop=True),
            val=val_df.reset_index(drop=True),
            test=test_df.reset_index(drop=True),
            train_dates=train_dates,
            val_dates=val_dates,
            test_dates=test_dates,
            embargo_days=embargo_applied,
        )
