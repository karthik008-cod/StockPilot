"""Master end-to-end data loading and preprocessing pipeline for StockPilot."""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from stockpilot.config import PipelineConfig
from stockpilot.data.loader import DataLoader, _sanitize_ticker
from stockpilot.data.cleaner import DataCleaner
from stockpilot.data.aligner import DataAligner
from stockpilot.features.technical import TechnicalFeatureExtractor
from stockpilot.features.market_relative import MarketRelativeFeatureExtractor
from stockpilot.features.fundamental import FundamentalFeatureExtractor
from stockpilot.features.sentiment import SentimentFeatureExtractor
from stockpilot.ml.targets import TargetGenerator
from stockpilot.ml.split import TimeSeriesSplitter, SplitResult
from stockpilot.ml.scaler import LeakageFreeScaler
from stockpilot.ml.leakage_audit import LeakageAuditor, AuditReport

logger = logging.getLogger(__name__)


@dataclass
class PipelineOutput:
    ticker: str
    full_df: pd.DataFrame
    train_df: pd.DataFrame
    val_df: pd.DataFrame
    test_df: pd.DataFrame
    split_result: SplitResult
    scaler: LeakageFreeScaler
    audit_report: AuditReport
    parquet_path: Optional[Path] = None
    csv_path: Optional[Path] = None


