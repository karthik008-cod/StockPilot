"""Institutional-grade financial feature engineering for StockPilot.

Implements:
1. Fractional Differentiation (Marcos López de Prado) for memory-preserving stationarity.
2. Advanced volatility estimators (Garman-Klass, Parkinson, Normalized ATR).
3. Long-memory regime metrics (Hurst Exponent via R/S analysis).
4. Multi-timeframe momentum, trend, and volume shock features.
"""

import logging
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from stockpilot.strategy.resampler import compute_wilder_rsi, resample_to_timeframe

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Fractional Differentiation (Memory-Preserving Stationarity)
# ==============================================================================

def get_fractional_weights(d: float, size: int, threshold: float = 1e-4) -> np.ndarray:
    """Computes binomial expansion weights for fractional differentiation.
    
    (1 - B)^d = sum_{k=0}^infty (-1)^k * binom(d, k) * B^k
    Weights satisfy recurrence: w_k = -w_{k-1} * (d - k + 1) / k
    """
    weights = [1.0]
    for k in range(1, size):
        w = -weights[-1] * (d - k + 1.0) / k
        if abs(w) < threshold:
            break
        weights.append(w)
    return np.array(weights[::-1])  # reverse for convolution


def fractional_differentiation(series: pd.Series, d: float, threshold: float = 1e-4) -> pd.Series:
    """Applies fixed-window fractional differentiation to preserve long-term price memory."""
    cleaned = series.dropna().astype(float)
    if len(cleaned) < 10:
        return series.copy()
    
    weights = get_fractional_weights(d, len(cleaned), threshold)
    k = len(weights)
    
    # Convolution with rolling dot product
    values = cleaned.values
    res = np.full(len(values), np.nan)
    for i in range(k - 1, len(values)):
        res[i] = np.dot(weights, values[i - k + 1: i + 1])
        
    return pd.Series(res, index=cleaned.index, name=f"{series.name}_frac_d{d:.2f}")


def estimate_hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """Computes the Hurst exponent using Rescaled Range (R/S) analysis.
    
    H > 0.5: Persistent (trending)
    H < 0.5: Anti-persistent (mean-reverting)
    H ~ 0.5: Random walk / Brownian motion
    """
    vals = series.dropna().values
    n = len(vals)
    if n < max_lag * 2:
        return 0.5

    lags = np.unique(np.logspace(0.7, np.log10(max_lag), num=8).astype(int))
    lags = [lag for lag in lags if lag >= 4 and lag < n]
    if len(lags) < 3:
        return 0.5

    rs_values = []
    for lag in lags:
        # Segment into chunks of size `lag`
        num_chunks = n // lag
        if num_chunks < 1:
            continue
        
        rs_chunk_list = []
        for i in range(num_chunks):
            chunk = vals[i * lag: (i + 1) * lag]
            m = np.mean(chunk)
            y = chunk - m
            z = np.cumsum(y)
            r = np.max(z) - np.min(z)
            s = np.std(chunk, ddof=1)
            if s > 1e-9:
                rs_chunk_list.append(r / s)
                
        if rs_chunk_list:
            rs_values.append((lag, np.mean(rs_chunk_list)))

    if len(rs_values) < 3:
        return 0.5

    log_lags = np.log([x[0] for x in rs_values])
    log_rs = np.log([x[1] for x in rs_values])
    poly = np.polyfit(log_lags, log_rs, 1)
    hurst = float(poly[0])
    return float(np.clip(hurst, 0.01, 0.99))


# ==============================================================================
# 2. Advanced Volatility Estimators
# ==============================================================================

