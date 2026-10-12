"""Smart Stock Recommendation Engine for StockPilot.

Scans the NIFTY universe, scores stocks using a term-weighted multi-factor
composite model, ranks them by suitability, generates actionable trade plans
(entry zone, stop-loss, targets, R:R), and provides transparent reasoning
explaining WHY each stock was recommended.

Supports:
  - Term selection: short / medium / long / custom target date
  - Filtering by index tier (NIFTY 50/100/200/500) and/or sector
  - Multi-factor scoring with weights that shift per investment horizon
"""

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from stockpilot.data.cleaner import DataCleaner
from stockpilot.data.loader import DataLoader, _sanitize_ticker
from stockpilot.ml.features import FeatureEngineeringPipeline
from stockpilot.trade.planner import TradePlanner, TERM_CONFIGS
from stockpilot.universe import universe as universe_mgr

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Term-Weighted Factor Definitions
# ──────────────────────────────────────────────────────────────────────────────

# Factor weights shift depending on the user's investment horizon.
# Each factor is scored 0-100, then weighted and summed into a composite score.
# High Risk-to-Reward ratio is given strong explicit weight across all terms.
TERM_FACTOR_WEIGHTS = {
    "short": {
        "daily_rsi_zone":    0.18,
        "weekly_rsi_trend":  0.07,
        "monthly_rsi_trend": 0.02,
        "hurst_persistence": 0.12,
        "volatility_fit":    0.13,
        "ema_structure":     0.07,
        "volume_surge":      0.14,
        "alpha_benchmark":   0.05,
        "rsi_slope":         0.04,
        "risk_reward_fit":   0.18,
    },
    "medium": {
        "daily_rsi_zone":    0.11,
        "weekly_rsi_trend":  0.15,
        "monthly_rsi_trend": 0.08,
        "hurst_persistence": 0.15,
        "volatility_fit":    0.06,
        "ema_structure":     0.13,
        "volume_surge":      0.05,
        "alpha_benchmark":   0.08,
        "rsi_slope":         0.02,
        "risk_reward_fit":   0.17,
    },
    "long": {
        "daily_rsi_zone":    0.04,
        "weekly_rsi_trend":  0.12,
        "monthly_rsi_trend": 0.18,
        "hurst_persistence": 0.11,
        "volatility_fit":    0.04,
        "ema_structure":     0.18,
        "volume_surge":      0.00,
        "alpha_benchmark":   0.07,
        "rsi_slope":         0.06,
        "risk_reward_fit":   0.20,
    },
}

# Ideal parameter ranges per term for volatility suitability
VOLATILITY_IDEAL = {
    "short":  {"natr_min": 1.2, "natr_max": 4.5, "natr_sweet": 2.5},
    "medium": {"natr_min": 1.0, "natr_max": 5.0, "natr_sweet": 2.0},
    "long":   {"natr_min": 0.6, "natr_max": 4.0, "natr_sweet": 1.5},
}

# Minimum composite score threshold to include in recommendations
MIN_COMPOSITE_SCORE = 45.0

# Minimum risk-to-reward ratio threshold (never recommend trades below 1:1)
MIN_RISK_REWARD_RATIO = 1.0

# Maximum number of stocks to process in parallel
MAX_PARALLEL_SCANS = 12


