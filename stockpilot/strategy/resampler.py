"""Multi-timeframe price resampling and Wilder-smoothed indicator calculations.

Strictly avoids look-ahead bias and correctly handles in-progress (forming)
candles for live as-of-date evaluation.
"""

import logging
from typing import Any, Dict, Optional, Union
import numpy as np
import pandas as pd

from stockpilot.strategy.models import Timeframe

logger = logging.getLogger(__name__)


def compute_wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Computes standard Wilder's Relative Strength Index (RSI).
    
    Uses exponential smoothing with alpha = 1 / period (Wilder's smoothing),
    which is mathematically equivalent to Wilder's recursive moving average.
    First `period` values are set to NaN as the initialization warmup window.
    """
    if series.empty or len(series) < 2:
        return pd.Series(dtype=float, index=series.index)

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    alpha = 1.0 / float(period)
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()

    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    # Mask initial warmup rows as NaN
    if len(rsi) >= period:
        rsi.iloc[:period] = np.nan
    else:
        rsi.iloc[:] = np.nan
    return rsi


def resample_to_timeframe(
    df: pd.DataFrame,
    timeframe: Union[Timeframe, str],
    as_of_date: Optional[Union[str, pd.Timestamp]] = None,
    compute_rsi: bool = False,
    period: int = 14,
) -> pd.DataFrame:
    """Resamples daily OHLCV dataframe into Weekly or Monthly candles.
    
    Point-in-Time Safeguards:
      - If as_of_date is provided, any daily observation strictly after as_of_date
        is filtered out BEFORE candle aggregation.
      - The most recent candle (whether weekly or monthly) represents the active forming
        period up to as_of_date, with Close equal to the latest daily close.
      - There is zero look-ahead into future days of the week or month.

    Args:
        df: Daily OHLCV DataFrame with 'Date', 'Open', 'High', 'Low', 'Close', 'Volume'.
        timeframe: Timeframe.DAILY, Timeframe.WEEKLY, or Timeframe.MONTHLY.
        as_of_date: Evaluation cutoff timestamp.

    Returns:
        Aggregated OHLCV DataFrame for the requested timeframe.
    """
    if df.empty:
        return pd.DataFrame()

    clean = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(clean["Date"]):
        clean["Date"] = pd.to_datetime(clean["Date"])

    clean = clean.sort_values("Date").reset_index(drop=True)

    # Enforce point-in-time cutoff
    if as_of_date is not None:
        cutoff = pd.to_datetime(as_of_date)
        clean = clean[clean["Date"] <= cutoff]
        if clean.empty:
            return pd.DataFrame()

    tf = Timeframe(timeframe) if isinstance(timeframe, str) else timeframe

    out_df = clean
    if tf == Timeframe.DAILY:
        out_df = clean
    elif tf == Timeframe.WEEKLY:
        # Group by ISO year and calendar week (Monday to Sunday)
        # Any trading session occurring in that week is aggregated together.
        clean["_iso_year"] = clean["Date"].dt.isocalendar().year
        clean["_iso_week"] = clean["Date"].dt.isocalendar().week

        out_df = clean.groupby(["_iso_year", "_iso_week"], as_index=False).agg({
            "Date": "last",
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).sort_values("Date").reset_index(drop=True)

    elif tf == Timeframe.MONTHLY:
        # Group by calendar year and month (1st to last day of month)
        clean["_year"] = clean["Date"].dt.year
        clean["_month"] = clean["Date"].dt.month

        out_df = clean.groupby(["_year", "_month"], as_index=False).agg({
            "Date": "last",
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).sort_values("Date").reset_index(drop=True)

    if compute_rsi and not out_df.empty:
        out_df[f"RSI_{period}"] = compute_wilder_rsi(out_df["Close"], period=period)

    return out_df


def extract_multi_timeframe_indicators(
    df: pd.DataFrame,
    as_of_date: Optional[Union[str, pd.Timestamp]] = None,
    period: int = 14,
) -> Dict[str, Any]:
    """Computes independent Daily, Weekly, and Monthly Wilder RSI(14) series and latest values.
    
    Returns:
        Dictionary containing current and previous RSI values on all three timeframes,
        plus the latest observation date.
    """
    daily_df = resample_to_timeframe(df, Timeframe.DAILY, as_of_date=as_of_date)
    weekly_df = resample_to_timeframe(df, Timeframe.WEEKLY, as_of_date=as_of_date)
    monthly_df = resample_to_timeframe(df, Timeframe.MONTHLY, as_of_date=as_of_date)

    if daily_df.empty or len(daily_df) < 5:
        return {
            "valid": False,
            "error": "Insufficient daily price history",
        }

    daily_rsi_s = compute_wilder_rsi(daily_df["Close"], period=period)
    weekly_rsi_s = compute_wilder_rsi(weekly_df["Close"], period=period) if len(weekly_df) >= 2 else pd.Series(dtype=float)
    monthly_rsi_s = compute_wilder_rsi(monthly_df["Close"], period=period) if len(monthly_df) >= 2 else pd.Series(dtype=float)

    # Current (latest candle) values
    d_curr = float(daily_rsi_s.iloc[-1]) if not daily_rsi_s.empty and not pd.isna(daily_rsi_s.iloc[-1]) else None
    d_prev = float(daily_rsi_s.iloc[-2]) if len(daily_rsi_s) > 1 and not pd.isna(daily_rsi_s.iloc[-2]) else None

    w_curr = float(weekly_rsi_s.iloc[-1]) if not weekly_rsi_s.empty and not pd.isna(weekly_rsi_s.iloc[-1]) else None
    w_prev = float(weekly_rsi_s.iloc[-2]) if len(weekly_rsi_s) > 1 and not pd.isna(weekly_rsi_s.iloc[-2]) else None

    m_curr = float(monthly_rsi_s.iloc[-1]) if not monthly_rsi_s.empty and not pd.isna(monthly_rsi_s.iloc[-1]) else None
    m_prev = float(monthly_rsi_s.iloc[-2]) if len(monthly_rsi_s) > 1 and not pd.isna(monthly_rsi_s.iloc[-2]) else None

    latest_date_str = str(daily_df["Date"].iloc[-1].strftime("%Y-%m-%d"))

    return {
        "valid": True,
        "as_of_date": latest_date_str,
        "daily_close": float(daily_df["Close"].iloc[-1]),
        "daily_count": len(daily_df),
        "weekly_count": len(weekly_df),
        "monthly_count": len(monthly_df),
        "daily_rsi_14": round(d_curr, 2) if d_curr is not None else None,
        "prev_daily_rsi_14": round(d_prev, 2) if d_prev is not None else None,
        "weekly_rsi_14": round(w_curr, 2) if w_curr is not None else None,
        "prev_weekly_rsi_14": round(w_prev, 2) if w_prev is not None else None,
        "monthly_rsi_14": round(m_curr, 2) if m_curr is not None else None,
        "prev_monthly_rsi_14": round(m_prev, 2) if m_prev is not None else None,
    }
