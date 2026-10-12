"""Web application backend for StockPilot NIFTY 50 explorer."""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Query
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
    create_custom_strategy,
    update_strategy,
    delete_strategy,
    reset_strategy,
)
from stockpilot.ml import ml_engine
from stockpilot.ml.recommender import stock_recommender


logger = logging.getLogger(__name__)

app = FastAPI(title="StockPilot Market Explorer (NIFTY 50 - 500)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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
    refresh: bool = Query(False, description="Force re-fetch latest data from Yahoo Finance and update cache"),
):
    """Loads and returns date-wise OHLCV records for the selected stock from its very first trading day."""
    ticker_info = universe.get_stock(ticker) or {"symbol": ticker, "name": ticker, "sector": "Market", "indices": ["NIFTY 50"]}

    try:
        # Load complete history; if refresh=True, incrementally sync latest data from Yahoo Finance
        if refresh:
            loader.sync_live_ohlcv(ticker)
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


@app.post("/api/sync-live-data")
@app.get("/api/sync-live-data")
def sync_live_data(
    ticker: str = Query("RELIANCE.NS", description="Stock ticker symbol to sync"),
    sync_benchmark: bool = Query(True, description="Also sync benchmark index ^NSEI"),
):
    """Fetches live quotes and latest daily candles up to today from Yahoo Finance and updates cache."""
    clean_ticker = ticker if (ticker.endswith(".NS") or ticker.startswith("^")) else f"{ticker}.NS"
    try:
        stock_res = loader.sync_live_ohlcv(clean_ticker)
        bench_res = None
        if sync_benchmark:
            bench_res = loader.sync_live_ohlcv("^NSEI")
            # Update ML engine's benchmark cache so all models use fresh data
            try:
                bench_df = loader.load_ohlcv("^NSEI", start_date="2020-01-01")
                if not bench_df.empty:
                    ml_engine._benchmark_cached_df = bench_df.tail(500).reset_index(drop=True)
            except Exception as me:
                logger.debug("Benchmark ML engine update notice: %s", me)

        indices_data = None
        try:
            indices_res = get_market_indices(refresh=True)
            indices_data = indices_res.get("indices", [])
        except Exception as ie:
            logger.debug("Indices sync error: %s", ie)

        return {
            "status": "success",
            "ticker": clean_ticker,
            "stock": stock_res,
            "benchmark": bench_res,
            "indices": indices_data,
            "latest_date": stock_res.get("latest_date"),
            "latest_close": stock_res.get("latest_close"),
            "new_bars_added": stock_res.get("new_bars_added", 0),
            "total_rows": stock_res.get("total_rows"),
            "message": f"Successfully updated {clean_ticker} to {stock_res.get('latest_date')}.",
        }
    except Exception as e:
        logger.error("Error syncing live data for %s: %s", clean_ticker, e)
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
    """Returns declarative metadata and conditions for all defined user strategies."""
    return {
        "count": len(STRATEGY_REGISTRY),
        "strategies": list_strategies(),
    }


@app.post("/api/strategies")
def create_strategy_endpoint(payload: Dict[str, Any] = Body(...)):
    """Creates a new custom technical scanner and persists it to disk."""
    try:
        strat = create_custom_strategy(payload)
        return {
            "success": True,
            "message": f"Successfully created scanner '{strat.name}' ({strat.strategy_id})",
            "strategy": strat.to_dict(),
        }
    except Exception as e:
        logger.error("Error creating custom strategy: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/strategies/{strategy_id}")
