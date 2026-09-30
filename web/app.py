"""Web application backend for StockPilot NIFTY 50 explorer."""

import logging
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import yfinance as yf

from stockpilot.data.loader import DataLoader
from stockpilot.data.cleaner import DataCleaner
from stockpilot.universe import universe, BENCHMARK_INDICES
from stockpilot.trade.planner import TradePlanner
from stockpilot.strategy import (
    StrategyScannerEngine,
    STRATEGY_REGISTRY,
    list_strategies,
    get_strategy,
)


logger = logging.getLogger(__name__)

app = FastAPI(title="StockPilot Market Explorer (NIFTY 50 - 500)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

loader = DataLoader()
cleaner = DataCleaner()


def _calc_returns_profile(df: pd.DataFrame, price_col: str = "Close") -> dict:
    """Calculates returns over 1W, 1M, YTD, 1Y, 3Y, 5Y periods."""
    if df.empty or len(df) < 2:
        return {}
    df = df.sort_values("Date").reset_index(drop=True)
    curr = float(df[price_col].iloc[-1])
    curr_date = df["Date"].iloc[-1]
    periods = {"1W": 5, "1M": 21, "1Y": 252, "3Y": 756, "5Y": 1260}
    out = {}
    for label, days in periods.items():
        if len(df) > days:
            past = float(df[price_col].iloc[-1 - days])
            out[label] = round(((curr - past) / past) * 100.0, 2)
        else:
            out[label] = None

    y_start = pd.to_datetime(f"{curr_date.year}-01-01")
    y_df = df[df["Date"] <= y_start]
    if not y_df.empty:
        y_past = float(y_df[price_col].iloc[-1])
        out["YTD"] = round(((curr - y_past) / y_past) * 100.0, 2)
    else:
        out["YTD"] = None
    return out


@app.get("/api/tiers")
def get_tiers():
    """Returns available index tiers and broad benchmarks."""
    return {
        "tiers": ["ALL", "NIFTY 50", "NIFTY 100", "NIFTY 200", "NIFTY 500"],
        "benchmarks": BENCHMARK_INDICES,
    }


@app.get("/api/sectors")
def get_sectors(tier: Optional[str] = Query(None, description="Index tier: ALL, NIFTY 50, NIFTY 100, NIFTY 200, NIFTY 500")):
    """Returns unique sectors across the universe or filtered by index tier."""
    tier_arg = None if (not tier or tier.upper() == "ALL") else tier
    sector_details = universe.get_sectors_for_tier(tier_arg)
    return {
        "tier": tier or "ALL",
        "sectors": [s["name"] for s in sector_details],
        "sector_details": sector_details,
    }


@app.get("/api/stocks")
def get_stocks(
    tier: Optional[str] = Query("NIFTY 100", description="Index tier: ALL, NIFTY 50, NIFTY 100, NIFTY 200, NIFTY 500"),
    sector: Optional[str] = Query(None, description="Sector filter"),
    search: Optional[str] = Query(None, description="Search keyword"),
):
    """Returns constituent stocks filtered by tier, sector, and search query."""
    tier_arg = None if (not tier or tier.upper() == "ALL") else tier
    stocks = universe.get_stocks(index_tier=tier_arg, sector=sector)
    if search and search.strip():
        q = search.strip().lower()
        stocks = [s for s in stocks if q in s["symbol"].lower() or q in s["name"].lower()]
    return {"count": len(stocks), "tier": tier, "sector": sector, "stocks": stocks}


@app.get("/api/data")
def get_stock_data(
    ticker: str = Query("RELIANCE.NS", description="Stock ticker symbol (e.g. RELIANCE.NS)"),
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    period: Optional[str] = Query("max", description="Timeframe period (1mo, 6mo, 1y, 3y, max)"),
    limit: Optional[int] = Query(None, description="Max number of records to return (None for all)"),
    benchmark: Optional[str] = Query("^NSEI", description="Benchmark to compare against (^NSEI, ^CRSLDX, ^CNX100)"),
):
    """Loads and returns date-wise OHLCV records for the selected stock from its very first trading day."""
    ticker_info = universe.get_stock(ticker) or {"symbol": ticker, "name": ticker, "sector": "Market", "indices": ["NIFTY 50"]}


    try:
        # Always fetch complete history from day 1
        df = loader.load_ohlcv(ticker, period="max")
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for ticker {ticker}")

        cleaned = cleaner.clean_ohlcv(df, ticker_name=ticker)
        if cleaned.empty:
            raise HTTPException(status_code=404, detail=f"No valid data after cleaning for {ticker}")

        cleaned["Change"] = cleaned["Close"] - cleaned["Open"]
        cleaned["Change_Pct"] = ((cleaned["Close"] - cleaned["Open"]) / cleaned["Open"]) * 100.0
        cleaned["Return_1d_Pct"] = cleaned["Close"].pct_change() * 100.0

        latest_row = cleaned.iloc[-1]
        prev_row = cleaned.iloc[-2] if len(cleaned) > 1 else latest_row

        close_val = float(latest_row["Close"])
        prev_close = float(prev_row["Close"])
        day_change = close_val - prev_close
        day_change_pct = (day_change / prev_close) * 100.0 if prev_close > 0 else 0.0

        # 52-Week High and Low with exact dates
        window_52w = cleaned.tail(252)
        h_idx = window_52w["High"].idxmax()
        l_idx = window_52w["Low"].idxmin()
        high_52w_val = round(float(window_52w.loc[h_idx, "High"]), 2)
        high_52w_date = window_52w.loc[h_idx, "Date"].strftime("%d-%b-%Y")
        low_52w_val = round(float(window_52w.loc[l_idx, "Low"]), 2)
        low_52w_date = window_52w.loc[l_idx, "Date"].strftime("%d-%b-%Y")

        # Volatilities (30-day realized standard deviation)
        returns_30d = cleaned["Close"].pct_change().tail(30).dropna()
        daily_vol = round(float(returns_30d.std() * 100.0), 2) if len(returns_30d) > 1 else 0.0
        annual_vol = round(float(daily_vol * np.sqrt(252)), 2)

        # Trade quantities
        vol_lakhs = round(float(latest_row["Volume"]) / 100000.0, 2)
        val_cr = round((float(latest_row["Volume"]) * close_val) / 10000000.0, 2)

        # Fetch yfinance ticker info
        try:
            yf_info = yf.Ticker(ticker).info or {}
        except Exception:
            yf_info = {}

        raw_mcap = yf_info.get("marketCap")
        total_mcap_cr = round(float(raw_mcap) / 10000000.0, 2) if raw_mcap else round((close_val * 1e8) / 1e7, 2)
        raw_float = yf_info.get("floatShares")
        ff_mcap_cr = round((float(raw_float) * close_val) / 10000000.0, 2) if raw_float else round(total_mcap_cr * 0.45, 2)

        face_value = float(yf_info.get("faceValue", 10.0)) if yf_info.get("faceValue") else 10.0
        symbol_pe = round(float(yf_info["trailingPE"]), 2) if yf_info.get("trailingPE") else None
        adjusted_pe = round(float(yf_info["forwardPE"]), 2) if yf_info.get("forwardPE") else None
        industry = yf_info.get("industry") or ticker_info.get("sector")

        # Returns comparison against selected benchmark
        bench_df = loader.load_benchmark(benchmark)
        bench_clean = cleaner.clean_ohlcv(bench_df) if not bench_df.empty else pd.DataFrame()
        stock_returns = _calc_returns_profile(cleaned, "Close")
        bench_close_col = "Benchmark_Close" if "Benchmark_Close" in bench_clean.columns else "Close"
        bench_returns = _calc_returns_profile(bench_clean, bench_close_col)

        summary = {
            "first_trading_date": str(cleaned["Date"].min().strftime("%Y-%m-%d")),
            "latest_date": str(latest_row["Date"].strftime("%Y-%m-%d")),
            "latest_close": round(close_val, 2),
            "prev_close": round(prev_close, 2),
            "change": round(day_change, 2),
            "change_pct": round(day_change_pct, 2),
            "day_open": round(float(latest_row["Open"]), 2),
            "day_high": round(float(latest_row["High"]), 2),
            "day_low": round(float(latest_row["Low"]), 2),
            "volume": int(latest_row["Volume"]),
            "high_52w": high_52w_val,
            "low_52w": low_52w_val,
            "total_records": len(cleaned),
        }

        company_details = {
            "returns_comparison": {
                "stock": stock_returns,
                "benchmark": bench_returns,
            },
            "trade_info": {
                "traded_volume_lakhs": vol_lakhs,
                "traded_value_cr": val_cr,
                "total_market_cap_cr": total_mcap_cr,
                "free_float_market_cap_cr": ff_mcap_cr,
                "impact_cost": 0.04,
                "face_value": face_value,
                "applicable_margin_rate": 18.5,
                "deliverable_pct": 55.23,
            },
            "price_info": {
                "high_52w": high_52w_val,
                "high_52w_date": high_52w_date,
                "low_52w": low_52w_val,
                "low_52w_date": low_52w_date,
                "upper_band": round(prev_close * 1.10, 2),
                "lower_band": round(prev_close * 0.90, 2),
                "price_band": "No Band (F&O)",
                "tick_size": 0.05,
                "daily_volatility": daily_vol,
                "annualised_volatility": annual_vol,
            },
            "securities_info": {
                "status": "Listed",
                "trading_status": "Active",
                "symbol_pe": symbol_pe,
                "adjusted_pe": adjusted_pe,
                "date_of_listing": str(cleaned["Date"].min().strftime("%d-%b-%Y")),
                "index": ", ".join(ticker_info.get("indices", ["NIFTY 50"])),
                "basic_industry": industry,
            },
        }

        # Filter by timeframe if a sub-period is chosen (1mo, 6mo, 1y, 3y)
        display_df = cleaned.copy()
        if period and period != "max" and start:
            display_df = display_df[display_df["Date"] >= pd.to_datetime(start)]

        records_df = display_df.sort_values("Date", ascending=False)
        if limit:
            records_df = records_df.head(limit)

        records = []
        for _, row in records_df.iterrows():
            records.append({
                "Date": str(row["Date"].strftime("%Y-%m-%d")),
                "Open": round(float(row["Open"]), 2),
                "High": round(float(row["High"]), 2),
                "Low": round(float(row["Low"]), 2),
                "Close": round(float(row["Close"]), 2),
                "Adj_Close": round(float(row["Adj Close"]), 2) if "Adj Close" in row else round(float(row["Close"]), 2),
                "Volume": int(row["Volume"]),
                "Change": round(float(row["Change"]), 2),
                "Change_Pct": round(float(row["Change_Pct"]), 2),
                "Return_1d_Pct": round(float(row["Return_1d_Pct"]), 2) if not pd.isna(row["Return_1d_Pct"]) else 0.0,
                "is_outlier": bool(row.get("is_outlier_return", False)),
                "is_circuit": bool(row.get("is_circuit_day", False)),
                "is_zero_vol": bool(row.get("is_zero_volume", False)),
            })


        return {
            "ticker": ticker,
            "company_name": ticker_info["name"],
            "sector": ticker_info["sector"],
            "summary": summary,
            "company_details": company_details,
            "records": records,
        }

    except Exception as e:
        logger.error("Error fetching data for %s: %s", ticker, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trade-setup")
def get_trade_setup(
    ticker: str = Query("RELIANCE.NS", description="Stock ticker symbol"),
    trade_term: str = Query("medium", description="Trade term: short, medium, or long"),
    trading_type: str = Query("swing", description="Trading type: swing, positional, investing, intraday, futures, options"),
    available_capital: Optional[float] = Query(100000.0, description="Total available capital in INR"),
    max_loss: Optional[float] = Query(2000.0, description="Maximum acceptable loss in INR"),
    deadline_date: Optional[str] = Query(None, description="Repayment deadline date (YYYY-MM-DD)"),
    capital: Optional[float] = Query(100000.0, description="Borrowed capital in INR"),
    interest_rate: Optional[float] = Query(10.0, description="Annual borrowing cost % p.a."),
):
    """Calculates Option A (Full Trade until Target/Exit) and Option B (Deadline-Constrained for Borrowed Capital).

    Includes position sizing computed from available capital and maximum acceptable loss.
    """
    try:
        df = loader.load_ohlcv(ticker, period="max")
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

        cleaned = cleaner.clean_ohlcv(df, ticker_name=ticker)
        planner = TradePlanner()
        setup = planner.generate_both_options(
            cleaned,
            ticker=ticker,
            trade_term=trade_term or "medium",
            trading_type=trading_type or "swing",
            available_capital=available_capital or 100000.0,
            max_acceptable_loss=max_loss or 2000.0,
            deadline_date=deadline_date,
            borrowed_capital=capital or 100000.0,
            annual_interest_rate=interest_rate or 10.0,
        )
        return setup
    except Exception as e:
        logger.error("Error generating trade setup for %s: %s", ticker, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


scanner_engine = StrategyScannerEngine(loader=loader, cleaner=cleaner)


@app.get("/api/strategies")
def get_strategies():
    """Returns declarative metadata and conditions for all 4 defined user strategies."""
    return {
        "count": len(STRATEGY_REGISTRY),
        "strategies": list_strategies(),
    }


@app.get("/api/scan")
def run_strategy_scan(
    strategy_id: str = Query("HTF_BULLISH_DEEP_DAILY_PULLBACK", description="Strategy ID or 'ALL'"),
    universe_override: Optional[str] = Query(None, description="Optional universe tier override (NIFTY 50, NIFTY 100, NIFTY 200, NIFTY 500)"),
    as_of_date: Optional[str] = Query(None, description="Point-in-time evaluation cutoff YYYY-MM-DD"),
    limit: Optional[int] = Query(None, description="Max candidates to return"),
):
    """Scans the designated universe against the selected strategy and returns matching candidates with audit evidence."""
    try:
        if strategy_id.upper() == "ALL":
            all_results = scanner_engine.scan_all_strategies(as_of_date=as_of_date)
            formatted = {}
            total = 0
            for sid, cands in all_results.items():
                if limit:
                    cands = cands[:limit]
                formatted[sid] = [c.to_dict() for c in cands]
                total += len(cands)
            return {
                "strategy_id": "ALL",
                "total_candidates": total,
                "results_by_strategy": formatted,
            }

        strat = get_strategy(strategy_id)
        if not strat:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{strategy_id}' not found. Available: {list(STRATEGY_REGISTRY.keys())}",
            )

        candidates = scanner_engine.scan_universe(
            strat,
            universe_override=universe_override,
            as_of_date=as_of_date,
        )
        if limit:
            candidates = candidates[:limit]

        return {
            "strategy_id": strat.strategy_id,
            "strategy_name": strat.name,
            "universe": universe_override or strat.universe,
            "purpose": strat.purpose,
            "count": len(candidates),
            "candidates": [c.to_dict() for c in candidates],
        }
    except Exception as e:
        logger.error("Scan error for strategy %s: %s", strategy_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock-strategy-check")
def check_stock_strategies(
    ticker: str = Query("RELIANCE.NS", description="Stock ticker symbol"),
    as_of_date: Optional[str] = Query(None, description="Point-in-time evaluation cutoff YYYY-MM-DD"),
):
    """Checks whether the selected stock satisfies any of the 4 defined user strategies."""
    try:
        res = scanner_engine.check_stock_all_strategies(ticker, as_of_date=as_of_date)
        return res
    except Exception as e:
        logger.error("Strategy check error for %s: %s", ticker, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")

def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(index_path)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
