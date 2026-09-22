"""Fundamental features and financial ratio calculations."""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FundamentalFeatureExtractor:
    """Extracts and normalizes fundamental ratios, growth rates, and margins."""

    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Computes derived fundamental ratios and quarterly growth metrics."""
        if df.empty:
            return df

        feat = df.copy()

        if "Total_Debt" in feat.columns and "Stockholders_Equity" in feat.columns:
            feat["Debt_To_Equity_Calc"] = feat["Total_Debt"] / (feat["Stockholders_Equity"].abs() + 1e-10)
        else:
            feat["Debt_To_Equity_Calc"] = np.nan

        if "Quarterly_Net_Income" in feat.columns and "Quarterly_Revenue" in feat.columns:
            feat["Net_Profit_Margin"] = feat["Quarterly_Net_Income"] / (feat["Quarterly_Revenue"].abs() + 1e-10)
        else:
            feat["Net_Profit_Margin"] = np.nan

        if "Free_Cash_Flow" in feat.columns and "Quarterly_Net_Income" in feat.columns:
            feat["FCF_To_Net_Income"] = feat["Free_Cash_Flow"] / (feat["Quarterly_Net_Income"].abs() + 1e-10)
        else:
            feat["FCF_To_Net_Income"] = np.nan

        fund_cols = [
            "Quarterly_Revenue", "Quarterly_Net_Income", "Quarterly_EPS",
            "Total_Debt", "Stockholders_Equity", "Free_Cash_Flow",
            "Debt_To_Equity_Calc", "Net_Profit_Margin", "FCF_To_Net_Income",
            "PE_Ratio", "PB_Ratio", "ROE", "Market_Cap", "Debt_To_Equity", "Dividend_Yield",
        ]
        for col in fund_cols:
            if col in feat.columns:
                feat[col] = feat[col].ffill()

        return feat