class StockScore:
    """Holds the multi-factor score breakdown for a single stock."""

    def __init__(self, ticker: str, company_name: str, sector: str, indices: List[str]):
        self.ticker = ticker
        self.company_name = company_name
        self.sector = sector
        self.indices = indices

        # Individual factor scores (0-100 scale)
        self.daily_rsi_zone: float = 0.0
        self.weekly_rsi_trend: float = 0.0
        self.monthly_rsi_trend: float = 0.0
        self.hurst_persistence: float = 0.0
        self.volatility_fit: float = 0.0
        self.ema_structure: float = 0.0
        self.volume_surge: float = 0.0
        self.alpha_benchmark: float = 0.0
        self.rsi_slope: float = 0.0
        self.risk_reward_fit: float = 0.0

        # Weighted composite
        self.composite_score: float = 0.0

        # Raw feature values for reasoning
        self.raw_features: Dict[str, float] = {}

        # Trade plan data
        self.current_price: float = 0.0
        self.entry_zone: Dict[str, float] = {}
        self.target_1: Dict[str, float] = {}
        self.target_2: Dict[str, float] = {}
        self.stop_loss: Dict[str, float] = {}
        self.risk_reward_ratio: float = 0.0
        self.expected_holding_days: int = 0
        self.trend: str = "Neutral"

        # Reasoning
        self.key_notes: List[str] = []
        self.why_recommended: str = ""
        self.risk_factors: List[str] = []

        # Status
        self.is_valid: bool = False
        self.error: str = ""

    def compute_composite(self, term: str) -> float:
        """Computes the weighted composite score using term-specific weights."""
        weights = TERM_FACTOR_WEIGHTS.get(term, TERM_FACTOR_WEIGHTS["medium"])
        scores = {
            "daily_rsi_zone":    self.daily_rsi_zone,
            "weekly_rsi_trend":  self.weekly_rsi_trend,
            "monthly_rsi_trend": self.monthly_rsi_trend,
            "hurst_persistence": self.hurst_persistence,
            "volatility_fit":    self.volatility_fit,
            "ema_structure":     self.ema_structure,
            "volume_surge":      self.volume_surge,
            "alpha_benchmark":   self.alpha_benchmark,
            "rsi_slope":         self.rsi_slope,
            "risk_reward_fit":   self.risk_reward_fit,
        }
        self.composite_score = sum(scores[k] * weights.get(k, 0.0) for k in scores)
        self.composite_score = round(min(100.0, max(0.0, self.composite_score)), 1)
        return self.composite_score

    def to_dict(self) -> Dict[str, Any]:
        """Serializes to API-friendly dictionary."""
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "sector": self.sector,
            "indices": self.indices,
            "composite_score": self.composite_score,
            "current_price": self.current_price,
            "entry_zone": self.entry_zone,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "stop_loss": self.stop_loss,
            "risk_reward_ratio": self.risk_reward_ratio,
            "expected_holding_days": self.expected_holding_days,
            "trend": self.trend,
            "key_notes": self.key_notes,
            "why_recommended": self.why_recommended,
            "risk_factors": self.risk_factors,
            "score_breakdown": {
                "daily_rsi_zone": round(self.daily_rsi_zone, 1),
                "weekly_rsi_trend": round(self.weekly_rsi_trend, 1),
                "monthly_rsi_trend": round(self.monthly_rsi_trend, 1),
                "hurst_persistence": round(self.hurst_persistence, 1),
                "volatility_fit": round(self.volatility_fit, 1),
                "ema_structure": round(self.ema_structure, 1),
                "volume_surge": round(self.volume_surge, 1),
                "alpha_benchmark": round(self.alpha_benchmark, 1),
                "rsi_slope": round(self.rsi_slope, 1),
                "risk_reward_fit": round(self.risk_reward_fit, 1),
            },
            "raw_features": {k: round(v, 3) for k, v in self.raw_features.items()},
        }


# ──────────────────────────────────────────────────────────────────────────────
# Scoring Functions (each returns 0-100)
# ──────────────────────────────────────────────────────────────────────────────

def _score_risk_reward(rr: float) -> float:
    """Scores risk-to-reward ratio for trade quality and asymmetry.

    Minimum threshold: 1.0:1 (score = 50)
    1.5:1 -> 75
    2.0:1 -> 90
    2.5:1+ -> 100
    Below 1.0:1 -> 0
    """
    if rr < 1.0:
        return 0.0
    if rr >= 2.5:
        return 100.0
    elif rr >= 2.0:
        return 90.0 + (rr - 2.0) * 20.0
    elif rr >= 1.5:
        return 75.0 + (rr - 1.5) * 30.0
    else:
        return 50.0 + (rr - 1.0) * 50.0


def _score_daily_rsi_zone(d_rsi: float, term: str) -> float:
    """Scores daily RSI based on optimal momentum zones per term.
    
    Short-term: ideal 48-68 (strong daily momentum)
    Medium-term: ideal 45-65 (healthy uptrend reloading)
    Long-term: ideal 40-60 (not overbought)
    """
    zones = {
        "short":  (48.0, 68.0),
        "medium": (45.0, 65.0),
        "long":   (40.0, 60.0),
    }
    lo, hi = zones.get(term, (45.0, 65.0))
    mid = (lo + hi) / 2.0

    if lo <= d_rsi <= hi:
        # In sweet spot — score 70-100
        dist_from_mid = abs(d_rsi - mid) / ((hi - lo) / 2.0)
        return 100.0 - 30.0 * dist_from_mid
    elif d_rsi < lo:
        # Below zone — penalize proportionally
        deficit = lo - d_rsi
        return max(0.0, 70.0 - deficit * 3.5)
    else:
        # Above zone (overbought risk)
        excess = d_rsi - hi
        return max(0.0, 65.0 - excess * 3.0)


