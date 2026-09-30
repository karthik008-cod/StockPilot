"""Multi-asset and point-in-time alignment for StockPilot."""

import logging
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataAligner:
    """Aligns stock market data with benchmark index, sector index,

    point-in-time quarterly fundamentals (lagged to prevent lookahead bias),
    and news sentiment.
    """

    def __init__(self, fundamental_lag_days: int = 45):
        self.fundamental_lag_days = fundamental_lag_days

    def align_market_data(
        self,
        stock_df: pd.DataFrame,
        benchmark_df: Optional[pd.DataFrame] = None,
        sector_df: Optional[pd.DataFrame] = None,
        broad_benchmark_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Aligns stock data with benchmark index (NIFTY 50), broad benchmark (NIFTY 500),

        and sector index on trading dates.
        """
        if stock_df.empty:
            return stock_df

        merged = stock_df.copy()
        merged["Date"] = pd.to_datetime(merged["Date"])

        # Merge primary benchmark (e.g. NIFTY 50)
        if benchmark_df is not None and not benchmark_df.empty:
            bench = benchmark_df.copy()
            bench["Date"] = pd.to_datetime(bench["Date"])
            rename_bench = {}
            for col in bench.columns:
                if col != "Date" and not col.startswith("Benchmark_"):
                    rename_bench[col] = f"Benchmark_{col}"
            if rename_bench:
                bench = bench.rename(columns=rename_bench)

            bench_cols = [c for c in bench.columns if c != "Date"]
            merged = pd.merge(merged, bench, on="Date", how="left")
            merged[bench_cols] = merged[bench_cols].ffill(limit=3)

        # Merge broad market benchmark (e.g. NIFTY 500)
        if broad_benchmark_df is not None and not broad_benchmark_df.empty:
            broad = broad_benchmark_df.copy()
            broad["Date"] = pd.to_datetime(broad["Date"])
            rename_broad = {}
            for col in broad.columns:
                if col != "Date" and not col.startswith("BroadBenchmark_"):
                    rename_broad[col] = f"BroadBenchmark_{col}"
            if rename_broad:
                broad = broad.rename(columns=rename_broad)

            broad_cols = [c for c in broad.columns if c != "Date"]
            merged = pd.merge(merged, broad, on="Date", how="left")
            merged[broad_cols] = merged[broad_cols].ffill(limit=3)

        # Merge sector
        if sector_df is not None and not sector_df.empty:
            sec = sector_df.copy()
            sec["Date"] = pd.to_datetime(sec["Date"])
            rename_sec = {}
            for col in sec.columns:
                if col != "Date" and not col.startswith("Sector_"):
                    rename_sec[col] = f"Sector_{col}"
            if rename_sec:
                sec = sec.rename(columns=rename_sec)

            sec_cols = [c for c in sec.columns if c != "Date"]
            merged = pd.merge(merged, sec, on="Date", how="left")
            merged[sec_cols] = merged[sec_cols].ffill(limit=3)

        return merged.sort_values("Date").reset_index(drop=True)


    def align_fundamentals(
        self,
        daily_df: pd.DataFrame,
        fundamentals: Dict[str, Any],
    ) -> pd.DataFrame:
        """Aligns quarterly fundamentals to daily trading dates point-in-time.

        Applies an announcement lag (default 45 days) to quarter end dates
        to strictly prevent lookahead data leakage.
        """
        if daily_df.empty:
            return daily_df

        df = daily_df.copy()
        df["Date"] = pd.to_datetime(df["Date"])

        q_income = fundamentals.get("quarterly_income", {})
        q_balance = fundamentals.get("quarterly_balance", {})
        q_cashflow = fundamentals.get("quarterly_cashflow", {})
        info_ratios = fundamentals.get("info_ratios", {})

        all_q_dates = sorted(list(set(list(q_income.keys()) + list(q_balance.keys()) + list(q_cashflow.keys()))))

        fund_records = []
        for q_date_str in all_q_dates:
            try:
                q_date = pd.to_datetime(q_date_str)
                effective_date = q_date + pd.Timedelta(days=self.fundamental_lag_days)

                inc = q_income.get(q_date_str, {})
                bal = q_balance.get(q_date_str, {})
                cf = q_cashflow.get(q_date_str, {})

                rev = inc.get("Total Revenue")
                net_inc = inc.get("Net Income")
                eps = inc.get("Diluted EPS")
                debt = bal.get("Total Debt")
                equity = bal.get("Stockholders Equity")
                fcf = cf.get("Free Cash Flow")

                fund_records.append({
                    "effective_date": effective_date,
                    "quarter_end_date": q_date,
                    "Quarterly_Revenue": rev,
                    "Quarterly_Net_Income": net_inc,
                    "Quarterly_EPS": eps,
                    "Total_Debt": debt,
                    "Stockholders_Equity": equity,
                    "Free_Cash_Flow": fcf,
                })
            except Exception as e:
                logger.warning("Error parsing quarterly date %s: %s", q_date_str, e)

        if fund_records:
            fund_df = pd.DataFrame(fund_records).sort_values("effective_date").reset_index(drop=True)
            df = df.sort_values("Date")
            fund_df = fund_df.sort_values("effective_date")

            df = pd.merge_asof(
                df,
                fund_df,
                left_on="Date",
                right_on="effective_date",
                direction="backward",
            )
            if "effective_date" in df.columns:
                df = df.drop(columns=["effective_date", "quarter_end_date"])
        else:
            for col in ["Quarterly_Revenue", "Quarterly_Net_Income", "Quarterly_EPS",
                        "Total_Debt", "Stockholders_Equity", "Free_Cash_Flow"]:
                df[col] = np.nan

        df["PE_Ratio"] = info_ratios.get("trailingPE", np.nan)
        df["PB_Ratio"] = info_ratios.get("priceToBook", np.nan)
        df["ROE"] = info_ratios.get("returnOnEquity", np.nan)
        df["Market_Cap"] = info_ratios.get("marketCap", np.nan)
        df["Debt_To_Equity"] = info_ratios.get("debtToEquity", np.nan)
        df["Dividend_Yield"] = info_ratios.get("dividendYield", np.nan)

        return df

    def align_news_sentiment(
        self,
        daily_df: pd.DataFrame,
        news_sentiment_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Merges daily aggregated news sentiment features with daily market data."""
        if daily_df.empty:
            return daily_df

        df = daily_df.copy()
        df["Date"] = pd.to_datetime(df["Date"])

        if news_sentiment_df is not None and not news_sentiment_df.empty:
            ns = news_sentiment_df.copy()
            ns["Date"] = pd.to_datetime(ns["Date"])
            df = pd.merge(df, ns, on="Date", how="left")

            if "News_Sentiment_Score" in df.columns:
                df["News_Sentiment_Score"] = df["News_Sentiment_Score"].fillna(0.0)
            if "News_Count" in df.columns:
                df["News_Count"] = df["News_Count"].fillna(0.0)
            if "News_Sentiment_5d_Mean" in df.columns:
                df["News_Sentiment_5d_Mean"] = df["News_Sentiment_5d_Mean"].fillna(0.0)
        else:
            df["News_Sentiment_Score"] = 0.0
            df["News_Count"] = 0.0
            df["News_Sentiment_5d_Mean"] = 0.0

        return df
