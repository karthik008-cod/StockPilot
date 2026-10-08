"""Master Strategy Scanner Engine for StockPilot.

Evaluates declarative multi-timeframe strategies across index universes
with zero look-ahead bias and comprehensive audit evidence.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Any, Dict, List, Optional, Union
import pandas as pd

from stockpilot.data.cleaner import DataCleaner
from stockpilot.data.loader import DataLoader
from stockpilot.universe import universe
from stockpilot.trade.planner import TradePlanner
from stockpilot.strategy.models import (
    Condition,
    ConditionEvidence,
    Operator,
    ScanCandidate,
    StrategyDefinition,
    Timeframe,
)
from stockpilot.strategy.registry import STRATEGY_REGISTRY, get_strategy
from stockpilot.strategy.resampler import (
    compute_wilder_rsi,
    extract_multi_timeframe_indicators,
    resample_to_timeframe,
)

logger = logging.getLogger(__name__)


class StrategyScannerEngine:
    """Evaluates declarative technical strategies across equity universes."""

    def __init__(
        self,
        loader: Optional[DataLoader] = None,
        cleaner: Optional[DataCleaner] = None,
        planner: Optional[TradePlanner] = None,
    ):
        self.loader = loader or DataLoader()
        self.cleaner = cleaner or DataCleaner()
        self.planner = planner or TradePlanner()

    @staticmethod
    def _evaluate_condition_value(
        tf_df: pd.DataFrame,
        cond: Condition,
    ) -> tuple[Optional[float], Optional[float]]:
        """Computes current and previous indicator values for any technical indicator."""
        if tf_df.empty or len(tf_df) < 2:
            return None, None

        ind = str(cond.indicator).upper().strip()
        period = max(1, int(cond.period))

        try:
            if ind == "RSI":
                series = compute_wilder_rsi(tf_df["Close"], period=period)
            elif ind == "SMA":
                series = tf_df["Close"].rolling(window=period, min_periods=max(2, period // 2)).mean()
            elif ind == "EMA":
                series = tf_df["Close"].ewm(span=period, adjust=False).mean()
            elif ind in ["CLOSE", "PRICE"]:
                series = tf_df["Close"]
            elif ind == "VOLUME":
                series = tf_df["Volume"].astype(float)
            elif ind == "RVOL":
                vol_sma = tf_df["Volume"].rolling(window=period, min_periods=min(5, len(tf_df))).mean()
                series = tf_df["Volume"] / (vol_sma + 1e-10)
            elif ind in ["ATH_PCT", "52W_HIGH_PCT"]:
                high_window = tf_df["High"].rolling(window=min(len(tf_df), 252), min_periods=min(10, len(tf_df))).max()
                series = (tf_df["Close"] / (high_window + 1e-10)) * 100.0
            elif ind in tf_df.columns:
                series = tf_df[ind].astype(float)
            else:
                series = compute_wilder_rsi(tf_df["Close"], period=period)

            # Compute index with shift
            shift = max(0, int(cond.shift))
            curr_idx = -1 - shift
            prev_idx = curr_idx - 1

            curr_val = float(series.iloc[curr_idx]) if abs(curr_idx) <= len(series) and not pd.isna(series.iloc[curr_idx]) else None
            prev_val = float(series.iloc[prev_idx]) if abs(prev_idx) <= len(series) and not pd.isna(series.iloc[prev_idx]) else None

            return curr_val, prev_val
        except Exception as e:
            logger.warning("Error evaluating condition %s: %s", cond, e)
            return None, None

    def evaluate_dataframe(
        self,
        df: pd.DataFrame,
        strategy: StrategyDefinition,
        symbol: str = "TICKER",
        name: str = "",
        sector: str = "",
        as_of_date: Optional[Union[str, pd.Timestamp]] = None,
        include_trade_setup: bool = True,
    ) -> ScanCandidate:
        """Evaluates a single stock DataFrame against a declarative strategy.
        
        Args:
            df: Clean daily OHLCV DataFrame.
            strategy: StrategyDefinition to evaluate.
            symbol: Stock ticker symbol.
            name: Company name.
            sector: Sector / Industry.
            as_of_date: Historical evaluation cutoff (point-in-time).
            include_trade_setup: If True and candidate passes, calculates trade setup.

        Returns:
            ScanCandidate with full evidence and indicator metrics.
        """
        if df.empty or len(df) < 20:
            return ScanCandidate(
                symbol=symbol,
                company_name=name or symbol,
                sector=sector or "Unknown",
                strategy_id=strategy.strategy_id,
                strategy_name=strategy.name,
                universe=strategy.universe,
                as_of_date=str(as_of_date or "N/A"),
                passed=False,
                indicators={"error": "Insufficient price observations"},
                conditions=[],
            )

        mtf = extract_multi_timeframe_indicators(df, as_of_date=as_of_date, period=14)
        if not mtf.get("valid", False):
            return ScanCandidate(
                symbol=symbol,
                company_name=name or symbol,
                sector=sector or "Unknown",
                strategy_id=strategy.strategy_id,
                strategy_name=strategy.name,
                universe=strategy.universe,
                as_of_date=str(as_of_date or "N/A"),
                passed=False,
                indicators=mtf,
                conditions=[],
            )

        evidence_list: List[ConditionEvidence] = []
        all_passed = True
        resampled_cache: Dict[Timeframe, pd.DataFrame] = {}

        for cond in strategy.conditions:
            val: Optional[float] = None
            prev_val: Optional[float] = None

            # Fast path for standard RSI(14)
            if str(cond.indicator).upper() == "RSI" and int(cond.period) == 14:
                if cond.timeframe == Timeframe.DAILY:
                    val = mtf.get("daily_rsi_14") if cond.shift == 0 else mtf.get("prev_daily_rsi_14")
                    prev_val = mtf.get("prev_daily_rsi_14")
                elif cond.timeframe == Timeframe.WEEKLY:
                    val = mtf.get("weekly_rsi_14") if cond.shift == 0 else mtf.get("prev_weekly_rsi_14")
                    prev_val = mtf.get("prev_weekly_rsi_14")
                elif cond.timeframe == Timeframe.MONTHLY:
                    val = mtf.get("monthly_rsi_14") if cond.shift == 0 else mtf.get("prev_monthly_rsi_14")
                    prev_val = mtf.get("prev_monthly_rsi_14")
            else:
                # Dynamic indicator evaluation on resampled timeframe candle series
                if cond.timeframe not in resampled_cache:
                    resampled_cache[cond.timeframe] = resample_to_timeframe(df, cond.timeframe, as_of_date=as_of_date)
                val, prev_val = self._evaluate_condition_value(resampled_cache[cond.timeframe], cond)

            passed, detail = cond.evaluate(val, prev_val)
            if not passed:
                all_passed = False

            evidence_list.append(
                ConditionEvidence(
                    condition_desc=cond.description or f"{cond.timeframe.value} {cond.indicator}({cond.period}) {cond.operator.value} {cond.value}",
                    timeframe=cond.timeframe.value,
                    indicator=cond.indicator,
                    operator=cond.operator.value,
                    threshold=cond.value,
                    threshold_high=cond.value_high,
                    actual_value=float(val) if val is not None else 0.0,
                    previous_value=float(prev_val) if prev_val is not None else None,
                    passed=passed,
                    detail=detail,
                )
            )

        # Optional trade planning calculation if candidate passed
        trade_levels = None
        if all_passed and include_trade_setup:
            try:
                # Use clean dataframe up to as_of_date
                clean_slice = df.copy()
                if as_of_date:
                    clean_slice = clean_slice[clean_slice["Date"] <= pd.to_datetime(as_of_date)]
                plan = self.planner.plan_full_trade(clean_slice, ticker=symbol, trade_term="medium")
                trade_levels = {
                    "entry_price": plan.entry_price,
                    "entry_zone": f"₹{plan.entry_zone_min} - ₹{plan.entry_zone_max}",
                    "stop_loss": plan.stop_loss,
                    "stop_loss_pct": plan.stop_loss_pct,
                    "target_1": plan.target_1,
                    "target_1_pct": plan.target_1_pct,
                    "target_2": plan.target_2,
                    "target_2_pct": plan.target_2_pct,
                    "risk_reward_ratio": plan.risk_reward_ratio,
                    "expected_holding_days": plan.expected_holding_days,
                    "trend": plan.trend,
                }
            except Exception as e:
                logger.debug("Could not compute trade setup for %s: %s", symbol, e)

        eval_date = mtf.get("as_of_date") or str(as_of_date or "Latest")

        return ScanCandidate(
            symbol=symbol,
            company_name=name or symbol,
            sector=sector or "Unknown",
            strategy_id=strategy.strategy_id,
            strategy_name=strategy.name,
            universe=strategy.universe,
            as_of_date=eval_date,
            passed=all_passed,
            indicators=mtf,
            conditions=evidence_list,
            trade_levels=trade_levels,
        )

    def scan_stock(
        self,
        ticker: str,
        strategy_or_id: Union[str, StrategyDefinition],
        as_of_date: Optional[Union[str, pd.Timestamp]] = None,
    ) -> Optional[ScanCandidate]:
        """Loads and evaluates a specific stock ticker against a strategy."""
        strat = strategy_or_id if isinstance(strategy_or_id, StrategyDefinition) else get_strategy(strategy_or_id)
        if not strat:
            raise ValueError(f"Unknown strategy ID: {strategy_or_id}")

        meta = universe.get_stock(ticker) or {"symbol": ticker, "name": ticker, "sector": "Market"}

        try:
            raw_df = self.loader.load_ohlcv(ticker, period="max")
            if raw_df.empty:
                return None
            clean_df = self.cleaner.clean_ohlcv(raw_df, ticker_name=ticker)
            return self.evaluate_dataframe(
                clean_df,
                strategy=strat,
                symbol=ticker,
                name=meta.get("name", ticker),
                sector=meta.get("sector", "Market"),
                as_of_date=as_of_date,
            )
        except Exception as e:
            logger.error("Error evaluating stock %s on strategy %s: %s", ticker, strat.strategy_id, e)
            return None

    def scan_universe(
        self,
        strategy_or_id: Union[str, StrategyDefinition],
        universe_override: Optional[str] = None,
        as_of_date: Optional[Union[str, pd.Timestamp]] = None,
        max_stocks: Optional[int] = None,
        max_workers: int = 8,
    ) -> List[ScanCandidate]:
        """Scans the universe specified by the strategy and returns matching candidates.
        
        Args:
            strategy_or_id: StrategyDefinition or ID.
            universe_override: Optional universe tier (e.g. "NIFTY 50", "NIFTY 100", "NIFTY 200", "NIFTY 500").
            as_of_date: Point-in-time evaluation cutoff.
            max_stocks: Optional cap for testing or quick scans.
            max_workers: Worker threads for fast parallel scanning of cached data.

        Returns:
            List of ScanCandidate objects that PASSED all conditions.
        """
        strat = strategy_or_id if isinstance(strategy_or_id, StrategyDefinition) else get_strategy(strategy_or_id)
        if not strat:
            raise ValueError(f"Unknown strategy: {strategy_or_id}")

        target_universe = universe_override or strat.universe
        stocks = universe.get_stocks(index_tier=target_universe)
        if max_stocks and max_stocks > 0:
            stocks = stocks[:max_stocks]

        logger.info(
            "Starting scan for strategy '%s' across universe '%s' (%d stocks)...",
            strat.strategy_id,
            target_universe,
            len(stocks),
        )

        passed_candidates: List[ScanCandidate] = []

        def _worker(stock_meta: Dict[str, Any]) -> Optional[ScanCandidate]:
            sym = stock_meta["symbol"]
            try:
                raw_df = self.loader.load_ohlcv(sym, period="max")
                if raw_df.empty or len(raw_df) < 20:
                    return None
                clean_df = self.cleaner.clean_ohlcv(raw_df, ticker_name=sym)
                candidate = self.evaluate_dataframe(
                    clean_df,
                    strategy=strat,
                    symbol=sym,
                    name=stock_meta.get("name", sym),
                    sector=stock_meta.get("sector", "Market"),
                    as_of_date=as_of_date,
                )
                return candidate if candidate.passed else None
            except Exception as ex:
                logger.debug("Skipping %s due to error: %s", sym, ex)
                return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_stock = {executor.submit(_worker, s): s for s in stocks}
            for future in as_completed(future_to_stock):
                res = future.result()
                if res is not None:
                    passed_candidates.append(res)

        # Sort candidates deterministically by symbol
        passed_candidates.sort(key=lambda c: c.symbol)
        logger.info(
            "Scan complete for '%s': Found %d passing stocks in '%s'",
            strat.strategy_id,
            len(passed_candidates),
            target_universe,
        )
        return passed_candidates

    def scan_all_strategies(
        self,
        as_of_date: Optional[Union[str, pd.Timestamp]] = None,
        max_stocks_per_universe: Optional[int] = None,
        max_workers: int = 8,
    ) -> Dict[str, List[ScanCandidate]]:
        """Scans each of the 4 defined strategies across their respective universes."""
        results: Dict[str, List[ScanCandidate]] = {}
        for strat_id, strat in STRATEGY_REGISTRY.items():
            candidates = self.scan_universe(
                strat,
                as_of_date=as_of_date,
                max_stocks=max_stocks_per_universe,
                max_workers=max_workers,
            )
            results[strat_id] = candidates
        return results

    def check_stock_all_strategies(
        self,
        ticker: str,
        as_of_date: Optional[Union[str, pd.Timestamp]] = None,
    ) -> Dict[str, Any]:
        """Checks whether a single stock satisfies any of the 4 defined strategies.
        
        Returns full multi-timeframe RSI metrics and condition evaluation breakdown.
        """
        meta = universe.get_stock(ticker) or {"symbol": ticker, "name": ticker, "sector": "Market"}
        raw_df = self.loader.load_ohlcv(ticker, period="max")
        if raw_df.empty:
            return {
                "symbol": ticker,
                "valid": False,
                "error": f"No data found for {ticker}",
            }

        clean_df = self.cleaner.clean_ohlcv(raw_df, ticker_name=ticker)
        mtf = extract_multi_timeframe_indicators(clean_df, as_of_date=as_of_date, period=14)

        evaluations = {}
        matches = []
        for strat_id, strat in STRATEGY_REGISTRY.items():
            cand = self.evaluate_dataframe(
                clean_df,
                strategy=strat,
                symbol=ticker,
                name=meta.get("name", ticker),
                sector=meta.get("sector", "Market"),
                as_of_date=as_of_date,
            )
            evaluations[strat_id] = cand.to_dict()
            if cand.passed:
                matches.append({
                    "strategy_id": strat.strategy_id,
                    "name": strat.name,
                    "universe": strat.universe,
                    "purpose": strat.purpose,
                })

        return {
            "symbol": ticker,
            "company_name": meta.get("name", ticker),
            "sector": meta.get("sector", "Market"),
            "as_of_date": mtf.get("as_of_date"),
            "indicators": mtf,
            "total_strategies": len(STRATEGY_REGISTRY),
            "matching_strategies_count": len(matches),
            "matches": matches,
            "has_setup": len(matches) > 0,
            "evaluations": evaluations,
        }