def update_strategy_endpoint(strategy_id: str, payload: Dict[str, Any] = Body(...)):
    """Updates/customizes an existing scanner strategy (built-in or custom)."""
    try:
        strat = update_strategy(strategy_id, payload)
        return {
            "success": True,
            "message": f"Successfully updated scanner '{strat.name}'",
            "strategy": strat.to_dict(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error updating strategy %s: %s", strategy_id, e)
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/strategies/{strategy_id}")
def delete_strategy_endpoint(strategy_id: str):
    """Deletes a custom scanner strategy."""
    try:
        delete_strategy(strategy_id)
        return {
            "success": True,
            "message": f"Deleted custom strategy '{strategy_id}'",
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error deleting strategy %s: %s", strategy_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/strategies/{strategy_id}/reset")
def reset_strategy_endpoint(strategy_id: str):
    """Resets a customized built-in strategy back to its default specification."""
    try:
        strat = reset_strategy(strategy_id)
        return {
            "success": True,
            "message": f"Reset scanner '{strat.name}' back to default parameters",
            "strategy": strat.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error resetting strategy %s: %s", strategy_id, e)
        raise HTTPException(status_code=500, detail=str(e))


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
@app.post("/api/sync-stock")
@app.get("/api/sync-stock")
def sync_stock_data(
    ticker: str = Query("RELIANCE.NS", description="Stock ticker symbol to sync"),
):
    """Fetches live latest market data for the ticker from Yahoo Finance, cleans, and updates cache."""
    try:
        df = loader.load_ohlcv(ticker, period="max", force_reload=True)
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data returned for {ticker} from market feed")
        cleaned = cleaner.clean_ohlcv(df, ticker_name=ticker)
        latest_row = cleaned.iloc[-1]
        return {
            "success": True,
            "ticker": ticker,
            "rows": len(cleaned),
            "first_date": str(cleaned["Date"].min().strftime("%Y-%m-%d")),
            "latest_date": str(latest_row["Date"].strftime("%Y-%m-%d")),
            "latest_close": round(float(latest_row["Close"]), 2),
            "message": f"Successfully updated {ticker} to {latest_row['Date'].strftime('%d-%b-%Y')}",
        }
    except Exception as e:
        logger.error("Sync error for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market-stats")
def get_market_stats():
    """Returns universe coverage and cache freshness statistics."""
    try:
        cache_files = list(Path(loader.config.cache_dir).glob("*_ohlcv.parquet"))
        stocks_50 = len(universe.get_stocks("NIFTY 50"))
        stocks_100 = len(universe.get_stocks("NIFTY 100"))
        stocks_200 = len(universe.get_stocks("NIFTY 200"))
        stocks_500 = len(universe.get_stocks("NIFTY 500"))
        all_stocks = len(universe.get_stocks("ALL"))

        # Find newest cached date across meta files
        meta_files = list(Path(loader.config.cache_dir).glob("*_ohlcv.meta.json"))
        latest_dates = []
        for mf in meta_files:
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    m_json = json.load(f)
                    if m_json.get("last_date"):
                        latest_dates.append(m_json["last_date"])
            except Exception:
                pass

        newest_cached_date = max(latest_dates) if latest_dates else "N/A"

        # Sector counts
        sectors = universe.get_all_sectors()
        sector_counts = {}
        for sec in sectors:
            sector_counts[sec] = len(universe.get_stocks(index_tier="ALL", sector=sec))

        return {
            "cached_tickers_count": len(cache_files),
            "newest_cached_date": newest_cached_date,
            "tiers": {
                "NIFTY 50": stocks_50,
                "NIFTY 100": stocks_100,
                "NIFTY 200": stocks_200,
                "NIFTY 500": stocks_500,
                "ALL": all_stocks,
            },
            "sectors_count": len(sectors),
            "sector_breakdown": sector_counts,
        }
    except Exception as e:
        logger.error("Market stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


_market_indices_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "indices": [],
}


@app.get("/api/market-indices")
def get_market_indices(refresh: bool = False):
    """
    Returns live market indices (NIFTY 50, NIFTY NEXT 50, BANK NIFTY, INDIA VIX, NIFTY 500)
    with LTP, point change, percentage change, and status.
    """
    global _market_indices_cache
    now = time.time()

    # Cache for 45 seconds unless refresh requested
    if not refresh and (now - _market_indices_cache["timestamp"] < 45.0) and _market_indices_cache["indices"]:
        return {
            "status": "cached",
            "indices": _market_indices_cache["indices"],
            "timestamp": _market_indices_cache["timestamp"],
        }

    indices_config = [
        ("NIFTY 50", "^NSEI"),
        ("NIFTY NEXT 50", "^NSMIDCP"),
        ("BANK NIFTY", "^NSEBANK"),
        ("INDIA VIX", "^INDIAVIX"),
        ("NIFTY 500", "^CRSLDX"),
    ]

    tickers = [t for _, t in indices_config]
    try:
        data = yf.download(tickers, period="5d", progress=False)
        parsed = []
        for name, ticker in indices_config:
            ltp, chg, pct, date_str = 0.0, 0.0, 0.0, ""
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if "Close" in data.columns.levels[0] and ticker in data["Close"].columns:
                        close_s = data["Close"][ticker].dropna()
                    else:
                        close_s = pd.Series(dtype=float)
                elif "Close" in data:
                    close_s = data["Close"].dropna()
                else:
                    close_s = pd.Series(dtype=float)

                if len(close_s) >= 1:
                    ltp = float(close_s.iloc[-1])
                    prev = float(close_s.iloc[-2]) if len(close_s) >= 2 else ltp
                    chg = ltp - prev
                    pct = (chg / prev) * 100.0 if prev else 0.0
                    date_str = str(close_s.index[-1].date())
            except Exception as parse_err:
                logger.warning("Error parsing downloaded index %s: %s", ticker, parse_err)

            # Fallback to local loader cache if download gave 0 or empty
            if ltp == 0.0:
                try:
                    cached_df = loader.load_ohlcv(ticker, period="1mo")
                    if not cached_df.empty and "close" in cached_df.columns:
                        c_s = cached_df["close"].dropna()
                        if len(c_s) >= 1:
                            ltp = float(c_s.iloc[-1])
                            prev = float(c_s.iloc[-2]) if len(c_s) >= 2 else ltp
                            chg = ltp - prev
                            pct = (chg / prev) * 100.0 if prev else 0.0
                            date_str = str(c_s.index[-1].date()) if hasattr(c_s.index[-1], 'date') else str(c_s.index[-1])[:10]
                except Exception as cache_err:
                    logger.debug("Local cache fallback failed for %s: %s", ticker, cache_err)

            parsed.append({
                "name": name,
                "ticker": ticker,
                "ltp": round(ltp, 2),
                "change": round(chg, 2),
                "change_pct": round(pct, 2),
                "is_positive": chg >= 0,
                "date": date_str,
            })

        _market_indices_cache = {
            "timestamp": now,
            "indices": parsed,
        }
        return {
            "status": "live",
            "indices": parsed,
            "timestamp": now,
        }
    except Exception as e:
        logger.error("Failed to fetch live market indices: %s", e)
        if _market_indices_cache["indices"]:
            return {
                "status": "cached_fallback",
                "indices": _market_indices_cache["indices"],
                "timestamp": _market_indices_cache["timestamp"],
            }
        
        # Emergency offline fallback from local cache
        fallback_parsed = []
        for name, ticker in indices_config:
            ltp, chg, pct, date_str = 0.0, 0.0, 0.0, ""
            try:
                cached_df = loader.load_ohlcv(ticker, period="1mo")
                if not cached_df.empty and "close" in cached_df.columns:
                    c_s = cached_df["close"].dropna()
                    if len(c_s) >= 1:
                        ltp = float(c_s.iloc[-1])
                        prev = float(c_s.iloc[-2]) if len(c_s) >= 2 else ltp
                        chg = ltp - prev
                        pct = (chg / prev) * 100.0 if prev else 0.0
                        date_str = str(c_s.index[-1].date()) if hasattr(c_s.index[-1], 'date') else str(c_s.index[-1])[:10]
            except Exception:
                pass
            fallback_parsed.append({
                "name": name,
                "ticker": ticker,
                "ltp": round(ltp, 2),
                "change": round(chg, 2),
                "change_pct": round(pct, 2),
                "is_positive": chg >= 0,
                "date": date_str,
            })
        _market_indices_cache = {
            "timestamp": now,
            "indices": fallback_parsed,
        }
        return {
            "status": "offline_fallback",
            "indices": fallback_parsed,
            "timestamp": now,
        }


@app.get("/api/ml/regime")
def get_ml_regime():
    """Returns macroeconomic market regime detected via GMM on benchmark."""
    try:
        return ml_engine.get_market_regime()
    except Exception as e:
        logger.error("Error detecting ML market regime: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/qualify")
def get_ml_qualification(ticker: str = Query(..., description="Stock ticker symbol e.g. RELIANCE.NS")):
    """Returns meta-label trade qualification, win probability, SHAP attributions, and Kelly multiplier."""
    try:
        clean_ticker = ticker if (ticker.endswith(".NS") or ticker.startswith("^")) else f"{ticker}.NS"
        result = ml_engine.analyze_stock_ml(clean_ticker)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error qualifying stock %s with ML: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/features")
def get_ml_features(ticker: str = Query(..., description="Stock ticker symbol e.g. RELIANCE.NS")):
    """Returns detailed microstructure and stationarity feature snapshot."""
    try:
        clean_ticker = ticker if (ticker.endswith(".NS") or ticker.startswith("^")) else f"{ticker}.NS"
        df = loader.load_ohlcv(clean_ticker, start_date="2020-01-01")
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {clean_ticker}")
        if len(df) > 500:
            df = df.tail(500).reset_index(drop=True)
            
        feats_df = ml_engine.feature_pipeline.extract_features(df, ml_engine._benchmark_cached_df)
        if feats_df.empty:
            raise HTTPException(status_code=400, detail="Feature extraction failed")
        
        latest = feats_df.iloc[-1].to_dict()
        # Clean any float NaN or non-serializable values
        cleaned_latest = {
            k: (None if pd.isna(v) else round(float(v), 4) if isinstance(v, (float, np.floating)) else str(v) if isinstance(v, pd.Timestamp) else v) 
            for k, v in latest.items()
        }
        return {
            "ticker": clean_ticker,
            "feature_count": len(cleaned_latest),
            "features": cleaned_latest,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error extracting ML features for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ml/recommend")
def get_ml_recommendations(
    term: str = Query("medium", description="Investment term: short, medium, or long"),
    target_date: Optional[str] = Query(None, description="Specific target date YYYY-MM-DD (overrides term)"),
    index_tier: Optional[str] = Query(None, description="Index tier filter: NIFTY 50, NIFTY 100, NIFTY 200, NIFTY 500, or ALL"),
    sector: Optional[str] = Query(None, description="Sector/industry filter"),
    top_n: int = Query(10, description="Number of top recommendations to return"),
    min_score: float = Query(45.0, description="Minimum composite score threshold (0-100)"),
    min_rr: float = Query(1.0, description="Minimum risk-to-reward ratio (e.g. 1.0 for 1:1, 1.5 for 1.5:1)"),
):
    """Smart Stock Recommendation Engine.
    
    Scans the NIFTY universe filtered by index tier and/or sector,
    scores each stock using a term-weighted multi-factor composite model,
    ranks them by suitability, and returns actionable trade plans with
    entry zones, stop-loss, targets, risk-reward ratios, and transparent
    reasoning explaining why each stock was recommended.
    
    Term options:
    - short: 2-15 day quick momentum capture
    - medium: 5-45 day swing trade setups  
    - long: 20-180 day positional / investment horizon
    - Or provide a specific target_date to auto-detect the best term
    """
    try:
        valid_terms = ["short", "medium", "long"]
        if term not in valid_terms:
            term = "medium"
        
        result = stock_recommender.recommend(
            term=term,
            target_date=target_date,
            index_tier=index_tier,
            sector=sector,
            top_n=min(max(1, top_n), 50),
            min_score=max(0.0, min(100.0, min_score)),
            min_risk_reward=max(1.0, min_rr),
        )
        return result
    except Exception as e:
        logger.error("Error generating ML recommendations: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    content = index_path.read_text(encoding="utf-8")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
