"""Data Loader module for StockPilot using yfinance."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import yfinance as yf

from stockpilot.config import DataConfig

logger = logging.getLogger(__name__)


def _sanitize_ticker(ticker: str) -> str:
    """Sanitize ticker string for safe filesystem usage on Windows/Linux."""
    return ticker.replace("^", "INDEX_").replace("/", "_").replace("\\", "_").replace(":", "_")


class DataLoader:
    """Handles data loading and raw caching for market, benchmark, sector,

    fundamentals, and news data from Yahoo Finance.
    """

    def __init__(self, config: Optional[DataConfig] = None):
        self.config = config or DataConfig()
        self.cache_dir = Path(self.config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_ohlcv(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "max",
        force_reload: bool = False,
    ) -> pd.DataFrame:
        """Loads historical OHLCV data with raw and adjusted prices from the very first day of trading.

        Includes Dividends and Stock Splits.
        """
        safe_ticker = _sanitize_ticker(ticker)
        cache_file = self.cache_dir / f"{safe_ticker}_ohlcv.parquet"
        cache_meta_file = self.cache_dir / f"{safe_ticker}_ohlcv.meta.json"

        is_max_request = (period == "max" or start_date is None)

        if not force_reload and cache_file.exists():
            try:
                # Check if cache holds full history when max is requested
                cache_is_max = False
                if cache_meta_file.exists():
                    try:
                        with open(cache_meta_file, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            cache_is_max = meta.get("is_max_history", False)
                    except Exception:
                        cache_is_max = False

                df = pd.read_parquet(cache_file)
                if not df.empty and "Date" in df.columns:
                    df["Date"] = pd.to_datetime(df["Date"])
                    if start_date and not is_max_request:
                        req_start = pd.to_datetime(start_date)
                        cache_min = df["Date"].min()
                        if cache_min <= req_start + pd.Timedelta(days=7):
                            logger.info("Loading cached OHLCV for %s from %s", ticker, cache_file)
                            filtered = df[df["Date"] >= req_start]
                            if end_date:
                                filtered = filtered[filtered["Date"] <= pd.to_datetime(end_date)]
                            return filtered.reset_index(drop=True)
                        else:
                            logger.info("Cache for %s starts at %s, but %s requested. Re-fetching full history...",
                                        ticker, cache_min.date(), req_start.date())
                    elif is_max_request:
                        if cache_is_max:
                            logger.info("Loading full cached day-1 OHLCV for %s (rows: %d, first: %s)",
                                        ticker, len(df), df["Date"].min().date())
                            if end_date:
                                df = df[df["Date"] <= pd.to_datetime(end_date)]
                            return df.reset_index(drop=True)
                        else:
                            logger.info("Cache for %s is not verified day-1 history. Re-fetching full max history...", ticker)
            except Exception as e:
                logger.warning("Error reading cache file %s: %s", cache_file, e)

        logger.info("Fetching complete history from day 1 for %s from Yahoo Finance...", ticker)
        yf_ticker = yf.Ticker(ticker)

        if start_date and not is_max_request:
            df = yf_ticker.history(
                start=start_date,
                end=end_date,
                auto_adjust=self.config.auto_adjust,
                actions=True,
            )
        else:
            df = yf_ticker.history(
                period="max",
                auto_adjust=self.config.auto_adjust,
                actions=True,
            )
            if df.empty:
                # Ancient companies (e.g. TATAPOWER) fail with period='max' due to pre-1950 incorporation date
                logger.info("Retrying with start='1996-01-01' fallback for %s...", ticker)
                df = yf_ticker.history(
                    start="1996-01-01",
                    end=end_date,
                    auto_adjust=self.config.auto_adjust,
                    actions=True,
                )
            if end_date and not df.empty:
                df = df[df.index <= pd.to_datetime(end_date)]

        if df.empty:
            logger.warning("No OHLCV data returned for %s", ticker)
            return pd.DataFrame()


        # Reset index to have 'Date' as a column and ensure timezone-naive UTC date
        df = df.reset_index()
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
            df["Date"] = pd.to_datetime(df["Date"].dt.date)

        # Standardize columns
        expected_cols = ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
        for col in expected_cols:
            if col not in df.columns:
                if col == "Adj Close" and "Close" in df.columns:
                    df["Adj Close"] = df["Close"]
                elif col in ["Dividends", "Stock Splits"]:
                    df[col] = 0.0
                else:
                    df[col] = np.nan

        df = df[expected_cols].sort_values("Date").reset_index(drop=True)

        try:
            if cache_file.exists():
                try:
                    old_df = pd.read_parquet(cache_file)
                    old_df["Date"] = pd.to_datetime(old_df["Date"])
                    merged = pd.concat([old_df, df], ignore_index=True).drop_duplicates(subset=["Date"], keep="last")
                    merged = merged.sort_values("Date").reset_index(drop=True)
                    merged.to_parquet(cache_file, index=False)
                    saved_df = merged
                    logger.info("Merged and saved %s OHLCV to cache: %s (total rows: %d)", ticker, cache_file, len(merged))
                except Exception:
                    df.to_parquet(cache_file, index=False)
                    saved_df = df
            else:
                df.to_parquet(cache_file, index=False)
                saved_df = df
                logger.info("Saved %s OHLCV to cache: %s (rows: %d)", ticker, cache_file, len(df))

            # Write metadata
            meta_data = {
                "ticker": ticker,
                "is_max_history": is_max_request or cache_meta_file.exists(),
                "first_date": str(saved_df["Date"].min().date()),
                "last_date": str(saved_df["Date"].max().date()),
                "total_rows": len(saved_df),
            }
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, indent=2)

        except Exception as e:
            logger.warning("Could not write cache file %s: %s", cache_file, e)

        if start_date and not is_max_request:
            req_start = pd.to_datetime(start_date)
            filtered = df[df["Date"] >= req_start]
            if end_date:
                filtered = filtered[filtered["Date"] <= pd.to_datetime(end_date)]
            return filtered.reset_index(drop=True)

        return df.reset_index(drop=True)

    def load_benchmark(
        self,
        benchmark_ticker: str = "^NSEI",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "max",
        force_reload: bool = False,
        prefix: str = "Benchmark_",
    ) -> pd.DataFrame:
        """Loads benchmark index data (e.g. NIFTY 50, NIFTY 500)."""
        df = self.load_ohlcv(benchmark_ticker, start_date=start_date, end_date=end_date, period=period, force_reload=force_reload)
        if not df.empty:
            rename_map = {
                "Open": f"{prefix}Open",
                "High": f"{prefix}High",
                "Low": f"{prefix}Low",
                "Close": f"{prefix}Close",
                "Adj Close": f"{prefix}Adj_Close",
                "Volume": f"{prefix}Volume",
            }
            df = df.rename(columns=rename_map)[["Date"] + list(rename_map.values())]
        return df

    def load_sector(
        self,
        sector_ticker: Optional[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "max",
        force_reload: bool = False,
        prefix: str = "Sector_",
    ) -> pd.DataFrame:
        """Loads sectoral index data (e.g. ^CNXIT, ^NSEBANK)."""
        if not sector_ticker:
            return pd.DataFrame()

        df = self.load_ohlcv(sector_ticker, start_date=start_date, end_date=end_date, period=period, force_reload=force_reload)
        if not df.empty:
            rename_map = {
                "Open": f"{prefix}Open",
                "High": f"{prefix}High",
                "Low": f"{prefix}Low",
                "Close": f"{prefix}Close",
                "Adj Close": f"{prefix}Adj_Close",
                "Volume": f"{prefix}Volume",
            }
            df = df.rename(columns=rename_map)[["Date"] + list(rename_map.values())]
        return df

    def load_fundamentals(
        self,
        ticker: str,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """Loads quarterly financial statements and snapshot valuation ratios."""
        safe_ticker = _sanitize_ticker(ticker)
        cache_file = self.cache_dir / f"{safe_ticker}_fundamentals.json"

        if not force_reload and cache_file.exists():
            logger.info("Loading cached fundamentals for %s from %s", ticker, cache_file)
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to read cached fundamentals %s: %s", cache_file, e)

        logger.info("Fetching fundamentals for %s from Yahoo Finance...", ticker)
        yf_ticker = yf.Ticker(ticker)

        # 1. Quarterly Income Statement
        quarterly_income = {}
        try:
            qf = yf_ticker.quarterly_financials
            if qf is not None and not qf.empty:
                for date_col in qf.columns:
                    date_str = str(pd.to_datetime(date_col).date())
                    col_data = qf[date_col].to_dict()
                    quarterly_income[date_str] = {
                        "Total Revenue": col_data.get("Total Revenue") or col_data.get("Operating Revenue"),
                        "Net Income": col_data.get("Net Income") or col_data.get("Net Income Common Stockholders"),
                        "Diluted EPS": col_data.get("Diluted EPS") or col_data.get("Basic EPS"),
                        "Operating Income": col_data.get("Operating Income"),
                    }
        except Exception as e:
            logger.warning("Could not fetch quarterly financials for %s: %s", ticker, e)

        # 2. Quarterly Balance Sheet
        quarterly_balance = {}
        try:
            qbs = yf_ticker.quarterly_balance_sheet
            if qbs is not None and not qbs.empty:
                for date_col in qbs.columns:
                    date_str = str(pd.to_datetime(date_col).date())
                    col_data = qbs[date_col].to_dict()
                    quarterly_balance[date_str] = {
                        "Total Debt": col_data.get("Total Debt"),
                        "Stockholders Equity": col_data.get("Stockholders Equity") or col_data.get("Common Stock Equity"),
                        "Cash And Cash Equivalents": col_data.get("Cash And Cash Equivalents") or col_data.get("Cash Financial"),
                    }
        except Exception as e:
            logger.warning("Could not fetch quarterly balance sheet for %s: %s", ticker, e)

        # 3. Quarterly Cashflow
        quarterly_cashflow = {}
        try:
            qcf = yf_ticker.quarterly_cashflow
            if qcf is not None and not qcf.empty:
                for date_col in qcf.columns:
                    date_str = str(pd.to_datetime(date_col).date())
                    col_data = qcf[date_col].to_dict()
                    quarterly_cashflow[date_str] = {
                        "Operating Cash Flow": col_data.get("Operating Cash Flow"),
                        "Capital Expenditure": col_data.get("Capital Expenditure"),
                        "Free Cash Flow": col_data.get("Free Cash Flow"),
                    }
        except Exception as e:
            logger.warning("Could not fetch quarterly cashflow for %s: %s", ticker, e)

        # 4. Info snapshot ratios
        info_ratios = {}
        try:
            info = yf_ticker.info or {}
            info_ratios = {
                "trailingPE": info.get("trailingPE"),
                "forwardPE": info.get("forwardPE"),
                "priceToBook": info.get("priceToBook"),
                "returnOnEquity": info.get("returnOnEquity"),
                "marketCap": info.get("marketCap"),
                "debtToEquity": info.get("debtToEquity"),
                "dividendYield": info.get("dividendYield"),
                "trailingEps": info.get("trailingEps"),
                "bookValue": info.get("bookValue"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
        except Exception as e:
            logger.warning("Could not fetch info ratios for %s: %s", ticker, e)

        fundamentals = {
            "ticker": ticker,
            "quarterly_income": quarterly_income,
            "quarterly_balance": quarterly_balance,
            "quarterly_cashflow": quarterly_cashflow,
            "info_ratios": info_ratios,
        }

        def _clean_json(obj):
            if isinstance(obj, dict):
                return {k: _clean_json(v) for k, v in obj.items()}
            elif isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64)):
                return None if np.isnan(obj) else float(obj)
            elif pd.isna(obj):
                return None
            return obj

        clean_fundamentals = _clean_json(fundamentals)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(clean_fundamentals, f, indent=2)
            logger.info("Saved fundamentals for %s to cache: %s", ticker, cache_file)
        except Exception as e:
            logger.warning("Could not cache fundamentals to %s: %s", cache_file, e)

        return clean_fundamentals

    def load_news(
        self,
        ticker: str,
        force_reload: bool = False,
    ) -> List[Dict[str, Any]]:
        """Loads available news items for a ticker."""
        safe_ticker = _sanitize_ticker(ticker)
        cache_file = self.cache_dir / f"{safe_ticker}_news.json"

        if not force_reload and cache_file.exists():
            logger.info("Loading cached news for %s from %s", ticker, cache_file)
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to read cached news %s: %s", cache_file, e)

        logger.info("Fetching news for %s from Yahoo Finance...", ticker)
        yf_ticker = yf.Ticker(ticker)
        parsed_news: List[Dict[str, Any]] = []

        try:
            raw_news = yf_ticker.news or []
            for item in raw_news:
                content = item.get("content", {})
                title = content.get("title") or item.get("title", "")
                summary = content.get("summary") or content.get("description") or item.get("summary", "")
                pub_date_raw = content.get("pubDate") or item.get("providerPublishTime")

                pub_date = None
                if pub_date_raw:
                    try:
                        if isinstance(pub_date_raw, (int, float)):
                            pub_date = str(pd.to_datetime(pub_date_raw, unit="s").tz_localize(None).date())
                        else:
                            pub_date = str(pd.to_datetime(pub_date_raw).tz_localize(None).date())
                    except Exception:
                        pass

                if title:
                    parsed_news.append({
                        "id": item.get("id"),
                        "date": pub_date,
                        "title": title,
                        "summary": summary,
                    })
        except Exception as e:
            logger.warning("Could not fetch news for %s: %s", ticker, e)

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(parsed_news, f, indent=2)
            logger.info("Saved %d news items for %s to cache: %s", len(parsed_news), ticker, cache_file)
        except Exception as e:
            logger.warning("Could not cache news to %s: %s", cache_file, e)

        return parsed_news
