"""CLI entrypoint to execute the StockPilot Data Loading and Preprocessing Pipeline."""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stockpilot.config import PipelineConfig
from stockpilot.pipeline import StockPilotPipeline


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="StockPilot Data Loading & Preprocessing Pipeline"
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="List of stock tickers to process (e.g. RELIANCE.NS TCS.NS)",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        help="Benchmark index ticker (default: ^NSEI)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/pipeline_config.yaml",
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD (default from config)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: latest)",
    )
    parser.add_argument(
        "--export-parquet",
        action="store_true",
        default=True,
        help="Export processed datasets to Parquet",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        default=True,
        help="Export processed datasets to CSV",
    )
    parser.add_argument(
        "--force-reload",
        action="store_true",
        default=False,
        help="Bypass local cache and re-download from Yahoo Finance",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    config = PipelineConfig.from_yaml(config_path)

    if args.benchmark:
        config.market.benchmark_ticker = args.benchmark
    if args.start:
        config.market.start_date = args.start
    if args.end:
        config.market.end_date = args.end

    target_tickers = args.tickers or config.market.default_tickers

    print("\n" + "=" * 65)
    print(" STOCKPILOT: DATA LOADING & PREPROCESSING PIPELINE")
    print("=" * 65)
    print(f" Tickers to process: {', '.join(target_tickers)}")
    print(f" Benchmark index:    {config.market.benchmark_ticker}")
    print(f" Date range:         {config.market.start_date} to {config.market.end_date or 'Latest'}")
    print(f" Export Parquet:     {args.export_parquet}")
    print(f" Export CSV:         {args.export_csv}")
    print(f" Force reload:       {args.force_reload}")
    print("=" * 65 + "\n")

    pipeline = StockPilotPipeline(config)
    results = pipeline.run_all(
        tickers=target_tickers,
        export_parquet=args.export_parquet,
        export_csv=args.export_csv,
        force_reload=args.force_reload,
    )

    print("\n" + "=" * 65)
    print(" SUMMARY OF PROCESSED DATASETS")
    print("=" * 65)
    for ticker, res in results.items():
        print(f"  - {ticker}:")
        print(f"      Total rows:   {len(res.full_df)} rows")
        print(f"      Train rows:   {len(res.train_df)} rows ({res.split_result.train_dates[0].date()} to {res.split_result.train_dates[1].date()})")
        print(f"      Val rows:     {len(res.val_df)} rows ({res.split_result.val_dates[0].date()} to {res.split_result.val_dates[1].date()})")
        print(f"      Test rows:    {len(res.test_df)} rows ({res.split_result.test_dates[0].date()} to {res.split_result.test_dates[1].date()})")
        print(f"      Embargo:      {res.split_result.embargo_days} trading days")
        print(f"      Features:     {len(res.scaler.feature_columns)} features")
        print(f"      Audit:        {'PASSED [LEAKAGE FREE]' if res.audit_report.passed_all else 'FAILED'}")
        if res.parquet_path:
            print(f"      Parquet:      {res.parquet_path}")
        if res.csv_path:
            print(f"      CSV:          {res.csv_path}")
        print()
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
