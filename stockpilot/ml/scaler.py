"""Leakage-free feature scaling fitted strictly on training data."""

import logging
from pathlib import Path
import pickle
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler, StandardScaler

from stockpilot.config import MLConfig

logger = logging.getLogger(__name__)

EXCLUDE_COLUMNS = {
    "Date",
    "is_outlier_return",
    "is_current_prediction_window",
    "Target_Return_5d",
    "Target_Return_10d",
    "Target_Return_20d",
    "Target_Dir_5d",
    "Target_Dir_10d",
    "Target_Dir_20d",
}


class LeakageFreeScaler:
    """Fits feature scaling strictly on the training set and transforms

    train, validation, and test datasets without data leakage.
    """

    def __init__(self, method: str = "robust", save_dir: str = "data/scalers"):
        self.method = method
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.scaler = RobustScaler() if method == "robust" else StandardScaler()
        self.feature_columns: List[str] = []
        self.train_medians: pd.Series = pd.Series(dtype=float)
        self.is_fitted: bool = False

    def get_feature_columns(self, df: pd.DataFrame) -> List[str]:
        """Identifies numeric columns suitable for scaling (excluding dates, targets, metadata)."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        return [c for c in numeric_cols if c not in EXCLUDE_COLUMNS and not c.startswith("Target_")]

    def fit(self, train_df: pd.DataFrame, ticker: str = "TICKER") -> "LeakageFreeScaler":
        """Fits scaler strictly on train_df features."""
        self.feature_columns = self.get_feature_columns(train_df)
        if not self.feature_columns:
            raise ValueError("No numeric feature columns found to scale in train_df")

        X_train = train_df[self.feature_columns].copy()
        self.train_medians = X_train.median()
        X_train_imputed = X_train.fillna(self.train_medians).fillna(0.0)

        self.scaler.fit(X_train_imputed)
        self.is_fitted = True

        logger.info("[%s] Fitted %s on %d features strictly on Train set",
                    ticker, self.scaler.__class__.__name__, len(self.feature_columns))

        save_path = self.save_dir / f"{ticker}_scaler.pkl"
        try:
            with open(save_path, "wb") as f:
                pickle.dump({
                    "scaler": self.scaler,
                    "feature_columns": self.feature_columns,
                    "train_medians": self.train_medians,
                    "method": self.method,
                }, f)
            logger.info("[%s] Saved fitted scaler to %s", ticker, save_path)
        except Exception as e:
            logger.warning("Could not persist scaler to %s: %s", save_path, e)

        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transforms features in df using the fitted scaler and train-derived medians."""
        if not self.is_fitted:
            raise RuntimeError("Scaler must be fitted on training data before transform()")

        out = df.copy()
        X = out[self.feature_columns].copy()
        X_imputed = X.fillna(self.train_medians).fillna(0.0)
        scaled_array = self.scaler.transform(X_imputed)

        scaled_col_names = [f"{col}_scaled" for col in self.feature_columns]
        scaled_df = pd.DataFrame(scaled_array, columns=scaled_col_names, index=out.index)

        return pd.concat([out, scaled_df], axis=1)

    def fit_transform_splits(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        test_df: pd.DataFrame,
        ticker: str = "TICKER",
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Convenience method to fit on train and transform train, val, and test."""
        self.fit(train_df, ticker=ticker)
        train_scaled = self.transform(train_df)
        val_scaled = self.transform(val_df)
        test_scaled = self.transform(test_df)
        return train_scaled, val_scaled, test_scaled
