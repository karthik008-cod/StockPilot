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
        "atr_target_mult": 1.5,     # Conservative T1 multiplier
        "atr_target2_mult": 2.5,    # Extended T2 multiplier
        "atr_sl_mult": 1.2,         # Tighter stop
        "min_days": 2,
        "max_days": 15,
        "sl_max_pct": 0.03,         # Max 3% SL
        "desc": "Quick momentum capture, 2-15 trading days",
    },
    "medium": {
        "label": "Medium-Term",
        "atr_target_mult": 2.0,
        "atr_target2_mult": 3.5,
        "atr_sl_mult": 1.5,
        "min_days": 5,
        "max_days": 45,
        "sl_max_pct": 0.05,         # Max 5% SL
        "desc": "Swing trade setup, 5-45 trading days",
    },
    "long": {
        "label": "Long-Term",
        "atr_target_mult": 3.0,
        "atr_target2_mult": 5.0,
        "atr_sl_mult": 2.0,
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
    ) -> FullTradePlan:
        """Calculates full technical trade setup (Option A: Hold until target or stop-loss).

        Args:
            trade_term: "short" (2-15d), "medium" (5-45d), or "long" (20-180d)
            trading_type: "swing", "positional", "investing", "intraday", "futures", "options"
            available_capital: Total capital the user has available for this trade
            max_acceptable_loss: Maximum rupee amount the user is willing to lose
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

        # Recent 20-day swing support and resistance
        recent_20 = clean_df.tail(20)
        recent_high = float(recent_20["High"].max())
        recent_low = float(recent_20["Low"].min())

        # Entry Zone (within +/- 0.5% of CMP or slight pullback)
        entry_min = round(cmp * 0.995, 2)
        entry_max = round(cmp * 1.005, 2)

        # ─── Term-Adjusted Stop Loss ─────────────────────────────────────────
        sl_raw = min(cmp - tc["atr_sl_mult"] * atr, recent_low - 0.2 * atr)
        sl_floor = cmp * (1.0 - tc["sl_max_pct"])
        sl = max(sl_floor, min(cmp * 0.985, sl_raw))
        sl = round(sl, 2)
        sl_pct = round(((sl - cmp) / cmp) * 100.0, 2)

        # ─── Term-Adjusted Targets ───────────────────────────────────────────
        t1_min_pct = {"short": 1.02, "medium": 1.03, "long": 1.05}
        t1 = round(max(cmp * t1_min_pct.get(trade_term, 1.03), cmp + tc["atr_target_mult"] * atr), 2)
        t1_pct = round(((t1 - cmp) / cmp) * 100.0, 2)

        t2 = round(max(t1 * 1.03, cmp + tc["atr_target2_mult"] * atr), 2)
        t2_pct = round(((t2 - cmp) / cmp) * 100.0, 2)

        # Risk-to-Reward Ratio (against Target 1)
        risk = max(cmp - sl, 0.01)
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
