"""Leakage-proof cross-validation for financial machine learning.

Implements:
1. Purged & Embargoed Time-Series Cross Validation (Marcos López de Prado).
2. Walk-Forward expanding and rolling window train/test splits.
"""

import logging
from typing import Generator, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PurgedTimeSeriesSplit:
    """Purged and Embargoed Walk-Forward Cross-Validation.
    
    Prevents lookahead leakage by:
    1. Purging: Dropping train samples whose holding interval overlaps with the test set.
    2. Embargoing: Dropping train samples in a buffer period immediately following the test set.
    """

    def __init__(
        self,
        n_splits: int = 5,
        embargo_pct: float = 0.02,
        min_train_pct: float = 0.4
    ):
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct
        self.min_train_pct = min_train_pct

    def split(
        self,
        X: pd.DataFrame,
        holding_intervals: Optional[pd.DataFrame] = None
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """Generates (train_indices, test_indices) pairs.
        
        Args:
            X: Feature matrix indexed by order of occurrence.
            holding_intervals: DataFrame with ['entry_idx', 'exit_idx'] mapping sample spans.
        """
        n_samples = len(X)
        indices = np.arange(n_samples)

        min_train_size = int(n_samples * self.min_train_pct)
        test_size = (n_samples - min_train_size) // self.n_splits
        embargo_size = int(n_samples * self.embargo_pct)

        for i in range(self.n_splits):
            test_start = min_train_size + i * test_size
            test_end = min_train_size + (i + 1) * test_size if i < self.n_splits - 1 else n_samples

            test_idx = indices[test_start:test_end]

            # Expanding window training
            train_candidates = indices[:test_start]

            if holding_intervals is not None and not holding_intervals.empty:
                # Purge train samples that overlap with test period
                train_mask = np.ones(len(train_candidates), dtype=bool)
                for tr_idx in train_candidates:
                    if tr_idx in holding_intervals.index:
                        exit_val = holding_intervals.loc[tr_idx, "exit_idx"]
                        if exit_val >= test_start:
                            train_mask[tr_idx] = False
                train_idx = train_candidates[train_mask]
            else:
                train_idx = train_candidates

            if len(train_idx) == 0 or len(test_idx) == 0:
                continue

            yield train_idx, test_idx
