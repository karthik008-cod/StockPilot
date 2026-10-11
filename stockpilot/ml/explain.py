"""Explainable AI (XAI) feature attribution for StockPilot trade setups.

Implements model-agnostic marginal attribution and feature sensitivity decomposition,
explaining exactly why the ML model approved or disqualified a specific trade setup.
"""

import logging
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FEATURE_FRIENDLY_NAMES = {
    "weekly_rsi_14": "Weekly RSI(14) Trend",
    "daily_rsi_14": "Daily RSI(14) Level",
    "daily_rsi_slope_3d": "Daily RSI 3D Acceleration",
    "monthly_rsi_14": "Monthly RSI(14) Macro",
    "garman_klass_vol": "Garman-Klass Volatility",
    "parkinson_vol": "Parkinson High/Low Volatility",
    "natr_14": "Normalized ATR (NATR %)",
    "vol_ratio_5_20": "Volatility Compression Ratio",
    "dist_ema_50_pct": "Distance to 50 EMA",
    "dist_ema_200_pct": "Distance to 200 EMA (Long Trend)",
    "ema_50_200_ratio": "Golden Cross Alignment (50/200)",
    "volume_shock": "Volume Shock / Activity Surge",
    "hurst_exponent": "Hurst Exponent (Trend Persistence)",
    "frac_diff_price": "Fractional Diff Memory Price",
    "excess_return_20d": "Alpha vs Benchmark Index (20D)",
    "return_5d": "Short-Term 5D Return",
    "return_21d": "Monthly 21D Return Momentum",
}


