"""Integration test for StockPilot end-to-end pipeline execution."""

import unittest
from unittest.mock import MagicMock
import numpy as np
import pandas as pd

from stockpilot.config import PipelineConfig
from stockpilot.pipeline import StockPilotPipeline


class TestPipelineIntegration(unittest.TestCase):

    def setUp(self):
        self.config = PipelineConfig()
        self.config.data.cache_dir = "data/test_raw"
        self.config.data.processed_dir = "data/test_processed"
        self.config.data.scalers_dir = "data/test_scalers"

        np.random.seed(42)
        n = 400
        dates = pd.date_range("2022-01-01", periods=n, freq="B")
        close = 1000.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.012, n)))
        high = close * (1.0 + np.random.uniform(0.002, 0.015, n))
        low = close * (1.0 - np.random.uniform(0.002, 0.015, n))
        open_p = (high + low) / 2.0
        volume = np.random.randint(100000, 2000000, n)

        self.mock_stock_df = pd.DataFrame({
            "Date": dates,
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        })

        self.mock_bench_df = pd.DataFrame({
            "Date": dates,
            "Benchmark_Open": open_p * 1.5,
            "Benchmark_High": high * 1.5,
            "Benchmark_Low": low * 1.5,
            "Benchmark_Close": close * 1.5,
            "Benchmark_Adj_Close": close * 1.5,
            "Benchmark_Volume": volume * 2,
        })

        self.mock_sector_df = pd.DataFrame({
            "Date": dates,
            "Sector_Open": open_p * 0.8,
            "Sector_High": high * 0.8,
            "Sector_Low": low * 0.8,
            "Sector_Close": close * 0.8,
            "Sector_Adj_Close": close * 0.8,
            "Sector_Volume": volume * 1.2,
        })

        self.mock_fundamentals = {
            "ticker": "TEST_TICKER",
            "quarterly_income": {
                "2022-03-31": {"Total Revenue": 10000, "Net Income": 2000, "Diluted EPS": 20},
                "2022-06-30": {"Total Revenue": 11000, "Net Income": 2200, "Diluted EPS": 22},
                "2022-09-30": {"Total Revenue": 11500, "Net Income": 2300, "Diluted EPS": 23},
                "2022-12-31": {"Total Revenue": 12000, "Net Income": 2400, "Diluted EPS": 24},
            },
            "quarterly_balance": {
                "2022-03-31": {"Total Debt": 5000, "Stockholders Equity": 15000},
                "2022-06-30": {"Total Debt": 4800, "Stockholders Equity": 16000},
            },
            "quarterly_cashflow": {},
            "info_ratios": {"trailingPE": 22.5, "priceToBook": 3.2, "marketCap": 50000000},
        }

        self.mock_news = [
            {"id": "1", "date": "2022-05-15", "title": "Record profit surge reported", "summary": "Strong growth"},
            {"id": "2", "date": "2022-08-20", "title": "New contract win boosts outlook", "summary": "Expansion"},
        ]

    def test_pipeline_execution_flow(self):
        pipeline = StockPilotPipeline(self.config)

        pipeline.loader.load_ohlcv = MagicMock(return_value=self.mock_stock_df)
        pipeline.loader.load_benchmark = MagicMock(return_value=self.mock_bench_df)
        pipeline.loader.load_sector = MagicMock(return_value=self.mock_sector_df)
        pipeline.loader.load_fundamentals = MagicMock(return_value=self.mock_fundamentals)
        pipeline.loader.load_news = MagicMock(return_value=self.mock_news)

        output = pipeline.process_ticker(
            "TEST_TICKER",
            export_parquet=True,
            export_csv=True,
            force_reload=True,
        )

        self.assertIsNotNone(output)
        self.assertEqual(output.ticker, "TEST_TICKER")
        self.assertGreater(len(output.train_df), 0)
        self.assertGreater(len(output.val_df), 0)
        self.assertGreater(len(output.test_df), 0)
        self.assertTrue(output.audit_report.passed_all)
        self.assertTrue(output.parquet_path.exists())
        self.assertTrue(output.csv_path.exists())


if __name__ == "__main__":
    unittest.main()
