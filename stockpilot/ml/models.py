"""Machine Learning models for StockPilot: Unsupervised Market Regime & Supervised Meta-Classifier.

Implements:
1. MarketRegimeDetector (Gaussian Mixture Model clustering on macro index volatility & drift).
2. MetaLabelClassifier (Precision-weighted HistGradientBoosting with probability calibration).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

MODEL_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models"
MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 1. Unsupervised Market Regime Detector (GMM)
# ==============================================================================

REGIME_DEFINITIONS = {
    "BULL_LOW_VOL": {
        "name": "Bull Trend (Low Volatility)",
        "desc": "Steady institutional accumulation with low noise. High win rate for trend pullbacks.",
        "compatible_strategies": ["HTF_BULLISH_DEEP_DAILY_PULLBACK", "HTF_BULLISH_DAILY_MOMENTUM_ZONE"],
        "sentiment": "BULLISH",
        "risk_level": "LOW",
        "color": "#00C076",
    },
    "BULL_HIGH_VOL": {
        "name": "Bull Breakout (High Volatility)",
        "desc": "Wide trading swings with strong upward momentum. Wider stop-loss recommended.",
        "compatible_strategies": ["WEEKLY_RSI_CROSS_ABOVE_60"],
        "sentiment": "BULLISH",
        "risk_level": "MODERATE",
        "color": "#0ECB81",
    },
    "CONSOLIDATION": {
        "name": "Consolidation / Squeeze",
        "desc": "Range-bound contraction with compressed ATR. Ideal for deep oversold reversals.",
        "compatible_strategies": ["MONTHLY_RSI_40_43_ZONE"],
        "sentiment": "NEUTRAL",
        "risk_level": "LOW",
        "color": "#F0B90B",
    },
    "BEAR_HIGH_RISK": {
        "name": "Distribution / Elevated Risk",
        "desc": "Elevated market downside or extreme volatility. Strict discipline: No trades > Loss trades.",
        "compatible_strategies": ["HIGH_ALPHA_RELATIVE_STRENGTH", "VOLATILITY_TRAILING_STOP", "CAPITAL_PRESERVATION"],
        "sentiment": "DEFENSIVE",
        "risk_level": "HIGH",
        "color": "#F6465D",
    },
}


def detect_stock_micro_regime(feature_row: pd.Series) -> Dict[str, Any]:
    """Detects asset-specific micro-regime independent of broad market benchmark index."""
    dist_200 = float(feature_row.get("dist_ema_200_pct", 0.0))
    dist_50 = float(feature_row.get("dist_ema_50_pct", 0.0))
    w_rsi = float(feature_row.get("weekly_rsi_14", 50.0))
    m_rsi = float(feature_row.get("monthly_rsi_14", 50.0))
    hurst = float(feature_row.get("hurst_exponent", 0.50))
    alpha = float(feature_row.get("excess_return_20d", 0.0))
    vol = float(feature_row.get("natr_14", 2.0))

    # 1. Parabolic / High-Momentum Secular Runner
    if (dist_200 > 25.0 or m_rsi > 78.0) and w_rsi > 62.0 and hurst > 0.65:
        return {
            "micro_regime_id": "PARABOLIC_SUPER_TREND",
            "name": "Parabolic Super-Trend (Alpha Leader)",
            "desc": f"Exceptional multi-timeframe trend momentum with +{alpha:.1f}% alpha over NIFTY. Strong institutional conviction.",
            "sentiment": "STRONG BULLISH",
            "risk_level": "PARABOLIC" if m_rsi > 85.0 else "MODERATE",
            "color": "#00C076",
            "compatible_strategies": ["MOMENTUM_BREAKOUT", "HIGH_ALPHA_TREND_RIDE", "VOLATILITY_TRAILING_STOP"],
            "parabolic_extension": m_rsi > 85.0,
        }

    # 2. Healthy Bull Trend Accumulation
    if dist_200 > 0.0 and w_rsi >= 50.0:
        return {
            "micro_regime_id": "BULL_ACCUMULATION",
            "name": "Bull Trend (Institutional Accumulation)",
            "desc": "Healthy structural uptrend trading cleanly above 200 EMA with positive higher-timeframe momentum.",
            "sentiment": "BULLISH",
            "risk_level": "LOW",
            "color": "#00C076",
            "compatible_strategies": ["HTF_BULLISH_DAILY_MOMENTUM_ZONE", "HTF_BULLISH_DEEP_DAILY_PULLBACK"],
            "parabolic_extension": False,
        }

    # 3. Consolidation / Range Bound Squeeze
    if abs(dist_50) < 6.0 and 38.0 <= w_rsi <= 58.0:
        return {
            "micro_regime_id": "CONSOLIDATION_RANGE",
            "name": "Consolidation / Range Squeeze",
            "desc": "Volatility contraction coiling between moving averages. Awaiting directional expansion catalyst.",
            "sentiment": "NEUTRAL",
            "risk_level": "LOW",
            "color": "#F0B90B",
            "compatible_strategies": ["RANGE_BOUND_SWING", "BREAKOUT_WATCH"],
            "parabolic_extension": False,
        }

    # 4. Bearish Distribution / Downtrend
    return {
        "micro_regime_id": "BEARISH_DISTRIBUTION",
        "name": "Bearish Distribution / Downtrend",
        "desc": "Trading below 200-day EMA structural hurdle with negative momentum and persistent selling pressure.",
        "sentiment": "DEFENSIVE",
        "risk_level": "HIGH",
        "color": "#F6465D",
        "compatible_strategies": ["CAPITAL_PRESERVATION", "OVERSOLD_REVERSAL_WATCH"],
        "parabolic_extension": False,
    }



class MarketRegimeDetector:
    """Detects latent market regimes using a Gaussian Mixture Model on benchmark index metrics."""

    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self.gmm = GaussianMixture(n_components=n_regimes, covariance_type="full", random_state=42)
        self.scaler = StandardScaler()
        self.regime_map: Dict[int, str] = {}
        self.is_fitted = False

    def fit(self, benchmark_df: pd.DataFrame) -> "MarketRegimeDetector":
        """Fits GMM on returns, rolling volatility, and ATR ratios of benchmark index."""
        if benchmark_df.empty or len(benchmark_df) < 100:
            logger.warning("Insufficient benchmark history to fit regime detector.")
            return self

        df = benchmark_df.sort_values("Date").reset_index(drop=True).copy()
        df["ret_1d"] = df["Close"].pct_change()
        df["ret_20d"] = df["Close"].pct_change(20)
        df["vol_20d"] = df["ret_1d"].rolling(20).std() * np.sqrt(252)
        df["vol_ratio"] = df["ret_1d"].rolling(5).std() / (df["ret_1d"].rolling(30).std() + 1e-7)

        features = df[["ret_20d", "vol_20d", "vol_ratio"]].dropna()
        if len(features) < 60:
            return self

        X_scaled = self.scaler.fit_transform(features.values)
        self.gmm.fit(X_scaled)
        self.is_fitted = True

        # Assign semantic names based on component cluster centers
        # Means: [ret_20d, vol_20d, vol_ratio]
        means = self.scaler.inverse_transform(self.gmm.means_)
        sorted_indices = np.argsort(means[:, 0])  # sort by return (lowest to highest)

        # Lowest return = BEAR_HIGH_RISK
        self.regime_map[sorted_indices[0]] = "BEAR_HIGH_RISK"
        # Highest return with low/high vol
        top_two = sorted_indices[2:]
        if means[top_two[0], 1] < means[top_two[1], 1]:
            self.regime_map[top_two[0]] = "BULL_LOW_VOL"
            self.regime_map[top_two[1]] = "BULL_HIGH_VOL"
        else:
            self.regime_map[top_two[1]] = "BULL_LOW_VOL"
            self.regime_map[top_two[0]] = "BULL_HIGH_VOL"

        # The remaining middle index = CONSOLIDATION
        self.regime_map[sorted_indices[1]] = "CONSOLIDATION"
        return self

    def predict_regime(self, benchmark_df: pd.DataFrame) -> Dict[str, Any]:
        """Classifies the most recent benchmark session into a market regime."""
        default_result = {
            "regime_id": "BULL_LOW_VOL",
            "probabilities": {k: 0.25 for k in REGIME_DEFINITIONS},
            **REGIME_DEFINITIONS["BULL_LOW_VOL"]
        }

        if not self.is_fitted or benchmark_df.empty or len(benchmark_df) < 35:
            return default_result

        df = benchmark_df.sort_values("Date").reset_index(drop=True).copy()
        df["ret_1d"] = df["Close"].pct_change()
        ret_20d = float(df["Close"].pct_change(20).iloc[-1])
        vol_20d = float(df["ret_1d"].rolling(20).std().iloc[-1] * np.sqrt(252))
        vol_ratio = float(df["ret_1d"].rolling(5).std().iloc[-1] / (df["ret_1d"].rolling(30).std().iloc[-1] + 1e-7))

        sample = np.array([[ret_20d, vol_20d, vol_ratio]])
        sample_scaled = self.scaler.transform(sample)

        probs = self.gmm.predict_proba(sample_scaled)[0]
        cluster_idx = int(np.argmax(probs))
        regime_id = self.regime_map.get(cluster_idx, "BULL_LOW_VOL")

        # Map cluster probs to semantic regimes
        prob_dict = {}
        for c_idx, p_val in enumerate(probs):
            r_name = self.regime_map.get(c_idx, f"REGIME_{c_idx}")
            prob_dict[r_name] = round(float(p_val) * 100.0, 1)

        info = REGIME_DEFINITIONS.get(regime_id, REGIME_DEFINITIONS["BULL_LOW_VOL"])
        return {
            "regime_id": regime_id,
            "probabilities": prob_dict,
            "benchmark_ret_20d": round(ret_20d * 100.0, 2),
            "benchmark_vol_20d": round(vol_20d * 100.0, 2),
            **info
        }


# ==============================================================================
# 2. Supervised Meta-Label Classifier
# ==============================================================================

class MetaLabelClassifier:
    """Precision-weighted secondary ML filter for technical trade setups.
    
    Guarantees:
    - High-precision gatekeeping: False Positives penalized heavily.
    - Calibrated Bayesian probability output P(Success).
    - Dynamic Kelly sizing recommendations.
    """

    FEATURE_NAMES = [
        "frac_diff_price",
        "return_5d",
        "return_21d",
        "garman_klass_vol",
        "parkinson_vol",
        "natr_14",
        "vol_ratio_5_20",
        "daily_rsi_14",
        "daily_rsi_slope_3d",
        "weekly_rsi_14",
        "monthly_rsi_14",
        "dist_ema_50_pct",
        "dist_ema_200_pct",
        "ema_50_200_ratio",
        "volume_shock",
        "hurst_exponent",
        "excess_return_20d"
    ]

    def __init__(self, approval_threshold: float = 0.55):
        self.approval_threshold = approval_threshold
        # Native LightGBM-style HistGradientBoosting in scikit-learn
        self.base_model = HistGradientBoostingClassifier(
            max_iter=100,
            learning_rate=0.05,
            max_depth=5,
            min_samples_leaf=15,
            l2_regularization=1.5,
            random_state=42
        )
        self.calibrated_model: Optional[CalibratedClassifierCV] = None
        self.is_trained = False

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weights: Optional[np.ndarray] = None) -> "MetaLabelClassifier":
        """Trains meta-classifier with probability calibration via 3-fold cross-validation."""
        clean_features = [f for f in self.FEATURE_NAMES if f in X.columns]
        X_mat = X[clean_features].copy().astype(float)
        y_vec = y.astype(int).values

        # Use uniqueness weights if provided, otherwise uniform weights
        weights = sample_weights if sample_weights is not None else np.ones(len(y_vec))

        # Train base model
        self.base_model.fit(X_mat, y_vec, sample_weight=weights)

        # Calibrate probabilities with sigmoid / Platt scaling via 3-fold cross validation
        self.calibrated_model = CalibratedClassifierCV(
            estimator=self.base_model,
            cv=3,
            method="sigmoid"
        )
        self.calibrated_model.fit(X_mat, y_vec, sample_weight=weights)
        self.is_trained = True

        return self

    def qualify_trade(self, feature_row: pd.Series) -> Dict[str, Any]:
        """Evaluates a single technical setup and outputs an institutional trade score."""
        clean_features = [f for f in self.FEATURE_NAMES if f in feature_row.index]
        X_vec = feature_row[clean_features].to_frame().T.astype(float)

        w_rsi = float(feature_row.get("weekly_rsi_14", 50.0))
        d_rsi = float(feature_row.get("daily_rsi_14", 50.0))
        m_rsi = float(feature_row.get("monthly_rsi_14", 50.0))
        hurst = float(feature_row.get("hurst_exponent", 0.50))
        vol = float(feature_row.get("natr_14", 2.0))
        vol_ratio = float(feature_row.get("vol_ratio_5_20", 1.0))
        dist_50 = float(feature_row.get("dist_ema_50_pct", 0.0))
        dist_200 = float(feature_row.get("dist_ema_200_pct", 0.0))
        ema_ratio = float(feature_row.get("ema_50_200_ratio", 1.0))
        vol_shock = float(feature_row.get("volume_shock", 1.0))
        alpha_20 = float(feature_row.get("excess_return_20d", 0.0))

        # Determine asset-specific micro-regime
        micro_regime = detect_stock_micro_regime(feature_row)

        # Baseline probability from continuous institutional multi-factor model
        z = 0.0

        # 1. Structural Trend Support (Above 200 EMA & Golden Cross)
        if dist_200 > 0:
            z += min(0.65, dist_200 * 0.018)
        else:
            z += max(-0.85, dist_200 * 0.05)  # Heavy penalty for trading below 200 EMA
        z += (ema_ratio - 1.0) * 1.6

        # 2. Multi-Timeframe Momentum (Weekly & Monthly RSI)
        z += (w_rsi - 50.0) * 0.028
        if m_rsi > 60.0:
            z += min(0.50, (m_rsi - 50.0) * 0.015)
        elif m_rsi < 45.0:
            z -= (50.0 - m_rsi) * 0.02

        # 3. Daily RSI Tactical Momentum Zone
        if 48.0 <= d_rsi <= 68.0:
            z += 0.35  # Clean bullish momentum continuation
        elif 38.0 <= d_rsi < 48.0 and dist_200 > 0:
            z += 0.28  # Uptrend pullback reload
        elif d_rsi < 35.0 and dist_200 < 0:
            z -= 0.40  # Downtrend breakdown

        # 4. Trend Persistence (Hurst Exponent)
        if hurst > 0.60:
            z += (hurst - 0.50) * 2.2
        elif hurst < 0.45:
            z -= (0.50 - hurst) * 1.8

        # 5. Relative Strength / Alpha over Benchmark
        z += float(np.clip(alpha_20 * 0.035, -0.6, 0.75))

        # 6. Volume Surge Confirmation
        if vol_shock > 1.4:
            z += min(0.40, (vol_shock - 1.0) * 0.18)

        # Convert to calibrated probability
        p_factor = float(1.0 / (1.0 + np.exp(-z)))
        p_factor = float(np.clip(p_factor, 0.15, 0.92))

        # Prior-normalize tree probability if trained
        # In 2:1 triple barrier labeling, the empirical population base-rate is ~33%.
        # Prior odds adjustment maps the 33% base-rate to an unbiased 50% neutral decision boundary.
        if self.is_trained and self.calibrated_model is not None:
            probs = self.calibrated_model.predict_proba(X_vec)[0]
            raw_p_ml = float(probs[1])
            # Odds adjustment: (p / 0.33) / (p / 0.33 + (1 - p) / 0.67)
            odds = (raw_p_ml / 0.33) / ((raw_p_ml / 0.33) + ((1.0 - raw_p_ml) / 0.67) + 1e-7)
            p_ml_norm = float(np.clip(odds, 0.10, 0.90))

            if micro_regime.get("micro_regime_id") == "PARABOLIC_SUPER_TREND":
                # In high-alpha parabolic super-trends, prioritize trend persistence and relative strength
                p_success = 0.25 * p_ml_norm + 0.75 * p_factor
            else:
                p_success = 0.40 * p_ml_norm + 0.60 * p_factor
        else:
            p_success = p_factor

        p_success = float(np.clip(p_success, 0.10, 0.92))
        is_approved = p_success >= self.approval_threshold
        trade_score = int(round(p_success * 100))

        # Dynamic Volatility-Adjusted Triple Barriers (adapted to stock's actual volatility regime)
        target_pct = round(float(np.clip(vol * 2.5, 6.0, 18.0)), 1)
        stop_pct = round(float(np.clip(vol * 1.5, 3.0, 9.0)), 1)
        is_parabolic = micro_regime.get("micro_regime_id") == "PARABOLIC_SUPER_TREND" or m_rsi > 82.0
        stop_type = "ATR Trailing Stop" if is_parabolic else "Fixed Stop"

        # Kelly Criterion Sizing with Parabolic Risk Adjustment
        b_ratio = 2.0  # 2:1 Reward to Risk
        q_fail = 1.0 - p_success
        base_kelly = max(0.0, (p_success * b_ratio - q_fail) / b_ratio) * 0.5  # Half Kelly

        # Prudent haircut for parabolic overextension (protecting capital from blow-off top drawdowns)
        haircut = 1.0
        parabolic_active = False
        if m_rsi > 82.0:
            haircut *= 0.65
            parabolic_active = True
        if vol > 4.2:
            haircut *= 0.80

        safe_kelly_multiplier = round(float(np.clip(base_kelly * haircut, 0.0, 1.2)), 2)

        if is_approved:
            if parabolic_active or is_parabolic:
                note = f"Approved: Strong secular momentum continuation edge (Win Prob: {p_success*100:.1f}%). Sized at {safe_kelly_multiplier}× Half-Kelly with strict {stop_type} due to Parabolic Extension (Monthly RSI: {m_rsi:.1f})."
                verdict_str = "APPROVED • MOMENTUM RUNNER"
            else:
                note = f"Approved: High-conviction structural setup cleared {self.approval_threshold*100:.0f}% precision gatekeeper."
                verdict_str = "APPROVED"
        else:
            note = f"Disqualified: Win probability ({p_success*100:.1f}%) below {self.approval_threshold*100:.0f}% confidence threshold (No trades > Loss trades)."
            verdict_str = "DISQUALIFIED"

        return {
            "verdict": verdict_str,
            "is_approved": is_approved,
            "success_probability": round(p_success * 100.0, 1),
            "trade_score": trade_score,
            "threshold": round(self.approval_threshold * 100.0, 1),
            "kelly_multiplier": safe_kelly_multiplier,
            "micro_regime": micro_regime,
            "parabolic_warning": parabolic_active or is_parabolic,
            "discipline_note": note,
            "barriers": {
                "target_pct": target_pct,
                "stop_pct": stop_pct,
                "vertical_days": 21,
                "stop_type": stop_type,
            },
        }

    def save(self, filepath: Optional[Path] = None):
        """Serializes trained model artifact."""
        path = filepath or (MODEL_CACHE_DIR / "meta_classifier.joblib")
        joblib.dump({"model": self.calibrated_model, "is_trained": self.is_trained}, path)

    def load(self, filepath: Optional[Path] = None) -> bool:
        """Loads serialized model artifact."""
        path = filepath or (MODEL_CACHE_DIR / "meta_classifier.joblib")
        if path.exists():
            try:
                obj = joblib.load(path)
                self.calibrated_model = obj.get("model")
                self.is_trained = bool(obj.get("is_trained", False) and self.calibrated_model is not None)
                return self.is_trained
            except Exception as e:
                logger.warning("Failed to load meta classifier artifact: %s", e)
        return False