def _score_weekly_rsi_trend(w_rsi: float) -> float:
    """Scores weekly RSI for bullish structure.
    
    Ideal: 50-70 (sustained uptrend confirmation)
    """
    if 50.0 <= w_rsi <= 70.0:
        # Sweet spot
        center = 60.0
        dist = abs(w_rsi - center) / 10.0
        return 95.0 - 20.0 * dist
    elif 45.0 <= w_rsi < 50.0:
        return 55.0 + (w_rsi - 45.0) * 3.0  # 55-70
    elif 70.0 < w_rsi <= 80.0:
        return 75.0 - (w_rsi - 70.0) * 3.0  # 75-45
    elif w_rsi > 80.0:
        return max(10.0, 45.0 - (w_rsi - 80.0) * 4.0)
    else:
        return max(0.0, 55.0 - (45.0 - w_rsi) * 4.0)


def _score_monthly_rsi_trend(m_rsi: float) -> float:
    """Scores monthly RSI for secular trend health.
    
    Ideal: 55-75 (long-term bullish confirmation without extreme overbought)
    """
    if 55.0 <= m_rsi <= 75.0:
        center = 65.0
        dist = abs(m_rsi - center) / 10.0
        return 95.0 - 15.0 * dist
    elif 45.0 <= m_rsi < 55.0:
        return 50.0 + (m_rsi - 45.0) * 3.0
    elif 75.0 < m_rsi <= 85.0:
        return 80.0 - (m_rsi - 75.0) * 4.0
    elif m_rsi > 85.0:
        return max(5.0, 40.0 - (m_rsi - 85.0) * 5.0)
    else:
        return max(0.0, 50.0 - (45.0 - m_rsi) * 4.0)


def _score_hurst_persistence(hurst: float, term: str) -> float:
    """Scores Hurst exponent for trend persistence.
    
    H > 0.55: Persistent trending — ideal for all terms
    H ~ 0.50: Random walk — low conviction
    H < 0.45: Mean-reverting noise — poor for trend following
    """
    if hurst >= 0.65:
        return min(100.0, 80.0 + (hurst - 0.65) * 200.0)
    elif 0.55 <= hurst < 0.65:
        return 65.0 + (hurst - 0.55) * 150.0
    elif 0.48 <= hurst < 0.55:
        return 35.0 + (hurst - 0.48) * 428.0  # 35-65
    elif 0.40 <= hurst < 0.48:
        return 15.0 + (hurst - 0.40) * 250.0  # 15-35
    else:
        return max(0.0, hurst * 30.0)


def _score_volatility_fit(natr: float, term: str) -> float:
    """Scores NATR volatility regime against term-ideal ranges.
    
    Each term has a sweet spot. Too low = no movement potential. Too high = excessive risk.
    """
    ideal = VOLATILITY_IDEAL.get(term, VOLATILITY_IDEAL["medium"])
    sweet = ideal["natr_sweet"]
    low = ideal["natr_min"]
    high = ideal["natr_max"]

    if low <= natr <= high:
        dist_from_sweet = abs(natr - sweet) / max(high - low, 0.5)
        return 90.0 - 35.0 * dist_from_sweet
    elif natr < low:
        return max(10.0, 55.0 - (low - natr) * 30.0)
    else:
        return max(5.0, 55.0 - (natr - high) * 15.0)


def _score_ema_structure(dist_50: float, dist_200: float, ema_ratio: float) -> float:
    """Scores EMA structural trend alignment.
    
    Best: Price > EMA50 > EMA200 (golden cross structure)
    Good: Price > EMA200 with healthy pullback to EMA50
    Poor: Price < EMA200 (structural downtrend)
    """
    score = 50.0  # neutral baseline

    # Above 200 EMA is the primary structural requirement
    if dist_200 > 0:
        score += min(25.0, dist_200 * 1.2)
    else:
        score -= min(40.0, abs(dist_200) * 2.5)

    # Golden cross (EMA50 > EMA200)
    if ema_ratio > 1.0:
        score += min(15.0, (ema_ratio - 1.0) * 150.0)
    else:
        score -= min(15.0, (1.0 - ema_ratio) * 150.0)

    # Distance from EMA50 — close to it is healthy, too far is overextended
    if 0.0 < dist_50 <= 5.0:
        score += 10.0  # Healthy proximity
    elif dist_50 > 12.0:
        score -= min(10.0, (dist_50 - 12.0) * 1.5)  # Overextended
    elif dist_50 < -3.0:
        score -= min(10.0, abs(dist_50 + 3.0) * 2.0)  # Below EMA50

    return max(0.0, min(100.0, score))


