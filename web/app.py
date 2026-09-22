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

from stockpilot.data.loader import DataLoader
from stockpilot.data.cleaner import DataCleaner
from stockpilot.nifty50 import NIFTY_50_STOCKS

logger = logging.getLogger(__name__)

app = FastAPI(title="StockPilot NIFTY 50 Explorer")

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

STOCKS_BY_SYMBOL = {s["symbol"]: s for s in NIFTY_50_STOCKS}


@app.get("/api/stocks")
def get_stocks():
    """Returns the full list of NIFTY 50 constituent stocks."""
    return {"count": len(NIFTY_50_STOCKS), "stocks": NIFTY_50_STOCKS}


@app.get("/api/data")
def get_stock_data(
    ticker: str = Query("RELIANCE.NS", description="Stock ticker symbol (e.g. RELIANCE.NS)"),
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    period: Optional[str] = Query("max", description="Timeframe period (1mo, 6mo, 1y, 3y, max)"),
    limit: Optional[int] = Query(None, description="Max number of records to return (None for all)"),
):
    """Loads and returns date-wise OHLCV records for the selected stock from its very first trading day."""
    ticker_info = STOCKS_BY_SYMBOL.get(ticker, {"symbol": ticker, "name": ticker, "sector": "Market"})

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

        window_52w = cleaned.tail(252)
        high_52w = float(window_52w["High"].max())
        low_52w = float(window_52w["Low"].min())

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
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "total_records": len(cleaned),
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
            })

        return {
            "ticker": ticker,
            "company_name": ticker_info["name"],
            "sector": ticker_info["sector"],
            "summary": summary,
            "records": records,
        }

    except Exception as e:
        logger.error("Error fetching data for %s: %s", ticker, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(index_path)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