def compute_garman_klass_volatility(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Computes Garman-Klass volatility estimator (jump and drift adjusted).
    
    sigma_GK^2 = 0.5 * ln(H/L)^2 - (2*ln(2) - 1) * ln(C/O)^2
    Annualized with sqrt(252).
    """
    log_hl = np.log(df["High"] / df["Low"])
    log_co = np.log(df["Close"] / df["Open"])
    gk_var = 0.5 * (log_hl ** 2) - (2 * np.log(2) - 1) * (log_co ** 2)
    rolling_gk = gk_var.rolling(window=window).mean()
    annualized_vol = np.sqrt(np.maximum(rolling_gk, 1e-8) * 252.0)
    return pd.Series(annualized_vol, index=df.index, name="garman_klass_vol")


def compute_parkinson_volatility(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Computes Parkinson extreme value volatility estimator.
    
    sigma_P^2 = ln(H/L)^2 / (4 * ln(2))
    Annualized with sqrt(252).
    """
    log_hl = np.log(df["High"] / df["Low"])
    park_var = (log_hl ** 2) / (4.0 * np.log(2.0))
    rolling_park = park_var.rolling(window=window).mean()
    annualized_vol = np.sqrt(np.maximum(rolling_park, 1e-8) * 252.0)
    return pd.Series(annualized_vol, index=df.index, name="parkinson_vol")


def compute_normalized_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Computes True Range normalized by Close price (NATR %)."""
    prev_close = df["Close"].shift(1)
    tr = np.maximum(
        df["High"] - df["Low"],
        np.maximum(
            np.abs(df["High"] - prev_close),
            np.abs(df["Low"] - prev_close)
        )
    )
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    natr = (atr / df["Close"]) * 100.0
    return pd.Series(natr, index=df.index, name="natr_pct")


# ==============================================================================
# 3. Comprehensive Feature Vector Generation
# ==============================================================================

class FeatureEngineeringPipeline:
    """Transforms raw OHLCV history into an institutional ML feature matrix."""

    def __init__(self, frac_d: float = 0.45):
        self.frac_d = frac_d

    def extract_features(
        self,
        df_daily: pd.DataFrame,
        benchmark_daily: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """Constructs a non-leaking, stationary feature table for a given stock."""
        if df_daily.empty or len(df_daily) < 60:
            return pd.DataFrame()

        df = df_daily.sort_values("Date").reset_index(drop=True).copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close", "Volume"]).reset_index(drop=True)

        features = pd.DataFrame(index=df.index)
        features["Date"] = df["Date"]

        close = df["Close"]

        # ── 1. Fractionally Differentiated Prices (Memory preserved) ──
        frac_close = fractional_differentiation(close, d=self.frac_d)
        features["frac_diff_price"] = frac_close.values

        # ── 2. Standard Returns over Horizons ──
        for lag in [1, 3, 5, 10, 21]:
            features[f"return_{lag}d"] = close.pct_change(lag) * 100.0

        # ── 3. Advanced Volatilities ──
        features["garman_klass_vol"] = compute_garman_klass_volatility(df, window=20).values
        features["parkinson_vol"] = compute_parkinson_volatility(df, window=20).values
        features["natr_14"] = compute_normalized_atr(df, period=14).values

        # Volatility expansion ratio: fast (5d) / slow (20d)
        fast_vol = df["Close"].pct_change().rolling(5).std()
        slow_vol = df["Close"].pct_change().rolling(20).std()
        features["vol_ratio_5_20"] = (fast_vol / (slow_vol + 1e-7)).values

        # ── 4. Multi-Timeframe Wilder RSI (Daily, Weekly, Monthly) ──
        daily_rsi = compute_wilder_rsi(close, period=14)
        features["daily_rsi_14"] = daily_rsi.values
        features["daily_rsi_slope_3d"] = daily_rsi.diff(3).values

        # Weekly candles
        df_weekly = resample_to_timeframe(df, timeframe="WEEKLY")
        if not df_weekly.empty:
            weekly_rsi = compute_wilder_rsi(df_weekly["Close"], period=14)
            df_weekly["weekly_rsi_14"] = weekly_rsi
            # Merge forward to daily candles (asof merge to strictly avoid lookahead)
            df_w_sub = df_weekly[["Date", "weekly_rsi_14"]].dropna()
            merged_w = pd.merge_asof(
                df[["Date"]], df_w_sub, on="Date", direction="backward"
            )
            features["weekly_rsi_14"] = merged_w["weekly_rsi_14"].values
        else:
            features["weekly_rsi_14"] = np.nan

        # Monthly candles
        df_monthly = resample_to_timeframe(df, timeframe="MONTHLY")
        if not df_monthly.empty:
            monthly_rsi = compute_wilder_rsi(df_monthly["Close"], period=14)
            df_monthly["monthly_rsi_14"] = monthly_rsi
            df_m_sub = df_monthly[["Date", "monthly_rsi_14"]].dropna()
            merged_m = pd.merge_asof(
                df[["Date"]], df_m_sub, on="Date", direction="backward"
            )
            features["monthly_rsi_14"] = merged_m["monthly_rsi_14"].values
        else:
            features["monthly_rsi_14"] = np.nan

        # ── 5. Trend Distances (Moving Averages) ──
        ema_20 = close.ewm(span=20, adjust=False).mean()
        ema_50 = close.ewm(span=50, adjust=False).mean()
        ema_200 = close.ewm(span=200, adjust=False).mean()
        features["dist_ema_20_pct"] = ((close - ema_20) / ema_20) * 100.0
        features["dist_ema_50_pct"] = ((close - ema_50) / ema_50) * 100.0
        features["dist_ema_200_pct"] = ((close - ema_200) / ema_200) * 100.0
        features["ema_50_200_ratio"] = (ema_50 / (ema_200 + 1e-7)).values

        # ── 6. Volume Dynamics ──
        vol_ma_20 = df["Volume"].rolling(20).mean()
        features["volume_shock"] = (df["Volume"] / (vol_ma_20 + 1e-7)).values

        # ── 7. Rolling Hurst Exponent (Memory & Trend Persistence) ──
        # Compute on rolling window of 60 days
        hurst_vals = np.full(len(df), np.nan)
        step = 5  # compute every 5 days for speed, then forward-fill
        for i in range(60, len(df), step):
            window_slice = close.iloc[i - 60: i]
            h = estimate_hurst_exponent(window_slice, max_lag=15)
            hurst_vals[i] = h
        features["hurst_exponent"] = pd.Series(hurst_vals, index=df.index).ffill().values

        # ── 8. Relative Strength against Benchmark ──
        if benchmark_daily is not None and not benchmark_daily.empty:
            bench = benchmark_daily.sort_values("Date").copy()
            bench["bench_ret_20d"] = bench["Close"].pct_change(20) * 100.0
            merged_bench = pd.merge(df[["Date"]], bench[["Date", "bench_ret_20d"]], on="Date", how="left")
            merged_bench["bench_ret_20d"] = merged_bench["bench_ret_20d"].ffill()
            features["excess_return_20d"] = features["return_21d"] - merged_bench["bench_ret_20d"].values
        else:
            features["excess_return_20d"] = 0.0

        # Drop burn-in rows
        features = features.iloc[40:].reset_index(drop=True)
        return features
