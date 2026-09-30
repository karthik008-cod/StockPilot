"""Configuration management for StockPilot pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml


@dataclass
class MarketConfig:
    benchmark_ticker: str = "^NSEI"            # Primary large-cap benchmark (NIFTY 50)
    broad_benchmark_ticker: str = "^CRSLDX"    # Broad-market benchmark (NIFTY 500)
    index_tier: str = "NIFTY 100"              # Target constituent tier
    benchmark_tickers: List[str] = field(default_factory=lambda: [
        "^NSEI", "^CNX100", "^CNX200", "^CRSLDX", "^NSMIDCP"
    ])
    default_tickers: List[str] = field(default_factory=lambda: [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"
    ])
    sector_map: Dict[str, str] = field(default_factory=lambda: {
        "RELIANCE.NS": "^CNXENERGY",
        "TCS.NS": "^CNXIT",
        "INFY.NS": "^CNXIT",
        "HDFCBANK.NS": "^NSEBANK",
        "ICICIBANK.NS": "^NSEBANK",
    })
    start_date: str = "2019-01-01"
    end_date: Optional[str] = None

    def get_sector_for_ticker(self, ticker: str) -> Optional[str]:
        """Resolves the sectoral index symbol for a given stock ticker."""
        if ticker in self.sector_map:
            return self.sector_map[ticker]
        from stockpilot.universe import universe
        stock = universe.get_stock(ticker)
        if stock and stock.get("sector"):
            return universe.get_sector_ticker(stock["sector"])
        return None



@dataclass
class DataConfig:
    cache_dir: str = "data/raw"
    processed_dir: str = "data/processed"
    scalers_dir: str = "data/scalers"
    fundamental_lag_days: int = 45
    auto_adjust: bool = False


@dataclass
class FeatureConfig:
    returns_horizons: List[int] = field(default_factory=lambda: [1, 5, 21])
    volatility_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    sma_windows: List[int] = field(default_factory=lambda: [20, 50, 200])
    ema_windows: List[int] = field(default_factory=lambda: [12, 26, 50])
    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_window: int = 20
    bb_std: float = 2.0
    atr_window: int = 14
    adx_window: int = 14
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth_k: int = 3
    rvol_window: int = 20
    extremes_52w_window: int = 252
    beta_window: int = 60


@dataclass
class MLConfig:
    target_horizons: List[int] = field(default_factory=lambda: [5, 10, 20])
    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    embargo_days: int = 20
    scaler_method: str = "robust"


@dataclass
class PipelineConfig:
    market: MarketConfig = field(default_factory=MarketConfig)
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    ml: MLConfig = field(default_factory=MLConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PipelineConfig":
        path = Path(path)
        if not path.exists():
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        market_dict = raw.get("market", {})
        data_dict = raw.get("data", {})
        feat_dict = raw.get("features", {})
        ml_dict = raw.get("ml", {})

        market = MarketConfig(
            benchmark_ticker=market_dict.get("benchmark_ticker", "^NSEI"),
            default_tickers=market_dict.get("default_tickers", ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"]),
            sector_map=market_dict.get("sector_map", {}),
            start_date=market_dict.get("start_date", "2019-01-01"),
            end_date=market_dict.get("end_date", None),
        )

        data = DataConfig(
            cache_dir=data_dict.get("cache_dir", "data/raw"),
            processed_dir=data_dict.get("processed_dir", "data/processed"),
            scalers_dir=data_dict.get("scalers_dir", "data/scalers"),
            fundamental_lag_days=data_dict.get("fundamental_lag_days", 45),
            auto_adjust=data_dict.get("auto_adjust", False),
        )

        features = FeatureConfig(
            returns_horizons=feat_dict.get("returns", {}).get("horizons", [1, 5, 21]),
            volatility_windows=feat_dict.get("volatility", {}).get("windows", [10, 20, 60]),
            sma_windows=feat_dict.get("moving_averages", {}).get("sma_windows", [20, 50, 200]),
            ema_windows=feat_dict.get("moving_averages", {}).get("ema_windows", [12, 26, 50]),
            rsi_window=feat_dict.get("rsi", {}).get("window", 14),
            macd_fast=feat_dict.get("macd", {}).get("fast", 12),
            macd_slow=feat_dict.get("macd", {}).get("slow", 26),
            macd_signal=feat_dict.get("macd", {}).get("signal", 9),
            bb_window=feat_dict.get("bollinger_bands", {}).get("window", 20),
            bb_std=feat_dict.get("bollinger_bands", {}).get("num_std", 2.0),
            atr_window=feat_dict.get("atr", {}).get("window", 14),
            adx_window=feat_dict.get("adx", {}).get("window", 14),
            stoch_k=feat_dict.get("stochastic", {}).get("k_window", 14),
            stoch_d=feat_dict.get("stochastic", {}).get("d_window", 3),
            stoch_smooth_k=feat_dict.get("stochastic", {}).get("smooth_k", 3),
            rvol_window=feat_dict.get("relative_volume", {}).get("window", 20),
            extremes_52w_window=feat_dict.get("extremes_52w", {}).get("window", 252),
            beta_window=feat_dict.get("beta_window", 60),
        )

        ml = MLConfig(
            target_horizons=ml_dict.get("target_horizons", [5, 10, 20]),
            train_ratio=ml_dict.get("split", {}).get("train_ratio", 0.70),
            val_ratio=ml_dict.get("split", {}).get("val_ratio", 0.15),
            test_ratio=ml_dict.get("split", {}).get("test_ratio", 0.15),
            embargo_days=ml_dict.get("split", {}).get("embargo_days", 20),
            scaler_method=ml_dict.get("scaler", {}).get("method", "robust"),
        )

        return cls(market=market, data=data, features=features, ml=ml)
