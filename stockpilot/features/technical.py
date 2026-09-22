"""Vectorized technical indicator feature engineering for StockPilot."""

import logging
from typing import Optional
import numpy as np
import pandas as pd

from stockpilot.config import FeatureConfig

logger = logging.getLogger(__name__)


class TechnicalFeatureExtractor:
    """Computes pure vectorized technical indicators from OHLCV data.

    Strictly backward-looking with zero lookahead bias.
    """

    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()

    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Computes all technical features on the input OHLCV DataFrame."""
        if df.empty or len(df) < 5:
            logger.warning("DataFrame too small to compute technical indicators")
            return df

        feat = df.copy()

        # 1. Returns and Log Returns
        close = feat["Close"]
        for h in self.config.returns_horizons:
            feat[f"Return_{h}d"] = close.pct_change(h)
        feat["Log_Return_1d"] = np.log(close / close.shift(1))

        # 2. Rolling Volatility (annualized from 1d log returns)
        for w in self.config.volatility_windows:
            feat[f"Volatility_{w}d"] = feat["Log_Return_1d"].rolling(window=w, min_periods=max(5, w // 2)).std() * np.sqrt(252)

        # 3. Simple Moving Averages (SMA) & Normalized Distance
        for w in self.config.sma_windows:
            sma = close.rolling(window=w, min_periods=w // 2).mean()
            feat[f"SMA_{w}"] = sma
            feat[f"Dist_SMA_{w}"] = (close - sma) / sma

        # 4. Exponential Moving Averages (EMA) & Normalized Distance
        for w in self.config.ema_windows:
            ema = close.ewm(span=w, adjust=False).mean()
            feat[f"EMA_{w}"] = ema
            feat[f"Dist_EMA_{w}"] = (close - ema) / ema

        # 5. Relative Strength Index (RSI - Wilder's Smoothing)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        alpha = 1.0 / self.config.rsi_window
        avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
        avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        feat["RSI_14"] = 100.0 - (100.0 / (1.0 + rs))

        # 6. Moving Average Convergence Divergence (MACD)
        fast_ema = close.ewm(span=self.config.macd_fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.config.macd_slow, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        macd_signal = macd_line.ewm(span=self.config.macd_signal, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        feat["MACD_Line"] = macd_line
        feat["MACD_Signal"] = macd_signal
        feat["MACD_Hist"] = macd_hist
        feat["MACD_Norm"] = macd_line / close

        # 7. Bollinger Bands
        bb_sma = close.rolling(window=self.config.bb_window, min_periods=self.config.bb_window // 2).mean()
        bb_std = close.rolling(window=self.config.bb_window, min_periods=self.config.bb_window // 2).std()
        bb_upper = bb_sma + self.config.bb_std * bb_std
        bb_lower = bb_sma - self.config.bb_std * bb_std
        bb_bandwidth = (bb_upper - bb_lower) / (bb_sma + 1e-10)
        bb_pctb = (close - bb_lower) / ((bb_upper - bb_lower) + 1e-10)

        feat["BB_Upper"] = bb_upper
        feat["BB_Lower"] = bb_lower
        feat["BB_Bandwidth"] = bb_bandwidth
        feat["BB_PctB"] = bb_pctb

        # 8. Average True Range (ATR) & Normalized ATR (NATR)
        prev_close = close.shift(1)
        tr1 = feat["High"] - feat["Low"]
        tr2 = (feat["High"] - prev_close).abs()
        tr3 = (feat["Low"] - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr_alpha = 1.0 / self.config.atr_window
        atr = true_range.ewm(alpha=atr_alpha, adjust=False).mean()
        feat["ATR_14"] = atr
        feat["NATR_14"] = (atr / close) * 100.0

        # 9. Average Directional Index (ADX) with +DI and -DI
        high = feat["High"]
        low = feat["Low"]
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_dm_series = pd.Series(plus_dm, index=feat.index)
        minus_dm_series = pd.Series(minus_dm, index=feat.index)

        smooth_plus_dm = plus_dm_series.ewm(alpha=1.0 / self.config.adx_window, adjust=False).mean()
        smooth_minus_dm = minus_dm_series.ewm(alpha=1.0 / self.config.adx_window, adjust=False).mean()

        plus_di = 100.0 * (smooth_plus_dm / (atr + 1e-10))
        minus_di = 100.0 * (smooth_minus_dm / (atr + 1e-10))
        dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
        adx = dx.ewm(alpha=1.0 / self.config.adx_window, adjust=False).mean()

        feat["Plus_DI_14"] = plus_di
        feat["Minus_DI_14"] = minus_di
        feat["ADX_14"] = adx

        # 10. Stochastic Oscillator (%K and %D)
        stoch_k_win = self.config.stoch_k
        lowest_low = low.rolling(window=stoch_k_win, min_periods=stoch_k_win // 2).min()
        highest_high = high.rolling(window=stoch_k_win, min_periods=stoch_k_win // 2).max()
        raw_k = 100.0 * ((close - lowest_low) / ((highest_high - lowest_low) + 1e-10))
        smooth_k = raw_k.rolling(window=self.config.stoch_smooth_k, min_periods=1).mean()
        stoch_d = smooth_k.rolling(window=self.config.stoch_d, min_periods=1).mean()

        feat["Stoch_K"] = smooth_k
        feat["Stoch_D"] = stoch_d

        # 11. Volume Indicators: OBV, Relative Volume (RVOL)
        volume = feat["Volume"]
        price_change_sign = np.sign(close.diff()).fillna(0.0)
        obv = (price_change_sign * volume).cumsum()
        feat["OBV"] = obv
        feat["OBV_EMA_20"] = obv.ewm(span=20, adjust=False).mean()

        vol_sma_20 = volume.rolling(window=self.config.rvol_window, min_periods=5).mean()
        feat["RVOL_20"] = volume / (vol_sma_20 + 1e-10)

        # 12. 52-Week (252-day) Extremes
        w52 = self.config.extremes_52w_window
        rolling_52w_high = high.rolling(window=w52, min_periods=w52 // 4).max()
        rolling_52w_low = low.rolling(window=w52, min_periods=w52 // 4).min()

        feat["Dist_52w_High"] = (close - rolling_52w_high) / (rolling_52w_high + 1e-10)
        feat["Dist_52w_Low"] = (close - rolling_52w_low) / (rolling_52w_low + 1e-10)

        return feat
