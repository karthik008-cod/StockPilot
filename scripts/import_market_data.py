"""Resilient Multi-Threaded Ingestion & Cleaning Engine for StockPilot.

Downloads complete Day-1 historical OHLCV data for benchmark indices
and constituent stocks across NIFTY 50, 100, 200, and 500 tiers.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stockpilot.universe import universe, BENCHMARK_INDICES, SECTOR_INDICES
from stockpilot.data.loader import DataLoader
from stockpilot.data.cleaner import DataCleaner


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def ingest_ticker(
    ticker: str,
    loader: DataLoader,
    cleaner: DataCleaner,
    period: str = "max",
    force_reload: bool = False,
    is_index: bool = False,
) -> Dict[str, Any]:
    """Ingests, caches, and cleans a single ticker."""
    start_t = time.time()
    result = {
        "ticker": ticker,
        "is_index": is_index,
        "success": False,
        "rows": 0,
        "first_date": None,
        "last_date": None,
        "outlier_days": 0,
        "circuit_days": 0,
        "zero_vol_days": 0,
        "error": None,
        "duration_sec": 0.0,
    }

    try:
        df = loader.load_ohlcv(ticker, period=period, force_reload=force_reload)
        if df.empty:
            result["error"] = "No OHLCV records returned"
            return result

        cleaned = cleaner.clean_ohlcv(df, ticker_name=ticker)
        if cleaned.empty:
            result["error"] = "No valid records after cleaning"
            return result

        result["success"] = True
        result["rows"] = len(cleaned)
        result["first_date"] = str(cleaned["Date"].min().date())
        result["last_date"] = str(cleaned["Date"].max().date())
        result["outlier_days"] = int(cleaned["is_outlier_return"].sum()) if "is_outlier_return" in cleaned.columns else 0
        result["circuit_days"] = int(cleaned["is_circuit_day"].sum()) if "is_circuit_day" in cleaned.columns else 0
        result["zero_vol_days"] = int(cleaned["is_zero_volume"].sum()) if "is_zero_volume" in cleaned.columns else 0
        result["duration_sec"] = round(time.time() - start_t, 2)

    except Exception as e:
        result["error"] = str(e)
        logger.warning("Failed ingestion for %s: %s", ticker, e)

    return result


def main():
    parser = argparse.ArgumentParser(description="StockPilot Resilient Data Ingestion & Cleaning Engine")
    parser.add_argument("--tier", type=str, default="NIFTY 100", choices=["NIFTY 50", "NIFTY 100", "NIFTY 200", "NIFTY 500", "ALL"],
                        help="Constituent tier to ingest (default: NIFTY 100)")
    parser.add_argument("--period", type=str, default="max", help="History period: max (day 1), 5y, 10y, etc.")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent worker threads (default: 5)")
    parser.add_argument("--force-reload", action="store_true", help="Bypass local cache and re-fetch fresh data")
    parser.add_argument("--skip-indices", action="store_true", help="Skip downloading benchmark and sector indices")
    args = parser.parse_args()

    # Safe encoding for Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    loader = DataLoader()
    cleaner = DataCleaner()

    print("\n" + "=" * 70)
    print(" [StockPilot] Market Data Ingestion & Preprocessing Suite")
    print(f" Target Tier:    {args.tier}")
    print(f" History Period: {args.period} (Full Day 1)")
    print(f" Worker Threads: {args.workers}")
    print(f" Force Reload:   {args.force_reload}")
    print("=" * 70 + "\n")

    report_items: List[Dict[str, Any]] = []

    # 1. Benchmark & Sector Indices Ingestion
    if not args.skip_indices:
        indices_to_fetch = list(BENCHMARK_INDICES.values()) + list(set(SECTOR_INDICES.values()))
        seen = set()
        unique_indices = [x for x in indices_to_fetch if not (x in seen or seen.add(x))]

        print(f"[*] Step 1: Ingesting Benchmark & Sector Indices ({len(unique_indices)} indices)...")
        for i, idx_ticker in enumerate(unique_indices, start=1):
            res = ingest_ticker(idx_ticker, loader, cleaner, period=args.period, force_reload=args.force_reload, is_index=True)
            report_items.append(res)
            if res["success"]:
                print(f"   [{i}/{len(unique_indices)}] {idx_ticker:<15} | {res['rows']:>6} rows | {res['first_date']} -> {res['last_date']} | OK ({res['duration_sec']}s)")
            else:
                print(f"   [{i}/{len(unique_indices)}] {idx_ticker:<15} | FAILED: {res['error']}")
            time.sleep(0.1)  # Polite pacing

    # 2. Constituent Stocks Ingestion
    tier_filter = None if args.tier == "ALL" else args.tier
    stocks_meta = universe.get_stocks(index_tier=tier_filter)
    symbols = [s["symbol"] for s in stocks_meta]

    print(f"\n[*] Step 2: Ingesting {args.tier} Constituents ({len(symbols)} stocks)...")

    total_stocks = len(symbols)
    completed_count = 0
    success_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(
                ingest_ticker,
                sym,
                loader,
                cleaner,
                period=args.period,
                force_reload=args.force_reload,
                is_index=False,
            ): sym
            for sym in symbols
        }

        for future in as_completed(future_map):
            completed_count += 1
            res = future.result()
            report_items.append(res)
            sym = res["ticker"]
            meta = universe.get_stock(sym) or {}
            c_name = meta.get("name", sym)[:28]

            if res["success"]:
                success_count += 1
                print(f"   [{completed_count:>3}/{total_stocks}] {sym:<14} | {c_name:<28} | {res['rows']:>6} rows ({res['first_date']} to {res['last_date']}) | Circuits: {res['circuit_days']:>2} | OK")
            else:
                print(f"   [{completed_count:>3}/{total_stocks}] {sym:<14} | {c_name:<28} | FAILED: {res['error']}")

    # 3. Compile and Save Summary Report
    out_dir = Path("data")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / f"ingestion_report_{args.tier.replace(' ', '_').lower()}.json"

    successful_items = [r for r in report_items if r["success"]]
    failed_items = [r for r in report_items if not r["success"]]
    total_rows = sum(r["rows"] for r in successful_items)

    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tier": args.tier,
        "period": args.period,
        "total_attempted": len(report_items),
        "total_successful": len(successful_items),
        "total_failed": len(failed_items),
        "total_historical_rows": total_rows,
        "failed_tickers": [f["ticker"] for f in failed_items],
        "details": report_items,
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 70)
    print(" [+] Ingestion & Cleaning Batch Completed!")
    print(f" Total Attempted:   {len(report_items)}")
    print(f" Successful:        {len(successful_items)}")
    print(f" Failed:            {len(failed_items)}")
    print(f" Total OHLCV Rows:  {total_rows:,}")
    print(f" Audit Report:      {report_file}")
    print("=" * 70 + "\n")



if __name__ == "__main__":
    main()
