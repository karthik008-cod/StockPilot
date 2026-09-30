"""Trade Strategy & Capital Horizon Planner for StockPilot.

Provides two distinct trade execution modes:
  Mode A: Full Technical Trade (Hold until target price or stop-loss exit)
  Mode B: Deadline-Constrained Trade (Hold until fixed deadline date for borrowed capital repayment)
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FullTradePlan:
    """Strategy A: Target-Driven Trade Plan (No deadline constraint)."""
    mode: str = "full_trade"
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
    exit_rule: str = "Hold position until Target Price or Stop-Loss is reached. No calendar deadline."
    strategy_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeadlineTradePlan:
    """Strategy B: Deadline-Constrained Trade Plan (For borrowed capital / fixed repayment date)."""
    mode: str = "deadline_constrained"
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
    urgency_rating: str = "Normal"
    feasibility_status: str = "Feasible"
    mandatory_exit_rule: str = "Position MUST be liquidated on or before deadline date to return borrowed funds."
    strategy_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TradePlanner:
    """Calculates trade parameters for both Full Technical and Deadline-Constrained modes."""

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

    def plan_full_trade(self, df: pd.DataFrame, ticker: str = "TICKER") -> FullTradePlan:
        """Calculates full technical trade setup (Option A: Hold until target or stop-loss)."""
        valid_df = df.dropna(subset=["Close", "High", "Low"])
        if valid_df.empty or len(valid_df) < 10:
            raise ValueError(f"Insufficient price history for {ticker}")

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

        # Stop Loss: max of (CMP - 1.5 * ATR) and (recent swing low - 0.2 * ATR)
        sl_raw = min(cmp - 1.5 * atr, recent_low - 0.2 * atr)
        sl = max(cmp * 0.92, min(cmp * 0.985, sl_raw))
        sl = round(sl, 2)
        sl_pct = round(((sl - cmp) / cmp) * 100.0, 2)

        # Target 1: Conservative 2.0 * ATR
        t1 = round(max(cmp * 1.03, cmp + 2.0 * atr), 2)
        t1_pct = round(((t1 - cmp) / cmp) * 100.0, 2)

        # Target 2: Extended 3.5 * ATR (or swing breakout)
        t2 = round(max(t1 * 1.03, cmp + 3.5 * atr), 2)
        t2_pct = round(((t2 - cmp) / cmp) * 100.0, 2)

        # Risk-to-Reward Ratio (against Target 1)
        risk = max(cmp - sl, 0.01)
        reward = max(t1 - cmp, 0.01)
        rr_ratio = round(reward / risk, 2)

        # Estimated holding period based on ATR movement speed
        daily_progress = max(0.35 * atr, 0.005 * cmp)
        ratio_val = reward / daily_progress
        if np.isnan(ratio_val) or np.isinf(ratio_val):
            expected_days = 15
        else:
            expected_days = int(np.clip(np.ceil(ratio_val), 5, 45))


        summary = (
            f"Technical target-driven trade for {ticker}. Enter between ₹{entry_min} - ₹{entry_max}. "
            f"Target 1 at ₹{t1} (+{t1_pct}%), Target 2 at ₹{t2} (+{t2_pct}%), with Stop-Loss at ₹{sl} ({sl_pct}%). "
            f"Risk/Reward: 1:{rr_ratio}. Estimated technical completion window: {expected_days} trading days. "
            f"Hold position until either target or stop-loss triggers."
        )

        return FullTradePlan(
            mode="full_trade",
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
            exit_rule="Hold position strictly until Target Price or Stop-Loss is reached. No artificial time exit.",
            strategy_summary=summary,
        )

    def plan_deadline_trade(
        self,
        df: pd.DataFrame,
        ticker: str = "TICKER",
        deadline_date: Optional[str] = None,
        capital: float = 100000.0,
        annual_interest_rate: float = 10.0,
    ) -> DeadlineTradePlan:
        """Calculates deadline-constrained trade setup (Option B: Must exit and return borrowed capital by date)."""
        valid_df = df.dropna(subset=["Close", "High", "Low"])
        if valid_df.empty or len(valid_df) < 10:
            raise ValueError(f"Insufficient price history for {ticker}")

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

        summary = (
            f"Deadline-constrained trade for {ticker}. Capital repayment deadline: {target_dt.strftime('%d-%b-%Y')} "
            f"({calendar_days} calendar days / ~{trading_days} trading days remaining). "
            f"Time-adjusted Target: ₹{time_target} (+{target_pct}%), Tightened Capital-Protection SL: ₹{tight_sl} ({sl_pct}%). "
            f"On ₹{capital:,.0f} borrowed capital @ {rate}% p.a., financing cost is ₹{accrued_cost:,.2f}. "
            f"Expected Net Profit after returning borrowed funds: ₹{net_pnl:,.2f} (+{net_roi}% net ROI). "
            f"Mandatory rule: Liquidate position on or before {target_dt.strftime('%d-%b-%Y')} at market price."
        )

        return DeadlineTradePlan(
            mode="deadline_constrained",
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
            urgency_rating=urgency,
            feasibility_status=feasibility,
            mandatory_exit_rule=f"Position MUST be exited on or before {target_dt.strftime('%d-%b-%Y')} to repay borrowed funds.",
            strategy_summary=summary,
        )

    def generate_both_options(
        self,
        df: pd.DataFrame,
        ticker: str = "TICKER",
        deadline_date: Optional[str] = None,
        capital: float = 100000.0,
        annual_interest_rate: float = 10.0,
    ) -> Dict[str, Any]:
        """Generates comprehensive trade setup containing both Option A and Option B."""
        full_plan = self.plan_full_trade(df, ticker=ticker)
        deadline_plan = self.plan_deadline_trade(
            df,
            ticker=ticker,
            deadline_date=deadline_date,
            capital=capital,
            annual_interest_rate=annual_interest_rate,
        )

        return {
            "ticker": ticker,
            "current_market_price": full_plan.entry_price,
            "option_a_full_trade": full_plan.to_dict(),
            "option_b_deadline": deadline_plan.to_dict(),
        }
