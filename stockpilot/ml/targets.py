"""Future return target generation for StockPilot ML pipeline."""

import logging
from typing import List, Optional
import numpy as np
import pandas as pd

from stockpilot.config import MLConfig

logger = logging.getLogger(__name__)


class TargetGenerator:
    """Generates future-return prediction targets strictly shifted backward

    so that no future information leaks into row t features.
    """

    def __init__(self, config: Optional[MLConfig] = None):
        self.config = config or MLConfig()

    def generate_targets(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generates continuous future percentage returns and binary directional targets.

        For each horizon h in [5, 10, 20]:
          Target_Return_{h}d = (Close_{t+h} - Close_t) / Close_t
          Target_Dir_{h}d = 1 if Target_Return_{h}d > 0 else 0
        """
        if df.empty:
            return df

        result = df.copy()
        close = result["Close"]

        for h in self.config.target_horizons:
            future_close = close.shift(-h)
            target_ret = (future_close - close) / (close + 1e-10)

            result[f"Target_Return_{h}d"] = target_ret
            result[f"Target_Dir_{h}d"] = np.where(target_ret.isna(), np.nan, (target_ret > 0).astype(float))

        max_horizon = max(self.config.target_horizons)
        result["is_current_prediction_window"] = False
        result.iloc[-max_horizon:, result.columns.get_loc("is_current_prediction_window")] = True

        return result