def _score_volume_surge(vol_shock: float) -> float:
    """Scores volume conviction relative to 20-day average.
    
    > 1.5x: Strong institutional activity
    1.0-1.5x: Normal
    < 0.7x: Low conviction / drying volume
    """
    if vol_shock >= 2.0:
        return min(100.0, 80.0 + (vol_shock - 2.0) * 20.0)
    elif 1.4 <= vol_shock < 2.0:
        return 60.0 + (vol_shock - 1.4) * 33.0
    elif 1.0 <= vol_shock < 1.4:
        return 40.0 + (vol_shock - 1.0) * 50.0
    elif 0.7 <= vol_shock < 1.0:
        return 20.0 + (vol_shock - 0.7) * 66.0
    else:
        return max(0.0, vol_shock * 28.0)


def _score_alpha_benchmark(alpha_20d: float) -> float:
    """Scores relative strength (alpha) over benchmark NIFTY index.
    
    Positive alpha = outperforming the market.
    """
    if alpha_20d >= 10.0:
        return min(100.0, 85.0 + (alpha_20d - 10.0) * 1.5)
    elif 5.0 <= alpha_20d < 10.0:
        return 65.0 + (alpha_20d - 5.0) * 4.0
    elif 0.0 <= alpha_20d < 5.0:
        return 45.0 + alpha_20d * 4.0
    elif -5.0 <= alpha_20d < 0.0:
        return 25.0 + (alpha_20d + 5.0) * 4.0
    else:
        return max(0.0, 25.0 + alpha_20d * 2.0)


def _score_rsi_slope(slope_3d: float) -> float:
    """Scores daily RSI 3-day slope for momentum direction.
    
    Positive slope = strengthening momentum
    Negative slope = weakening / topping out
    """
    if slope_3d >= 3.0:
        return min(100.0, 80.0 + slope_3d * 2.0)
    elif 0.5 <= slope_3d < 3.0:
        return 60.0 + (slope_3d - 0.5) * 8.0
    elif -0.5 <= slope_3d < 0.5:
        return 45.0 + slope_3d * 30.0  # Flat — neutral
    elif -3.0 <= slope_3d < -0.5:
        return 20.0 + (slope_3d + 3.0) * 10.0
    else:
        return max(0.0, 20.0 + (slope_3d + 3.0) * 5.0)


# ──────────────────────────────────────────────────────────────────────────────
# Reasoning Generator
# ──────────────────────────────────────────────────────────────────────────────

def _generate_key_notes(ss: StockScore, term: str) -> List[str]:
    """Generates human-readable key observations for the stock."""
    notes = []
    f = ss.raw_features

    d_rsi = f.get("daily_rsi_14", 50)
    w_rsi = f.get("weekly_rsi_14", 50)
    m_rsi = f.get("monthly_rsi_14", 50)
    hurst = f.get("hurst_exponent", 0.5)
    natr = f.get("natr_14", 2.0)
    dist_200 = f.get("dist_ema_200_pct", 0)
    dist_50 = f.get("dist_ema_50_pct", 0)
    ema_ratio = f.get("ema_50_200_ratio", 1.0)
    vol_shock = f.get("volume_shock", 1.0)
    alpha = f.get("excess_return_20d", 0)
    rsi_slope = f.get("daily_rsi_slope_3d", 0)

    # Trend structure
    if dist_200 > 0 and ema_ratio > 1.0:
        notes.append(f"Trading above 50 & 200 EMA with golden cross (EMA ratio: {ema_ratio:.3f})")
    elif dist_200 > 0:
        notes.append(f"Above 200 EMA (+{dist_200:.1f}%), structural uptrend intact")
    elif dist_200 < -5:
        notes.append(f"⚠️ Trading {dist_200:.1f}% below 200 EMA — structural downtrend")

    # Weekly RSI
    if w_rsi > 60:
        notes.append(f"Strong weekly RSI uptrend at {w_rsi:.1f} — sustained institutional momentum")
    elif 50 <= w_rsi <= 60:
        notes.append(f"Weekly RSI at {w_rsi:.1f} — healthy bullish territory")
    elif w_rsi < 40:
        notes.append(f"⚠️ Weekly RSI weak at {w_rsi:.1f} — lacks higher timeframe confirmation")

    # Hurst persistence
    if hurst > 0.60:
        notes.append(f"Hurst exponent {hurst:.2f} confirms persistent trend — price moves are NOT random noise")
    elif hurst < 0.45:
        notes.append(f"⚠️ Hurst {hurst:.2f} suggests mean-reverting noise — trend following less reliable")

    # Volume
    if vol_shock > 1.5:
        notes.append(f"Volume surge {vol_shock:.1f}× above 20-day average — fresh institutional accumulation")
    elif vol_shock < 0.6:
        notes.append(f"⚠️ Low volume at {vol_shock:.1f}× average — lacks conviction")

    # Alpha
    if alpha > 5:
        notes.append(f"Outperforming NIFTY by +{alpha:.1f}% over 20 days — strong relative strength")
    elif alpha < -5:
        notes.append(f"⚠️ Underperforming NIFTY by {alpha:.1f}% — relative weakness")

    # Daily RSI momentum
    if rsi_slope > 2.0:
        notes.append(f"Daily RSI accelerating (+{rsi_slope:.1f} slope) — building momentum")
    elif rsi_slope < -2.0:
        notes.append(f"⚠️ Daily RSI decelerating ({rsi_slope:.1f} slope) — momentum fading")

    # NATR volatility
    ideal = VOLATILITY_IDEAL.get(term, VOLATILITY_IDEAL["medium"])
    if ideal["natr_min"] <= natr <= ideal["natr_max"]:
        notes.append(f"NATR {natr:.1f}% volatility well-suited for {term}-term trading")
    elif natr > ideal["natr_max"]:
        notes.append(f"⚠️ High volatility (NATR {natr:.1f}%) — wider stops needed, manage position size")

    return notes


