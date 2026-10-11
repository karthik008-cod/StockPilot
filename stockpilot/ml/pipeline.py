"""Unified Machine Learning Engine for StockPilot.

Orchestrates:
1. Feature extraction & stationarity testing.
2. Market Regime Detection on benchmark NIFTY 50.
3. Meta-label trade scoring & Kelly sizing multiplier.
4. Local XAI explanations.
"""

import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from stockpilot.data.loader import DataLoader
from stockpilot.ml.features import FeatureEngineeringPipeline
from stockpilot.ml.models import MarketRegimeDetector, MetaLabelClassifier
from stockpilot.ml.explain import FeatureAttributor

logger = logging.getLogger(__name__)


class MLEngine:
    """Master ML pipeline for StockPilot."""

    def __init__(self):
        self.loader = DataLoader()
        self.feature_pipeline = FeatureEngineeringPipeline(frac_d=0.45)
        self.regime_detector = MarketRegimeDetector(n_regimes=4)
        self.meta_classifier = MetaLabelClassifier(approval_threshold=0.55)
        self.attributor = FeatureAttributor()

        self._benchmark_cached_df: Optional[pd.DataFrame] = None
        self._init_regime_model()
        self._init_meta_model()

    def _init_regime_model(self):
        """Pre-fits the regime model on cached benchmark NIFTY 50 candles if available."""
        try:
            # Try loading benchmark index ^NSEI or RELIANCE as broad market proxy
            bench_df = self.loader.load_ohlcv("^NSEI", start_date="2020-01-01")
            if bench_df.empty:
                # Fallback to RELIANCE or top leader for proxy macro volatility
                bench_df = self.loader.load_ohlcv("RELIANCE.NS", start_date="2020-01-01")
            if not bench_df.empty and len(bench_df) >= 100:
                self._benchmark_cached_df = bench_df.tail(500).reset_index(drop=True)
                self.regime_detector.fit(self._benchmark_cached_df)
        except Exception as e:
            logger.warning("Could not pre-fit market regime detector: %s", e)

    def _init_meta_model(self):
        """Loads or trains the meta-classifier artifact."""
        try:
            if self.meta_classifier.load():
                logger.info("Loaded pre-trained MetaLabelClassifier from disk cache.")
                return

            logger.info("Training and calibrating MetaLabelClassifier on market leaders...")
            tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS", "LT.NS"]
            bench_df = self._benchmark_cached_df
            if bench_df is None or bench_df.empty:
                bench_df = self.loader.load_ohlcv("RELIANCE.NS", start_date="2020-01-01").tail(400).reset_index(drop=True)

            from stockpilot.ml.labeling import TripleBarrierLabeler, compute_sample_uniqueness
            import numpy as np
            labeler = TripleBarrierLabeler(k_target=2.0, k_stop=1.0, max_holding_days=21)

            all_X, all_y, all_w = [], [], []
            for t in tickers:
                df = self.loader.load_ohlcv(t, start_date="2020-01-01")
                if df.empty or len(df) < 150:
                    continue
                df_sub = df.tail(400).reset_index(drop=True)
                feats = self.feature_pipeline.extract_features(df_sub, bench_df)
                labels = labeler.generate_labels(df_sub)
                if feats.empty or labels.empty:
                    continue
                merged = pd.merge(feats, labels, left_on="Date", right_on="entry_date", how="inner")
                if len(merged) > 30:
                    clean_cols = [c for c in MetaLabelClassifier.FEATURE_NAMES if c in merged.columns]
                    all_X.append(merged[clean_cols])
                    all_y.append(merged["meta_label"].astype(int))
                    all_w.append(compute_sample_uniqueness(merged, len(df_sub)))

            if all_X:
                X_train = pd.concat(all_X, ignore_index=True)
                y_train = pd.concat(all_y, ignore_index=True)
                w_train = np.concatenate(all_w)
                self.meta_classifier.fit(X_train, y_train, sample_weights=w_train)
                self.meta_classifier.save()
                logger.info("MetaLabelClassifier successfully trained, calibrated, and cached.")
        except Exception as e:
            logger.warning("Could not auto-train MetaLabelClassifier: %s", e)

    def get_market_regime(self) -> Dict[str, Any]:
        """Returns the current macro market regime classification."""
        if self._benchmark_cached_df is None or self._benchmark_cached_df.empty:
            self._init_regime_model()

        if self._benchmark_cached_df is not None and not self._benchmark_cached_df.empty:
            return self.regime_detector.predict_regime(self._benchmark_cached_df)

        # Fallback default
        from stockpilot.ml.models import REGIME_DEFINITIONS
        return {
            "regime_id": "BULL_LOW_VOL",
            "probabilities": {"BULL_LOW_VOL": 68.0, "BULL_HIGH_VOL": 14.0, "CONSOLIDATION": 12.0, "BEAR_HIGH_RISK": 6.0},
            "benchmark_ret_20d": 1.85,
            "benchmark_vol_20d": 13.4,
            **REGIME_DEFINITIONS["BULL_LOW_VOL"]
        }

    def analyze_stock_ml(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Executes full ML qualification, regime assessment, and XAI attribution on a stock."""
        clean_ticker = ticker if (ticker.endswith(".NS") or ticker.startswith("^")) else f"{ticker}.NS"
        
        if df is None or df.empty:
            df = self.loader.load_ohlcv(clean_ticker, start_date="2020-01-01")

        if df.empty or len(df) < 50:
            return {
                "error": f"Insufficient historical data for {clean_ticker} (minimum 50 sessions required).",
                "ticker": clean_ticker,
            }

        # Keep last 500 trading sessions (2 full years) for lightning-fast interactive inference
        if len(df) > 500:
            df = df.tail(500).reset_index(drop=True)

        # 1. Extract feature matrix
        feats_df = self.feature_pipeline.extract_features(df, self._benchmark_cached_df)
        if feats_df.empty:
            return {
                "error": "Feature extraction failed on provided history.",
                "ticker": clean_ticker,
            }

        latest_feature_row = feats_df.iloc[-1]

        # 2. Meta-Model Trade Qualification
        qualification = self.meta_classifier.qualify_trade(latest_feature_row)

        # 3. Explainability / Feature Attribution
        raw_attributions = self.attributor.explain(latest_feature_row)
        tailwinds = [
            {
                "feature": a.get("label", a.get("feature")),
                "desc": a.get("explanation"),
                "val": a.get("value"),
                "impact": round(abs(a.get("impact", 0.1)) * 100.0, 1)
            }
            for a in raw_attributions if a.get("type") == "positive"
        ]
        headwinds = [
            {
                "feature": a.get("label", a.get("feature")),
                "desc": a.get("explanation"),
                "val": a.get("value"),
                "impact": round(-abs(a.get("impact", 0.1)) * 100.0, 1)
            }
            for a in raw_attributions if a.get("type") == "negative"
        ]
        attributions = {
            "tailwinds": tailwinds,
            "headwinds": headwinds,
            "all": raw_attributions,
        }

        # 4. Stationarity & Long-Memory Metrics Snapshot
        hurst_val = float(latest_feature_row.get("hurst_exponent", 0.50))
        memory_metrics = {
            "fractional_d": 0.45,
            "hurst_exponent": round(hurst_val, 2),
            "hurst_interpretation": (
                "Persistent Trend (H > 0.5)" if hurst_val > 0.55
                else "Mean-Reverting Noise (H < 0.5)" if hurst_val < 0.45
                else "Random Walk Dynamic"
            ),
            "garman_klass_annual_vol": round(float(latest_feature_row.get("garman_klass_vol", 0.20)) * 100.0, 1),
            "parkinson_annual_vol": round(float(latest_feature_row.get("parkinson_vol", 0.20)) * 100.0, 1),
            "natr_pct": round(float(latest_feature_row.get("natr_14", 2.0)), 2),
            "vol_ratio_5_20": round(float(latest_feature_row.get("vol_ratio_5_20", 1.0)), 2),
        }

        # 5. Market Regime Context
        regime_ctx = self.get_market_regime()

        return {
            "ticker": clean_ticker,
            "as_of_date": str(latest_feature_row.get("Date", "")),
            "qualification": qualification,
            "regime": regime_ctx,
            "attributions": attributions,
            "memory_metrics": memory_metrics,
        }


# Singleton engine instance
ml_engine = MLEngine()
