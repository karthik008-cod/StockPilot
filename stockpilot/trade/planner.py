"""Trade Strategy & Capital Horizon Planner for StockPilot.

Provides two distinct trade execution modes:
  Mode A: Full Technical Trade (Hold until target price or stop-loss exit)
  Mode B: Deadline-Constrained Trade (Hold until fixed deadline date for borrowed capital repayment)

Supports position sizing based on available capital and maximum acceptable loss,
trade term selection (short/medium/long), and trading type classification.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Trading Type Definitions ────────────────────────────────────────────────
# Which types are supportable from Yahoo Finance OHLCV equity data
VALID_TRADING_TYPES = [
    "swing",          # 2-30 day holds, technical breakouts
    "positional",     # 1-6 month holds, trend following
    "investing",      # 6+ month holds, fundamental + technical
    "intraday",       # Same-day close (limited: we compute levels, user executes)
    "futures",        # F&O segment (entry/SL/target applicable; margin-based sizing)
    "options",        # Options (limited: we provide directional view + strike guidance)
]

# ─── Trade Term Definitions ──────────────────────────────────────────────────
TERM_CONFIGS = {
    "short": {
        "label": "Short-Term",
        "atr_target_mult": 1.8,     # High R:R target (~1.5:1)
        "atr_target2_mult": 3.0,    # Extended T2 runner (~2.5:1)
        "atr_sl_mult": 1.2,         # Disciplined stop
        "min_days": 2,
        "max_days": 15,
        "sl_max_pct": 0.03,         # Max 3% SL
        "desc": "Quick momentum capture, 2-15 trading days",
    },
    "medium": {
        "label": "Medium-Term",
        "atr_target_mult": 2.5,     # High R:R target (~1.7:1)
        "atr_target2_mult": 4.2,    # Extended T2 runner (~2.8:1)
        "atr_sl_mult": 1.5,
        "min_days": 5,
        "max_days": 45,
        "sl_max_pct": 0.05,         # Max 5% SL
        "desc": "Swing trade setup, 5-45 trading days",
    },
    "long": {
        "label": "Long-Term",
        "atr_target_mult": 3.6,     # High R:R target (~2.0:1)
        "atr_target2_mult": 6.0,    # Extended T2 runner (~3.3:1)
        "atr_sl_mult": 1.8,
        "min_days": 20,
        "max_days": 180,
        "sl_max_pct": 0.08,         # Max 8% SL
        "desc": "Positional / investment horizon, 20-180 trading days",
    },
}


@dataclass
class PositionSizing:
    """Position sizing computed from available capital and max acceptable loss."""
    available_capital: float = 0.0
    max_acceptable_loss: float = 0.0
    risk_per_share: float = 0.0
    position_size_shares: int = 0
    capital_required: float = 0.0
    capital_utilization_pct: float = 0.0
    max_loss_actual: float = 0.0
    potential_profit_t1: float = 0.0
    potential_profit_t2: float = 0.0
    shares_affordable: int = 0
    is_affordable: bool = True
    sizing_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FullTradePlan:
    """Strategy A: Target-Driven Trade Plan (No deadline constraint)."""
    mode: str = "full_trade"
    trade_term: str = "medium"
    trade_term_label: str = "Medium-Term"
    trading_type: str = "swing"
    entry_price: float = 0.0
    entry_zone_min: float = 0.0
    entry_zone_max: float = 0.0
    target_1: float = 0.0
    target_1_pct: float = 0.0
    target_2: float = 0.0
    target_2_pct: float = 0.0
    stop_loss: float = 0.0
    stop_loss_pct: float = 0.0
    risk_reward_ratio: float = 0.0
    expected_holding_days: int = 0
    atr_14: float = 0.0
    trend: str = "Neutral"
    position_sizing: dict = field(default_factory=dict)
    support_1: dict = field(default_factory=dict)
    support_2: dict = field(default_factory=dict)
    resistance_1: dict = field(default_factory=dict)
    resistance_2: dict = field(default_factory=dict)
    market_regime: dict = field(default_factory=dict)
    technical_reasoning: str = ""
    exit_rule: str = "Hold position until Target Price or Stop-Loss is reached. No calendar deadline."
    strategy_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeadlineTradePlan:
    """Strategy B: Deadline-Constrained Trade Plan (For borrowed capital / fixed repayment date)."""
    mode: str = "deadline_constrained"
    trading_type: str = "swing"
    entry_price: float = 0.0
    entry_zone_min: float = 0.0
    entry_zone_max: float = 0.0
    deadline_date: str = ""
    calendar_days_remaining: int = 0
    trading_days_remaining: int = 0
    time_constrained_target: float = 0.0
    target_pct: float = 0.0
    tightened_stop_loss: float = 0.0
    stop_loss_pct: float = 0.0
    risk_reward_ratio: float = 0.0
    borrowed_capital: float = 100000.0
    annual_interest_rate: float = 10.0
    accrued_borrowing_cost: float = 0.0
    gross_projected_pnl: float = 0.0
    net_projected_pnl: float = 0.0
    net_roi_pct: float = 0.0
    position_sizing: dict = field(default_factory=dict)
    urgency_rating: str = "Normal"
    feasibility_status: str = "Feasible"
    mandatory_exit_rule: str = "Position MUST be liquidated on or before deadline date to return borrowed funds."
    strategy_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TradePlanner:
    """Calculates trade parameters for both Full Technical and Deadline-Constrained modes.

    Now includes:
      - Trade term (short / medium / long) for Option A
      - Trading type (swing / positional / investing / intraday / futures / options)
      - Position sizing from available capital and max acceptable loss
    """

    def __init__(self, atr_window: int = 14):
        self.atr_window = atr_window

    def _calc_atr(self, df: pd.DataFrame) -> float:
        """Calculates Average True Range (ATR) from recent daily prices."""
        valid_df = df.dropna(subset=["Close", "High", "Low"])
        if len(valid_df) < self.atr_window + 1:
            return float(valid_df["Close"].iloc[-1]) * 0.02 if not valid_df.empty else 1.0

        high = valid_df["High"]
        low = valid_df["Low"]
        close_prev = valid_df["Close"].shift(1)

        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr_series = tr.rolling(window=self.atr_window).mean()
        val = atr_series.dropna().iloc[-1] if not atr_series.dropna().empty else float(valid_df["Close"].iloc[-1]) * 0.02
        return max(float(val), float(valid_df["Close"].iloc[-1]) * 0.005)

    def _calc_trend(self, df: pd.DataFrame) -> str:
        """Determines market trend based on moving averages."""
        valid_df = df.dropna(subset=["Close"])
        if len(valid_df) < 50:
            return "Consolidation"
        close = valid_df["Close"]
        sma20_s = close.rolling(20).mean().dropna()
        sma50_s = close.rolling(50).mean().dropna()
        if sma20_s.empty or sma50_s.empty:
            return "Consolidation"

        sma20 = float(sma20_s.iloc[-1])
        sma50 = float(sma50_s.iloc[-1])
        curr = float(close.iloc[-1])

        if curr > sma20 > sma50:
            return "Strong Bullish"
        elif curr > sma20:
            return "Mild Bullish"
        elif curr < sma20 < sma50:
            return "Strong Bearish"
        elif curr < sma20:
            return "Mild Bearish"
        return "Consolidation"

    def _detect_support_resistance(
        self,
        df: pd.DataFrame,
        cmp: float,
        atr: float,
        trade_term: str = "medium",
    ) -> Dict[str, Any]:
        """Detects key chart support and resistance levels from price action.
        
        Uses:
          - Multi-bar swing pivot highs and lows tailored to the chosen term lookback
          - 20-day, 50-day, and 200-day Exponential Moving Averages (EMA)
          - 52-week highs and multi-week consolidation boundaries
          - Fibonacci projections (1.272 / 1.618) for all-time-high breakouts
        """
        valid_df = df.dropna(subset=["Close", "High", "Low"]).sort_values("Date").reset_index(drop=True)
        n = len(valid_df)

        lookback = 40 if trade_term == "short" else (100 if trade_term == "medium" else 250)
        lookback = min(lookback, n)
        sub_df = valid_df.tail(lookback).reset_index(drop=True)
        m = len(sub_df)

        pivot_w = 3 if trade_term == "short" else (5 if trade_term == "medium" else 8)
        highs = sub_df["High"].values
        lows = sub_df["Low"].values

        pivot_highs: List[float] = []
        pivot_lows: List[float] = []

        for i in range(pivot_w, m - pivot_w):
            if all(highs[i] >= highs[i - k] for k in range(1, pivot_w + 1)) and \
               all(highs[i] >= highs[i + k] for k in range(1, pivot_w + 1)):
                pivot_highs.append(float(highs[i]))

            if all(lows[i] <= lows[i - k] for k in range(1, pivot_w + 1)) and \
               all(lows[i] <= lows[i + k] for k in range(1, pivot_w + 1)):
                pivot_lows.append(float(lows[i]))

        if m >= 20:
            pivot_highs.append(float(highs[-20:].max()))
            pivot_lows.append(float(lows[-20:].min()))

        if n >= 150:
            pivot_highs.append(float(valid_df["High"].tail(250).max()))

        # Moving average levels
        close_s = valid_df["Close"]
        ema_20 = float(close_s.ewm(span=20).mean().iloc[-1])
        ema_50 = float(close_s.ewm(span=50).mean().iloc[-1]) if n >= 50 else ema_20
        ema_200 = float(close_s.ewm(span=200).mean().iloc[-1]) if n >= 150 else None

        # Supports (< CMP)
        supp_candidates = []
        for pl in pivot_lows:
            if pl < cmp * 0.998:
                supp_candidates.append((pl, "Swing Low Support"))

        if ema_20 < cmp * 0.995:
            supp_candidates.append((ema_20, "20 EMA Dynamic Support"))
        if ema_50 < cmp * 0.995:
            supp_candidates.append((ema_50, "50 EMA Trend Support"))
        if ema_200 and ema_200 < cmp * 0.995:
            supp_candidates.append((ema_200, "200 EMA Institutional Floor"))

        supp_candidates.sort(key=lambda x: x[0], reverse=True)
        clustered_supp = []
        for price, label in supp_candidates:
            if not clustered_supp:
                clustered_supp.append((price, label))
            elif abs(price - clustered_supp[-1][0]) / max(clustered_supp[-1][0], 1.0) > 0.012:
                clustered_supp.append((price, label))

        s1_price = clustered_supp[0][0] if len(clustered_supp) >= 1 else cmp - 1.2 * atr
        s1_type = clustered_supp[0][1] if len(clustered_supp) >= 1 else "ATR Volatility Support"

        s2_price = clustered_supp[1][0] if len(clustered_supp) >= 2 else (s1_price - 1.5 * atr)
        s2_type = clustered_supp[1][1] if len(clustered_supp) >= 2 else "Secondary Structural Floor"

        # Resistances (> CMP)
        res_candidates = []
        for ph in pivot_highs:
            if ph > cmp * 1.002:
                res_candidates.append((ph, "Swing High Resistance"))

        if ema_20 > cmp * 1.005:
            res_candidates.append((ema_20, "20 EMA Overhead Resistance"))
        if ema_50 > cmp * 1.005:
            res_candidates.append((ema_50, "50 EMA Overhead Resistance"))
        if ema_200 and ema_200 > cmp * 1.005:
            res_candidates.append((ema_200, "200 EMA Institutional Barrier"))

        res_candidates.sort(key=lambda x: x[0])
        clustered_res = []
        for price, label in res_candidates:
            if not clustered_res:
                clustered_res.append((price, label))
            elif abs(price - clustered_res[-1][0]) / max(clustered_res[-1][0], 1.0) > 0.012:
                clustered_res.append((price, label))

        is_breakout = len(clustered_res) == 0 or (clustered_res[0][0] <= cmp * 1.008)
        swing_depth = max(cmp - s1_price, 1.5 * atr)

        if is_breakout or len(clustered_res) == 0:
            r1_price = cmp + 1.272 * swing_depth
            r1_type = "Fibonacci 1.272 Breakout Target"
            r2_price = cmp + 1.618 * swing_depth
            r2_type = "Fibonacci 1.618 Extension Target"
        elif len(clustered_res) == 1:
            r1_price = clustered_res[0][0]
            r1_type = clustered_res[0][1]
            r2_price = max(r1_price + 1.2 * atr, cmp + 1.618 * swing_depth)
            r2_type = "Fibonacci 1.618 Extension Target"
        else:
            r1_price = clustered_res[0][0]
            r1_type = clustered_res[0][1]
            r2_price = clustered_res[1][0]
            r2_type = clustered_res[1][1]

        return {
            "support_1": {
                "price": round(s1_price, 2),
                "type": s1_type,
                "distance_pct": round(((s1_price - cmp) / cmp) * 100.0, 2),
            },
            "support_2": {
                "price": round(s2_price, 2),
                "type": s2_type,
                "distance_pct": round(((s2_price - cmp) / cmp) * 100.0, 2),
            },
            "resistance_1": {
                "price": round(r1_price, 2),
                "type": r1_type,
                "distance_pct": round(((r1_price - cmp) / cmp) * 100.0, 2),
            },
            "resistance_2": {
                "price": round(r2_price, 2),
                "type": r2_type,
                "distance_pct": round(((r2_price - cmp) / cmp) * 100.0, 2),
            },
            "is_breakout": is_breakout,
        }

    @staticmethod
    def compute_position_sizing(
        entry_price: float,
        stop_loss: float,
        target_1: float,
        target_2: float,
        available_capital: float,
        max_acceptable_loss: float,
    ) -> PositionSizing:
        """Calculates optimal position size from risk management constraints.

        Position Size = Max Acceptable Loss / Risk Per Share
        where Risk Per Share = Entry Price - Stop Loss

        Ensures capital_required does not exceed available_capital.
        """
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share < 0.01:
            risk_per_share = entry_price * 0.02  # Fallback 2% risk

        # Max shares from risk tolerance
        risk_shares = int(max_acceptable_loss / risk_per_share) if max_acceptable_loss > 0 else 0

        # Max shares affordable
        affordable = int(available_capital / entry_price) if entry_price > 0 else 0

        # Effective position = min of risk-based and affordability
        position_size = min(risk_shares, affordable) if (risk_shares > 0 and affordable > 0) else max(risk_shares, affordable)
        position_size = max(0, position_size)

        capital_req = round(position_size * entry_price, 2)
        cap_util = round((capital_req / available_capital) * 100, 2) if available_capital > 0 else 0.0
        actual_max_loss = round(position_size * risk_per_share, 2)
        profit_t1 = round(position_size * max(target_1 - entry_price, 0), 2)
        profit_t2 = round(position_size * max(target_2 - entry_price, 0), 2)

        is_affordable = capital_req <= available_capital

        if position_size == 0:
            note = "Position size is 0. Either capital is too low or max loss tolerance is too tight for this stock's price."
        elif not is_affordable:
            note = f"Capital required ({capital_req:,.0f}) exceeds available capital ({available_capital:,.0f}). Reduce position or increase capital."
        elif cap_util > 80:
            note = f"High capital utilization ({cap_util:.1f}%). Consider diversifying across multiple positions."
        elif cap_util < 20:
            note = f"Low utilization ({cap_util:.1f}%). You may increase position size within risk limits."
        else:
            note = f"Position utilizes {cap_util:.1f}% of available capital. Within prudent allocation bounds."

        return PositionSizing(
            available_capital=available_capital,
            max_acceptable_loss=max_acceptable_loss,
            risk_per_share=round(risk_per_share, 2),
            position_size_shares=position_size,
            capital_required=capital_req,
            capital_utilization_pct=cap_util,
            max_loss_actual=actual_max_loss,
            potential_profit_t1=profit_t1,
            potential_profit_t2=profit_t2,
            shares_affordable=affordable,
            is_affordable=is_affordable,
            sizing_note=note,
        )

    def plan_full_trade(
        self,
        df: pd.DataFrame,
        ticker: str = "TICKER",
        trade_term: str = "medium",
        trading_type: str = "swing",
        available_capital: float = 100000.0,
        max_acceptable_loss: float = 2000.0,
        market_regime: Optional[Dict[str, Any]] = None,
    ) -> FullTradePlan:
        """Calculates full technical trade setup anchored to chart supports, resistances, and market trend.

        Args:
            trade_term: "short" (2-15d), "medium" (5-45d), or "long" (20-180d)
            trading_type: "swing", "positional", "investing", "intraday", "futures", "options"
            available_capital: Total capital the user has available for this trade
            max_acceptable_loss: Maximum rupee amount the user is willing to lose
            market_regime: Optional dictionary of NIFTY trend and INDIA VIX volatility context
        """
        valid_df = df.dropna(subset=["Close", "High", "Low"])
        if valid_df.empty or len(valid_df) < 10:
            raise ValueError(f"Insufficient price history for {ticker}")

        # Validate trade_term
        if trade_term not in TERM_CONFIGS:
            trade_term = "medium"
        tc = TERM_CONFIGS[trade_term]

        # Validate trading_type
        if trading_type not in VALID_TRADING_TYPES:
            trading_type = "swing"

        clean_df = valid_df.sort_values("Date").reset_index(drop=True)
        cmp = float(clean_df["Close"].iloc[-1])
        atr = self._calc_atr(clean_df)
        trend = self._calc_trend(clean_df)

        # ─── Detect Chart Support & Resistance Levels ────────────────────────
        sr = self._detect_support_resistance(clean_df, cmp, atr, trade_term)
        s1 = sr["support_1"]["price"]
        s2 = sr["support_2"]["price"]
        r1 = sr["resistance_1"]["price"]
        r2 = sr["resistance_2"]["price"]

        # Entry Zone (within +/- 0.5% of CMP or slight pullback to support)
        entry_min = round(max(cmp * 0.995, min(cmp, s1)), 2) if s1 < cmp else round(cmp * 0.995, 2)
        entry_max = round(cmp * 1.005, 2)

        # ─── Stop-Loss Anchored to Technical Support S1 ──────────────────────
        # Place SL with breathing buffer below support so normal wicks don't trigger it
        sl_from_support = round(s1 - 0.25 * atr, 2)
        sl_floor = cmp * (1.0 - tc["sl_max_pct"])

        # If S1 is within term risk limit, use S1 anchor; otherwise limit to max term loss
        if sl_from_support >= sl_floor:
            sl = min(round(cmp * 0.99, 2), sl_from_support)
        else:
            sl = sl_floor

        # Adjust for market volatility (INDIA VIX)
        if market_regime:
            vix = market_regime.get("vix_level", 14.0)
            if vix > 18.0:
                # Elevated volatility: expand buffer slightly to avoid noise whipsaw
                sl = min(sl, round(cmp - 1.2 * atr, 2))

        sl = round(sl, 2)
        sl_pct = round(((sl - cmp) / cmp) * 100.0, 2)
        risk = max(cmp - sl, 0.01)

        # ─── Target 1 Anchored to Chart Resistance R1 ────────────────────────
        # Primary target is at or slightly before overhead resistance R1
        t1_cand = round(r1 * 0.998, 2)

        # Enforce minimum 1:1 Risk-to-Reward discipline (Reward >= Risk)
        # If R1 is too close to CMP (Reward < Risk), setup requires breakout past R1 targeting R2
        if (t1_cand - cmp) < risk:
            t1 = round(max(cmp + risk, r2 * 0.995), 2)
        else:
            t1 = max(t1_cand, round(cmp + risk, 2))

        t1 = round(t1, 2)
        t1_pct = round(((t1 - cmp) / cmp) * 100.0, 2)

        # ─── Target 2 Anchored to Extended Resistance R2 / Runner ────────────
        t2 = round(max(t1 * 1.025, r2, cmp + tc["atr_target2_mult"] * atr), 2)
        t2_pct = round(((t2 - cmp) / cmp) * 100.0, 2)

        reward = max(t1 - cmp, 0.01)
        rr_ratio = round(reward / risk, 2)

        # ─── Term-Adjusted Holding Period ────────────────────────────────────
        daily_progress = max(0.35 * atr, 0.005 * cmp)
        ratio_val = reward / daily_progress
        if np.isnan(ratio_val) or np.isinf(ratio_val):
            expected_days = (tc["min_days"] + tc["max_days"]) // 2
        else:
            expected_days = int(np.clip(np.ceil(ratio_val), tc["min_days"], tc["max_days"]))

        # ─── Position Sizing ─────────────────────────────────────────────────
        sizing = self.compute_position_sizing(
            entry_price=cmp,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            available_capital=available_capital,
            max_acceptable_loss=max_acceptable_loss,
        )

        tech_reasoning = (
            f"Trade setup anchored to chart support at INR {s1} ({sr['support_1']['type']}) "
            f"with stop-loss positioned below at INR {sl} ({sl_pct}%). "
            f"Target 1 at INR {t1} (+{t1_pct}%) aligned with chart resistance at INR {r1} ({sr['resistance_1']['type']}), "
            f"yielding an asymmetric 1:{rr_ratio:.2f} risk-to-reward ratio. "
            f"Target 2 at INR {t2} (+{t2_pct}%) targets extended structural zone at INR {r2} ({sr['resistance_2']['type']})."
        )

        summary = (
            f"{tc['label']} {trading_type.title()} trade for {ticker}. "
            f"Enter between INR {entry_min} - INR {entry_max}. "
            f"Target 1 at INR {t1} (+{t1_pct}%), Target 2 at INR {t2} (+{t2_pct}%), "
            f"with Stop-Loss at INR {sl} ({sl_pct}%). "
            f"Risk/Reward: 1:{rr_ratio}. Position: {sizing.position_size_shares} shares "
            f"(Capital: INR {sizing.capital_required:,.0f}, Max Loss: INR {sizing.max_loss_actual:,.0f}). "
            f"Estimated {tc['label'].lower()} completion: {expected_days} trading days. "
            f"Hold position until either target or stop-loss triggers."
        )

        return FullTradePlan(
            mode="full_trade",
            trade_term=trade_term,
            trade_term_label=tc["label"],
            trading_type=trading_type,
            entry_price=round(cmp, 2),
            entry_zone_min=entry_min,
            entry_zone_max=entry_max,
            target_1=t1,
            target_1_pct=t1_pct,
            target_2=t2,
            target_2_pct=t2_pct,
            stop_loss=sl,
            stop_loss_pct=sl_pct,
            risk_reward_ratio=rr_ratio,
            expected_holding_days=expected_days,
            atr_14=round(atr, 2),
            trend=trend,
            position_sizing=sizing.to_dict(),
            support_1=sr["support_1"],
            support_2=sr["support_2"],
            resistance_1=sr["resistance_1"],
            resistance_2=sr["resistance_2"],
            market_regime=market_regime or {},
            technical_reasoning=tech_reasoning,
            exit_rule=f"Hold position strictly until Target Price or Stop-Loss is reached. No artificial time exit. ({tc['label']} {trading_type.title()} mode).",
            strategy_summary=summary,
        )

    def plan_deadline_trade(
        self,
        df: pd.DataFrame,
        ticker: str = "TICKER",
        deadline_date: Optional[str] = None,
        capital: float = 100000.0,
        annual_interest_rate: float = 10.0,
        trading_type: str = "swing",
        available_capital: float = 100000.0,
        max_acceptable_loss: float = 2000.0,
    ) -> DeadlineTradePlan:
        """Calculates deadline-constrained trade setup (Option B: Must exit and return borrowed capital by date)."""
        valid_df = df.dropna(subset=["Close", "High", "Low"])
        if valid_df.empty or len(valid_df) < 10:
            raise ValueError(f"Insufficient price history for {ticker}")

        if trading_type not in VALID_TRADING_TYPES:
            trading_type = "swing"

        clean_df = valid_df.sort_values("Date").reset_index(drop=True)

        cmp = float(clean_df["Close"].iloc[-1])
        atr = self._calc_atr(clean_df)
        today = date.today()

        # Parse deadline date or default to 30 calendar days ahead
        if deadline_date:
            try:
                target_dt = datetime.strptime(deadline_date, "%Y-%m-%d").date()
            except ValueError:
                target_dt = today + timedelta(days=30)
        else:
            target_dt = today + timedelta(days=30)

        # Enforce deadline is in the future
        if target_dt <= today:
            target_dt = today + timedelta(days=7)

        calendar_days = (target_dt - today).days
        # Approximate trading days (~5 trading days per 7 calendar days minus public holidays)
        trading_days = max(1, int(np.round(calendar_days * (5.0 / 7.0))))

        # Entry Zone
        entry_min = round(cmp * 0.995, 2)
        entry_max = round(cmp * 1.005, 2)

        # Realistically achievable price move within trading_days:
        # Move scale follows square-root of time rule: sigma * sqrt(T)
        time_factor = np.sqrt(trading_days)
        max_feasible_gain = (1.2 * atr * time_factor) / cmp

        # Realistic Target within time constraint
        target_pct_raw = max(0.015, min(0.18, max_feasible_gain))
        time_target = round(cmp * (1.0 + target_pct_raw), 2)
        target_pct = round(target_pct_raw * 100.0, 2)

        # Tightened Stop Loss: When trading with borrowed capital, capital preservation is priority #1!
        # Stop-loss is tightened to 1.0 * ATR (or max 4% loss) so debt default risk is minimized
        tight_sl_raw = cmp - 1.0 * atr
        tight_sl = max(cmp * 0.96, min(cmp * 0.985, tight_sl_raw))
        tight_sl = round(tight_sl, 2)
        sl_pct = round(((tight_sl - cmp) / cmp) * 100.0, 2)

        # R:R for the deadline trade
        risk = cmp - tight_sl
        reward = time_target - cmp
        rr_ratio = round(reward / risk, 2) if risk > 0 else 1.5

        # Borrowing / Margin Interest Calculations
        # Cost = Principal * (Rate / 100) * (Calendar Days / 365)
        capital = float(max(1000.0, capital))
        rate = float(max(0.0, annual_interest_rate))
        accrued_cost = round(capital * (rate / 100.0) * (calendar_days / 365.0), 2)

        # Projected PnL if target reached
        gross_pnl = round(capital * (target_pct_raw), 2)
        net_pnl = round(gross_pnl - accrued_cost, 2)
        net_roi = round((net_pnl / capital) * 100.0, 2)

        # Urgency & Feasibility Assessment
        if trading_days < 5:
            urgency = "High Urgency / High Risk"
            feasibility = "Low Feasibility (Insufficient days for setup to mature before capital repayment)"
        elif trading_days < 12:
            urgency = "Moderate Urgency"
            feasibility = "Moderate Feasibility (Requires immediate momentum)"
        else:
            urgency = "Normal"
            feasibility = "High Feasibility (Sufficient time buffer for target delivery before repayment)"

        # ─── Position Sizing for Option B ────────────────────────────────────
        # Use time_target as T1, and a 1.5x stretch as T2 equivalent
        opt_b_t2 = round(cmp + 1.5 * (time_target - cmp), 2)
        sizing = self.compute_position_sizing(
            entry_price=cmp,
            stop_loss=tight_sl,
            target_1=time_target,
            target_2=opt_b_t2,
            available_capital=available_capital,
            max_acceptable_loss=max_acceptable_loss,
        )

        summary = (
            f"Deadline-constrained {trading_type.title()} trade for {ticker}. "
            f"Capital repayment deadline: {target_dt.strftime('%d-%b-%Y')} "
            f"({calendar_days} calendar days / ~{trading_days} trading days remaining). "
            f"Time-adjusted Target: INR {time_target} (+{target_pct}%), "
            f"Tightened Capital-Protection SL: INR {tight_sl} ({sl_pct}%). "
            f"Position: {sizing.position_size_shares} shares "
            f"(Capital: INR {sizing.capital_required:,.0f}, Max Loss: INR {sizing.max_loss_actual:,.0f}). "
            f"On INR {capital:,.0f} borrowed capital @ {rate}% p.a., financing cost is INR {accrued_cost:,.2f}. "
            f"Expected Net Profit after returning borrowed funds: INR {net_pnl:,.2f} (+{net_roi}% net ROI). "
            f"Mandatory rule: Liquidate position on or before {target_dt.strftime('%d-%b-%Y')} at market price."
        )

        return DeadlineTradePlan(
            mode="deadline_constrained",
            trading_type=trading_type,
            entry_price=round(cmp, 2),
            entry_zone_min=entry_min,
            entry_zone_max=entry_max,
            deadline_date=str(target_dt),
            calendar_days_remaining=calendar_days,
            trading_days_remaining=trading_days,
            time_constrained_target=time_target,
            target_pct=target_pct,
            tightened_stop_loss=tight_sl,
            stop_loss_pct=sl_pct,
            risk_reward_ratio=rr_ratio,
            borrowed_capital=capital,
            annual_interest_rate=rate,
            accrued_borrowing_cost=accrued_cost,
            gross_projected_pnl=gross_pnl,
            net_projected_pnl=net_pnl,
            net_roi_pct=net_roi,
            position_sizing=sizing.to_dict(),
            urgency_rating=urgency,
            feasibility_status=feasibility,
            mandatory_exit_rule=f"Position MUST be exited on or before {target_dt.strftime('%d-%b-%Y')} to repay borrowed funds.",
            strategy_summary=summary,
        )

    def generate_both_options(
        self,
        df: pd.DataFrame,
        ticker: str = "TICKER",
        trade_term: str = "medium",
        trading_type: str = "swing",
        available_capital: float = 100000.0,
        max_acceptable_loss: float = 2000.0,
        deadline_date: Optional[str] = None,
        borrowed_capital: float = 100000.0,
        annual_interest_rate: float = 10.0,
    ) -> Dict[str, Any]:
        """Generates comprehensive trade setup containing both Option A and Option B."""
        full_plan = self.plan_full_trade(
            df,
            ticker=ticker,
            trade_term=trade_term,
            trading_type=trading_type,
            available_capital=available_capital,
            max_acceptable_loss=max_acceptable_loss,
        )
        deadline_plan = self.plan_deadline_trade(
            df,
            ticker=ticker,
            deadline_date=deadline_date,
            capital=borrowed_capital,
            annual_interest_rate=annual_interest_rate,
            trading_type=trading_type,
            available_capital=available_capital,
            max_acceptable_loss=max_acceptable_loss,
        )

        return {
            "ticker": ticker,
            "current_market_price": full_plan.entry_price,
            "trading_type": trading_type,
            "trade_term": trade_term,
            "option_a_full_trade": full_plan.to_dict(),
            "option_b_deadline": deadline_plan.to_dict(),
        }