def _generate_risk_factors(ss: StockScore, term: str) -> List[str]:
    """Generates risk warnings for the recommendation."""
    risks = []
    f = ss.raw_features

    d_rsi = f.get("daily_rsi_14", 50)
    m_rsi = f.get("monthly_rsi_14", 50)
    natr = f.get("natr_14", 2.0)
    dist_200 = f.get("dist_ema_200_pct", 0)
    hurst = f.get("hurst_exponent", 0.5)
    vol_shock = f.get("volume_shock", 1.0)
    vol_ratio = f.get("vol_ratio_5_20", 1.0)

    if d_rsi > 72:
        risks.append(f"Daily RSI at {d_rsi:.1f} — overbought, consider waiting for a pullback to entry zone")
    if m_rsi > 78:
        risks.append(f"Monthly RSI at {m_rsi:.1f} — parabolic extension risk, tighten trailing stop")
    if natr > 4.5:
        risks.append(f"High volatility (NATR {natr:.1f}%) — expect wide intraday swings, reduce position size")
    if dist_200 > 30:
        risks.append(f"Extended {dist_200:.0f}% above 200 EMA — mean reversion risk on any negative catalyst")
    if hurst < 0.48:
        risks.append(f"Low Hurst ({hurst:.2f}) — trend may not persist, apply strict stop-loss discipline")
    if vol_ratio > 2.0:
        risks.append(f"Volatility expanding rapidly (5d/20d ratio: {vol_ratio:.1f}×) — regime shift risk")
    if vol_shock < 0.7:
        risks.append("Declining volume — breakout/continuation moves need volume confirmation")
    if dist_200 < -5:
        risks.append(f"Below 200 EMA structural support — higher probability of further downside")

    if not risks:
        risks.append("No major risk flags detected — standard position sizing and stop-loss discipline apply")

    return risks