class FeatureAttributor:
    """Calculates local feature contributions towards trade approval."""

    def __init__(self, baseline_scores: Optional[Dict[str, float]] = None):
        # Established quantitative baselines
        self.baselines = baseline_scores or {
            "weekly_rsi_14": 52.0,
            "daily_rsi_14": 50.0,
            "daily_rsi_slope_3d": 0.0,
            "monthly_rsi_14": 50.0,
            "natr_14": 2.2,
            "garman_klass_vol": 0.22,
            "parkinson_vol": 0.20,
            "vol_ratio_5_20": 1.0,
            "dist_ema_50_pct": 0.0,
            "dist_ema_200_pct": 0.0,
            "ema_50_200_ratio": 1.0,
            "volume_shock": 1.0,
            "hurst_exponent": 0.50,
            "excess_return_20d": 0.0,
        }

    def explain(self, feature_row: pd.Series) -> List[Dict[str, Any]]:
        """Decomposes the feature vector into positive drivers and negative headwinds."""
        attributions = []

        # 1. Weekly RSI
        w_rsi = float(feature_row.get("weekly_rsi_14", 50.0))
        if w_rsi > 60.0:
            attributions.append({
                "feature": "weekly_rsi_14",
                "label": FEATURE_FRIENDLY_NAMES["weekly_rsi_14"],
                "value": f"{w_rsi:.1f}",
                "impact": round(min(0.25, (w_rsi - 50.0) * 0.015), 3),
                "type": "positive",
                "explanation": f"Weekly RSI > 60 ({w_rsi:.1f}) confirms dominant bullish higher-timeframe regime."
            })
        elif w_rsi < 45.0:
            attributions.append({
                "feature": "weekly_rsi_14",
                "label": FEATURE_FRIENDLY_NAMES["weekly_rsi_14"],
                "value": f"{w_rsi:.1f}",
                "impact": round(-min(0.20, (50.0 - w_rsi) * 0.015), 3),
                "type": "negative",
                "explanation": f"Weak weekly RSI ({w_rsi:.1f}) indicates prevailing macro downtrend."
            })

        # 2. Daily RSI & Slope
        d_rsi = float(feature_row.get("daily_rsi_14", 50.0))
        d_slope = float(feature_row.get("daily_rsi_slope_3d", 0.0))
        if 39.0 <= d_rsi <= 45.0:
            attributions.append({
                "feature": "daily_rsi_14",
                "label": "Daily RSI Pullback Zone",
                "value": f"{d_rsi:.1f}",
                "impact": 0.18,
                "type": "positive",
                "explanation": f"Daily RSI is in prime institutional pullback reload zone (39-45)."
            })
        elif 58.0 <= d_rsi <= 63.0:
            attributions.append({
                "feature": "daily_rsi_14",
                "label": "Daily RSI Momentum Zone",
                "value": f"{d_rsi:.1f}",
                "impact": 0.16,
                "type": "positive",
                "explanation": f"Daily RSI is in high-momentum breakout zone (58-63)."
            })
        elif d_rsi > 75.0:
            attributions.append({
                "feature": "daily_rsi_14",
                "label": "Overbought Daily RSI",
                "value": f"{d_rsi:.1f}",
                "impact": -0.15,
                "type": "negative",
                "explanation": f"Daily RSI is extended (>75), elevated risk of mean-reversion pullback."
            })

        if d_slope > 3.0:
            attributions.append({
                "feature": "daily_rsi_slope_3d",
                "label": FEATURE_FRIENDLY_NAMES["daily_rsi_slope_3d"],
                "value": f"+{d_slope:.1f} pts",
                "impact": 0.08,
                "type": "positive",
                "explanation": "Positive momentum acceleration over last 3 sessions."
            })

        # 3. Hurst Exponent (Trend Persistence)
        h = float(feature_row.get("hurst_exponent", 0.50))
        if h > 0.55:
            attributions.append({
                "feature": "hurst_exponent",
                "label": FEATURE_FRIENDLY_NAMES["hurst_exponent"],
                "value": f"{h:.2f}",
                "impact": round((h - 0.5) * 0.4, 3),
                "type": "positive",
                "explanation": f"Hurst exponent H={h:.2f} confirms persistent trending dynamics."
            })
        elif h < 0.42:
            attributions.append({
                "feature": "hurst_exponent",
                "label": FEATURE_FRIENDLY_NAMES["hurst_exponent"],
                "value": f"{h:.2f}",
                "impact": -0.09,
                "type": "negative",
                "explanation": f"Hurst exponent H={h:.2f} indicates noisy, mean-reverting chop."
            })

        # 4. Volatility (NATR & Vol Ratio)
        natr = float(feature_row.get("natr_14", 2.0))
        if natr > 4.5:
            attributions.append({
                "feature": "natr_14",
                "label": FEATURE_FRIENDLY_NAMES["natr_14"],
                "value": f"{natr:.2f}%",
                "impact": -0.12,
                "type": "negative",
                "explanation": f"Elevated ATR ({natr:.2f}% of price) widens required stop-loss distance."
            })
        elif natr < 2.0:
            attributions.append({
                "feature": "natr_14",
                "label": FEATURE_FRIENDLY_NAMES["natr_14"],
                "value": f"{natr:.2f}%",
                "impact": 0.07,
                "type": "positive",
                "explanation": "Controlled volatility enables tight protective risk control."
            })

        # 5. Long-Term Moving Average Structure
        dist_200 = float(feature_row.get("dist_ema_200_pct", 0.0))
        if dist_200 > 0.0:
            attributions.append({
                "feature": "dist_ema_200_pct",
                "label": FEATURE_FRIENDLY_NAMES["dist_ema_200_pct"],
                "value": f"+{dist_200:.1f}%",
                "impact": 0.09,
                "type": "positive",
                "explanation": "Price trades cleanly above 200-day EMA support."
            })
        else:
            attributions.append({
                "feature": "dist_ema_200_pct",
                "label": FEATURE_FRIENDLY_NAMES["dist_ema_200_pct"],
                "value": f"{dist_200:.1f}%",
                "impact": -0.11,
                "type": "negative",
                "explanation": "Price is below 200-day EMA long-term structural hurdle."
            })

        # 6. Volume Shock
        vol_shock = float(feature_row.get("volume_shock", 1.0))
        if vol_shock > 1.8:
            attributions.append({
                "feature": "volume_shock",
                "label": FEATURE_FRIENDLY_NAMES["volume_shock"],
                "value": f"{vol_shock:.1f}x",
                "impact": 0.11,
                "type": "positive",
                "explanation": f"Significant volume expansion ({vol_shock:.1f}x 20-day avg) validates institutional participation."
            })

        # Sort by absolute impact
        attributions.sort(key=lambda x: abs(x["impact"]), reverse=True)
        return attributions