class StockPilotPipeline:
    """End-to-end data loading and preprocessing pipeline for StockPilot."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.loader = DataLoader(self.config.data)
        self.cleaner = DataCleaner()
        self.aligner = DataAligner(fundamental_lag_days=self.config.data.fundamental_lag_days)
        self.tech_extractor = TechnicalFeatureExtractor(self.config.features)
        self.relative_extractor = MarketRelativeFeatureExtractor(self.config.features)
        self.fund_extractor = FundamentalFeatureExtractor()
        self.sent_extractor = SentimentFeatureExtractor()
        self.target_gen = TargetGenerator(self.config.ml)
        self.splitter = TimeSeriesSplitter(self.config.ml)
        self.scaler = LeakageFreeScaler(
            method=self.config.ml.scaler_method,
            save_dir=self.config.data.scalers_dir,
        )
        self.auditor = LeakageAuditor()

        self.processed_dir = Path(self.config.data.processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def print_pipeline_stage(self, stage_name: str):
        logger.info("\n" + "=" * 50)
        logger.info("  STAGE: %s", stage_name)
        logger.info("=" * 50)

    def process_ticker(
        self,
        ticker: str,
        export_parquet: bool = True,
        export_csv: bool = True,
        force_reload: bool = False,
    ) -> PipelineOutput:
        safe_name = _sanitize_ticker(ticker)
        print(f"\n{'#'*60}\n# Processing {ticker} for StockPilot\n{'#'*60}")

        self.print_pipeline_stage("1. RAW DATA LOADING")
        start_date = self.config.market.start_date
        end_date = self.config.market.end_date

        stock_df = self.loader.load_ohlcv(ticker, start_date=start_date, end_date=end_date, force_reload=force_reload)
        if stock_df.empty:
            raise ValueError(f"No OHLCV data found for {ticker}")

        bench_ticker = self.config.market.benchmark_ticker
        bench_df = self.loader.load_benchmark(bench_ticker, start_date=start_date, end_date=end_date, force_reload=force_reload)

        sec_ticker = self.config.market.sector_map.get(ticker)
        sec_df = self.loader.load_sector(sec_ticker, start_date=start_date, end_date=end_date, force_reload=force_reload) if sec_ticker else None

        fundamentals = self.loader.load_fundamentals(ticker, force_reload=force_reload)
        news_items = self.loader.load_news(ticker, force_reload=force_reload)

        print(f"   [OK] Loaded Stock OHLCV: {len(stock_df)} rows")
        print(f"   [OK] Loaded Benchmark ({bench_ticker}): {len(bench_df)} rows")
        print(f"   [OK] Loaded Sector ({sec_ticker or 'None'}): {len(sec_df) if sec_df is not None else 0} rows")
        print(f"   [OK] Loaded Fundamentals: {len(fundamentals.get('quarterly_income', {}))} quarters")
        print(f"   [OK] Loaded News: {len(news_items)} articles")

        self.print_pipeline_stage("2. CLEANING & VALIDATION")
        cleaned_df = self.cleaner.clean_ohlcv(stock_df, ticker_name=ticker)
        if bench_df is not None and not bench_df.empty:
            bench_df = self.cleaner.clean_ohlcv(bench_df, ticker_name=bench_ticker)
        if sec_df is not None and not sec_df.empty:
            sec_df = self.cleaner.clean_ohlcv(sec_df, ticker_name=sec_ticker)

        print(f"   [OK] Cleaned & Validated OHLCV: {len(cleaned_df)} rows (0 invalid ticks)")

        self.print_pipeline_stage("3. MARKET + SECTOR + INDEX ALIGNMENT")
        aligned_df = self.aligner.align_market_data(cleaned_df, benchmark_df=bench_df, sector_df=sec_df)
        print(f"   [OK] Aligned Stock with Benchmark & Sector: {len(aligned_df)} rows")

        self.print_pipeline_stage("4. FUNDAMENTAL DATA ALIGNMENT (POINT-IN-TIME)")
        aligned_df = self.aligner.align_fundamentals(aligned_df, fundamentals)
        print(f"   [OK] Point-in-time fundamentals aligned with {self.config.data.fundamental_lag_days}-day lag")

        self.print_pipeline_stage("5. NEWS / SENTIMENT FEATURES")
        sentiment_daily = self.sent_extractor.process_news_items(news_items)
        aligned_df = self.aligner.align_news_sentiment(aligned_df, sentiment_daily)
        print(f"   [OK] Aggregated and merged news sentiment features")

        self.print_pipeline_stage("6. TECHNICAL INDICATORS")
        feat_df = self.tech_extractor.extract_features(aligned_df)
        print(f"   [OK] Computed SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, OBV, RVOL, 52W Extremes")

        self.print_pipeline_stage("7. RETURNS + VOLATILITY + RELATIVE STRENGTH")
        feat_df = self.relative_extractor.extract_features(feat_df)
        feat_df = self.fund_extractor.extract_features(feat_df)
        print(f"   [OK] Computed Relative Strength vs NIFTY/Sector, Rolling Beta (60d), Correlation, Derived Ratios")

        self.print_pipeline_stage("8. TARGET CREATION")
        model_df = self.target_gen.generate_targets(feat_df)
        print(f"   [OK] Generated 5d, 10d, 20d future return & direction targets (strictly backward-shifted)")

        self.print_pipeline_stage("9. CHRONOLOGICAL TRAIN / VALIDATION / TEST SPLIT")
        clean_model_df = model_df.dropna(subset=["SMA_200", "Dist_52w_High"]).reset_index(drop=True)
        split_res = self.splitter.split(clean_model_df)

        print(f"   [OK] Train set: {len(split_res.train)} rows ({split_res.train_dates[0].date()} to {split_res.train_dates[1].date()})")
        print(f"   [OK] Val set:   {len(split_res.val)} rows ({split_res.val_dates[0].date()} to {split_res.val_dates[1].date()})")
        print(f"   [OK] Test set:  {len(split_res.test)} rows ({split_res.test_dates[0].date()} to {split_res.test_dates[1].date()})")
        print(f"   [OK] Embargo:   {split_res.embargo_days} trading days between splits")

        self.print_pipeline_stage("10. LEAKAGE-FREE FEATURE SCALING")
        train_scaled, val_scaled, test_scaled = self.scaler.fit_transform_splits(
            split_res.train, split_res.val, split_res.test, ticker=safe_name
        )
        full_scaled = self.scaler.transform(clean_model_df)
        print(f"   [OK] Scaler ({self.config.ml.scaler_method}) fitted strictly on Train and applied to all splits")

        self.print_pipeline_stage("11. LEAKAGE AUDIT CHECK")
        audit_report = self.auditor.run_full_audit(
            clean_model_df, split_res, self.scaler, horizons=self.config.ml.target_horizons
        )
        print(audit_report.summary())
        if not audit_report.passed_all:
            raise RuntimeError(f"Leakage audit FAILED for {ticker}! Check logs for details.")

        self.print_pipeline_stage("12. FINAL MODEL-READY DATASET PERSISTENCE")
        parquet_path = None
        csv_path = None

        if export_parquet:
            parquet_path = self.processed_dir / f"{safe_name}_model_ready.parquet"
            full_scaled.to_parquet(parquet_path, index=False)
            train_scaled.to_parquet(self.processed_dir / f"{safe_name}_train.parquet", index=False)
            val_scaled.to_parquet(self.processed_dir / f"{safe_name}_val.parquet", index=False)
            test_scaled.to_parquet(self.processed_dir / f"{safe_name}_test.parquet", index=False)
            print(f"   [OK] Exported Parquet: {parquet_path}")

        if export_csv:
            csv_path = self.processed_dir / f"{safe_name}_model_ready.csv"
            full_scaled.to_csv(csv_path, index=False)
            train_scaled.to_csv(self.processed_dir / f"{safe_name}_train.csv", index=False)
            val_scaled.to_csv(self.processed_dir / f"{safe_name}_val.csv", index=False)
            test_scaled.to_csv(self.processed_dir / f"{safe_name}_test.csv", index=False)
            print(f"   [OK] Exported CSV: {csv_path}")

        metadata = {
            "ticker": ticker,
            "total_rows": len(full_scaled),
            "feature_columns_count": len(self.scaler.feature_columns),
            "feature_columns": self.scaler.feature_columns,
            "target_columns": [c for c in full_scaled.columns if c.startswith("Target_")],
            "train_rows": len(train_scaled),
            "val_rows": len(val_scaled),
            "test_rows": len(test_scaled),
            "train_range": [str(split_res.train_dates[0].date()), str(split_res.train_dates[1].date())],
            "val_range": [str(split_res.val_dates[0].date()), str(split_res.val_dates[1].date())],
            "test_range": [str(split_res.test_dates[0].date()), str(split_res.test_dates[1].date())],
            "audit_passed": audit_report.passed_all,
        }
        meta_path = self.processed_dir / f"{safe_name}_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        print(f"   [OK] Saved metadata: {meta_path}")

        print(f"\n{'='*60}\n Pipeline completed successfully for {ticker}!\n{'='*60}\n")

        return PipelineOutput(
            ticker=ticker,
            full_df=full_scaled,
            train_df=train_scaled,
            val_df=val_scaled,
            test_df=test_scaled,
            split_result=split_res,
            scaler=self.scaler,
            audit_report=audit_report,
            parquet_path=parquet_path,
            csv_path=csv_path,
        )

    def run_all(
        self,
        tickers: Optional[List[str]] = None,
        export_parquet: bool = True,
        export_csv: bool = True,
        force_reload: bool = False,
    ) -> Dict[str, PipelineOutput]:
        target_tickers = tickers or self.config.market.default_tickers
        results = {}
        for ticker in target_tickers:
            try:
                results[ticker] = self.process_ticker(
                    ticker,
                    export_parquet=export_parquet,
                    export_csv=export_csv,
                    force_reload=force_reload,
                )
            except Exception as e:
                logger.error("Failed pipeline processing for %s: %s", ticker, e, exc_info=True)
                print(f"   [!] Error processing {ticker}: {e}")
        return results