def _generate_why_recommended(ss: StockScore, term: str, total_universe: int) -> str:
    """Generates a comprehensive explanation of why this stock was selected."""
    f = ss.raw_features
    clean_name = ss.company_name or ss.ticker.replace(".NS", "")
    term_label = {"short": "short-term", "medium": "medium-term", "long": "long-term"}.get(term, "medium-term")

    strengths = []
    top_scores = sorted(
        [
            ("trend structure", ss.ema_structure),
            ("momentum", ss.weekly_rsi_trend),
            ("trend persistence", ss.hurst_persistence),
            ("volatility suitability", ss.volatility_fit),
            ("volume conviction", ss.volume_surge),
            ("relative strength", ss.alpha_benchmark),
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    for name, score in top_scores[:3]:
        if score >= 65:
            strengths.append(name)

    strengths_str = ", ".join(strengths) if strengths else "balanced technical structure"

    d_rsi = f.get("daily_rsi_14", 50)
    w_rsi = f.get("weekly_rsi_14", 50)
    hurst = f.get("hurst_exponent", 0.5)
    dist_200 = f.get("dist_ema_200_pct", 0)
    alpha = f.get("excess_return_20d", 0)
    vol_shock = f.get("volume_shock", 1.0)

    parts = [
        f"{clean_name} ranks in the top selections among {total_universe} NIFTY stocks "
        f"for {term_label} trading with a composite score of {ss.composite_score}/100."
    ]

    parts.append(
        f"Its strongest factors are {strengths_str}."
    )

    # Add specific metric citations
    if dist_200 > 0 and f.get("ema_50_200_ratio", 1.0) > 1.0:
        parts.append(
            f"The stock maintains a healthy structural uptrend, trading {dist_200:.1f}% above its 200-day EMA "
            f"with a golden cross formation."
        )
    elif dist_200 > 0:
        parts.append(f"Structurally positioned {dist_200:.1f}% above the 200-day EMA.")

    if hurst > 0.55:
        parts.append(
            f"A Hurst exponent of {hurst:.2f} confirms that price movements exhibit genuine trending behavior "
            f"rather than random noise — this is a statistically measurable edge."
        )

    if w_rsi >= 55:
        parts.append(f"Weekly RSI at {w_rsi:.1f} indicates sustained institutional-grade momentum.")

    if vol_shock > 1.3:
        parts.append(
            f"Volume at {vol_shock:.1f}× the 20-day average signals active institutional participation."
        )

    if alpha > 3:
        parts.append(
            f"Alpha of +{alpha:.1f}% over NIFTY demonstrates independent relative strength — "
            f"this stock is outperforming the broader market."
        )

    # Risk-reward context
    if ss.risk_reward_ratio >= 1.0:
        rr_rating = "exceptional" if ss.risk_reward_ratio >= 2.0 else ("attractive" if ss.risk_reward_ratio >= 1.5 else "solid")
        parts.append(
            f"The trade plan offers an {rr_rating} {ss.risk_reward_ratio:.2f}:1 risk-to-reward ratio "
            f"(with {ss.target_1.get('pct', 0):.1f}% primary upside target against {abs(ss.stop_loss.get('pct', 0)):.1f}% stop-loss), "
            f"comfortably meeting or exceeding the minimum 1:1 asymmetric payoff requirement."
        )

    return " ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Main Recommender Engine
# ──────────────────────────────────────────────────────────────────────────────

class StockRecommender:
    """Scans the NIFTY universe, scores, ranks, and recommends stocks."""

    def __init__(
        self,
        loader: Optional[DataLoader] = None,
        cleaner: Optional[DataCleaner] = None,
    ):
        self.loader = loader or DataLoader()
        self.cleaner = cleaner or DataCleaner()
        self.feature_pipeline = FeatureEngineeringPipeline(frac_d=0.45)
        self.planner = TradePlanner()

        # Cache benchmark data for alpha computation
        self._benchmark_df: Optional[pd.DataFrame] = None
        self._load_benchmark()

    def _load_benchmark(self):
        """Loads and caches benchmark NIFTY 50 data."""
        try:
            bench_df = self.loader.load_ohlcv("^NSEI", start_date="2020-01-01")
            if not bench_df.empty and len(bench_df) >= 100:
                self._benchmark_df = bench_df.tail(500).reset_index(drop=True)
        except Exception as e:
            logger.warning("Could not load benchmark for recommender: %s", e)

    def _resolve_term_from_date(self, target_date: str) -> str:
        """Converts a specific target date to the nearest matching term."""
        try:
            dt = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            return "medium"

        today = date.today()
        delta_days = (dt - today).days

        if delta_days <= 0:
            return "short"
        elif delta_days <= 15:
            return "short"
        elif delta_days <= 60:
            return "medium"
        else:
            return "long"

    def _ensure_universe_freshness(self, stocks: List[Dict[str, Any]]) -> None:
        """Batch-syncs any universe stocks whose cached data is older than 2 calendar days."""
        today = date.today()

        # 1. Benchmark freshness
        try:
            bench_path = self.loader.cache_dir / "INDEX_NSEI_ohlcv.parquet"
            bench_stale = True
            if bench_path.exists():
                bench_df = pd.read_parquet(bench_path)
                if not bench_df.empty and "Date" in bench_df.columns:
                    b_last = pd.to_datetime(bench_df["Date"]).max().date()
                    if (today - b_last).days <= 2:
                        bench_stale = False
            if bench_stale:
                self.loader.sync_live_ohlcv("^NSEI")
                self._load_benchmark()
        except Exception as be:
            logger.warning("Error checking benchmark freshness: %s", be)

        # 2. Universe stocks freshness
        stale_tickers = []
        for s in stocks:
            sym = s.get("symbol")
            if not sym:
                continue
            safe_sym = _sanitize_ticker(sym)
            meta_path = self.loader.cache_dir / f"{safe_sym}_ohlcv.meta.json"
            parquet_path = self.loader.cache_dir / f"{safe_sym}_ohlcv.parquet"

            if not parquet_path.exists():
                stale_tickers.append(sym)
                continue

            is_stale = True
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    last_str = meta.get("last_date")
                    if last_str:
                        last_d = datetime.strptime(last_str, "%Y-%m-%d").date()
                        if (today - last_d).days <= 2:
                            is_stale = False
                except Exception:
                    is_stale = True

            if is_stale:
                stale_tickers.append(sym)

        if stale_tickers:
            logger.info("Batch-syncing live market data through today (%s) for %d stale stocks...", today, len(stale_tickers))
            self.loader.sync_batch_ohlcv(stale_tickers, chunk_size=40)

    def _score_single_stock(
        self,
        ticker: str,
        stock_meta: Dict[str, Any],
        term: str,
    ) -> StockScore:
        """Computes all factor scores for a single stock."""
        ss = StockScore(
            ticker=ticker,
            company_name=stock_meta.get("name", ticker),
            sector=stock_meta.get("sector", ""),
            indices=stock_meta.get("indices", []),
        )

        try:
            # Load OHLCV data (with auto-sync enabled)
            df = self.loader.load_ohlcv(ticker, start_date="2020-01-01", auto_sync=True)
            if df.empty or len(df) < 80:
                ss.error = f"Insufficient data ({len(df)} rows)"
                return ss

            if len(df) > 500:
                df = df.tail(500).reset_index(drop=True)

            # Clean data
            cleaned = self.cleaner.clean_ohlcv(df, ticker_name=ticker)
            if cleaned.empty or len(cleaned) < 60:
                ss.error = "Insufficient clean data"
                return ss

            # ── Generate trade levels using TradePlanner FIRST ──
            try:
                plan = self.planner.plan_full_trade(
                    cleaned,
                    ticker=ticker,
                    trade_term=term,
                    trading_type="swing" if term == "short" else ("positional" if term == "medium" else "investing"),
                )
                ss.current_price = plan.entry_price
                ss.entry_zone = {"min": plan.entry_zone_min, "max": plan.entry_zone_max}
                ss.target_1 = {"price": plan.target_1, "pct": plan.target_1_pct}
                ss.target_2 = {"price": plan.target_2, "pct": plan.target_2_pct}
                ss.stop_loss = {"price": plan.stop_loss, "pct": plan.stop_loss_pct}
                ss.risk_reward_ratio = plan.risk_reward_ratio
                ss.expected_holding_days = plan.expected_holding_days
                ss.trend = plan.trend
            except Exception as plan_err:
                logger.debug("Trade plan generation failed for %s: %s", ticker, plan_err)
                cmp = float(cleaned["Close"].iloc[-1])
                ss.current_price = round(cmp, 2)
                ss.entry_zone = {"min": round(cmp * 0.995, 2), "max": round(cmp * 1.005, 2)}
                ss.risk_reward_ratio = 1.0

            # Enforce minimum 1:1 Risk-to-Reward ratio constraint
            if ss.risk_reward_ratio < MIN_RISK_REWARD_RATIO:
                ss.error = f"Risk-to-reward ratio {ss.risk_reward_ratio:.2f}:1 is below required minimum 1:1"
                ss.is_valid = False
                return ss

            # Score the Risk-to-Reward ratio
            ss.risk_reward_fit = _score_risk_reward(ss.risk_reward_ratio)

            # Extract ML features
            feats_df = self.feature_pipeline.extract_features(cleaned, self._benchmark_df)
            if feats_df.empty:
                ss.error = "Feature extraction failed"
                return ss

            latest = feats_df.iloc[-1]

            # Store raw feature values for reasoning
            feature_keys = [
                "daily_rsi_14", "weekly_rsi_14", "monthly_rsi_14",
                "hurst_exponent", "natr_14", "dist_ema_50_pct", "dist_ema_200_pct",
                "ema_50_200_ratio", "volume_shock", "excess_return_20d",
                "daily_rsi_slope_3d", "vol_ratio_5_20", "garman_klass_vol",
                "parkinson_vol", "return_5d", "return_21d",
            ]
            for k in feature_keys:
                val = latest.get(k)
                ss.raw_features[k] = float(val) if val is not None and not (isinstance(val, float) and math.isnan(val)) else 0.0

            f = ss.raw_features

            # ── Compute individual factor scores ──
            ss.daily_rsi_zone = _score_daily_rsi_zone(f["daily_rsi_14"], term)
            ss.weekly_rsi_trend = _score_weekly_rsi_trend(f["weekly_rsi_14"])
            ss.monthly_rsi_trend = _score_monthly_rsi_trend(f["monthly_rsi_14"])
            ss.hurst_persistence = _score_hurst_persistence(f["hurst_exponent"], term)
            ss.volatility_fit = _score_volatility_fit(f["natr_14"], term)
            ss.ema_structure = _score_ema_structure(
                f["dist_ema_50_pct"], f["dist_ema_200_pct"], f["ema_50_200_ratio"]
            )
            ss.volume_surge = _score_volume_surge(f["volume_shock"])
            ss.alpha_benchmark = _score_alpha_benchmark(f["excess_return_20d"])
            ss.rsi_slope = _score_rsi_slope(f["daily_rsi_slope_3d"])

            # ── Compute weighted composite with R:R weighting ──
            ss.compute_composite(term)

            ss.is_valid = True

        except Exception as e:
            ss.error = str(e)
            logger.debug("Scoring failed for %s: %s", ticker, e)

        return ss

    def recommend(
        self,
        term: str = "medium",
        target_date: Optional[str] = None,
        index_tier: Optional[str] = None,
        sector: Optional[str] = None,
        top_n: int = 10,
        min_score: float = MIN_COMPOSITE_SCORE,
        min_risk_reward: float = MIN_RISK_REWARD_RATIO,
        auto_sync_universe: bool = True,
    ) -> Dict[str, Any]:
        """Main recommendation entry point.
        
        Args:
            term: Investment term — "short", "medium", or "long"
            target_date: Optional specific date (YYYY-MM-DD), overrides term
            index_tier: Optional index filter (NIFTY 50, NIFTY 100, etc.)
            sector: Optional sector filter
            top_n: Number of top recommendations to return
            min_score: Minimum composite score threshold
            min_risk_reward: Minimum risk-to-reward ratio threshold (default 1.0 = 1:1)
            auto_sync_universe: Whether to batch-sync stale stocks through today
            
        Returns:
            Dict with ranked recommendations, metadata, and market context
        """
        start_time = datetime.now()

        # Resolve term from target_date if provided
        effective_term = term
        if target_date:
            effective_term = self._resolve_term_from_date(target_date)

        # Get filtered universe
        tier_arg = None if (not index_tier or index_tier.upper() == "ALL") else index_tier
        stocks = universe_mgr.get_stocks(index_tier=tier_arg, sector=sector)

        if not stocks:
            return {
                "status": "error",
                "message": "No stocks found matching the specified filters",
                "term": effective_term,
                "index_tier": index_tier,
                "sector": sector,
                "recommendations": [],
            }

        total_universe = len(stocks)
        logger.info(
            "Recommender scanning %d stocks for term=%s, tier=%s, sector=%s (min R:R=%.2f:1)",
            total_universe, effective_term, index_tier or "ALL", sector or "ALL", min_risk_reward
        )

        # Ensure universe stocks have live up-to-date data through today
        if auto_sync_universe:
            try:
                self._ensure_universe_freshness(stocks)
            except Exception as sync_err:
                logger.warning("Error syncing universe freshness: %s", sync_err)

        # Score all stocks in parallel
        scored: List[StockScore] = []
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SCANS) as executor:
            futures = {
                executor.submit(
                    self._score_single_stock,
                    s["symbol"],
                    s,
                    effective_term,
                ): s["symbol"]
                for s in stocks
            }

            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    ss = future.result(timeout=30)
                    if ss.is_valid and ss.composite_score >= min_score and ss.risk_reward_ratio >= min_risk_reward:
                        scored.append(ss)
                except Exception as e:
                    logger.debug("Failed to score %s: %s", ticker, e)

        # Sort by composite score descending, with higher R:R ratio as decisive quality factor
        scored.sort(key=lambda x: (x.composite_score, x.risk_reward_ratio), reverse=True)

        # Take top N
        top_picks = scored[:top_n]

        # Generate reasoning for top picks
        for i, ss in enumerate(top_picks):
            ss.key_notes = _generate_key_notes(ss, effective_term)
            ss.risk_factors = _generate_risk_factors(ss, effective_term)
            ss.why_recommended = _generate_why_recommended(ss, effective_term, total_universe)

        elapsed = (datetime.now() - start_time).total_seconds()

        # Term metadata
        term_config = TERM_CONFIGS.get(effective_term, TERM_CONFIGS["medium"])

        return {
            "status": "success",
            "term": effective_term,
            "term_label": term_config["label"],
            "term_description": term_config["desc"],
            "target_date": target_date,
            "index_tier": index_tier or "ALL",
            "sector": sector or "ALL",
            "universe_scanned": total_universe,
            "qualified_count": len(scored),
            "top_n": top_n,
            "min_score_threshold": min_score,
            "min_risk_reward": min_risk_reward,
            "elapsed_seconds": round(elapsed, 2),
            "recommendations": [ss.to_dict() for ss in top_picks],
            "scoring_weights": TERM_FACTOR_WEIGHTS.get(effective_term, TERM_FACTOR_WEIGHTS["medium"]),
        }


# Singleton instance
stock_recommender = StockRecommender()
