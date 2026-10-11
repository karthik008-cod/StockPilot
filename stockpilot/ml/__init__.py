"""Machine Learning dataset preparation, regime detection, meta-labeling, and validation."""
from stockpilot.ml.targets import TargetGenerator
from stockpilot.ml.split import TimeSeriesSplitter
from stockpilot.ml.scaler import LeakageFreeScaler
from stockpilot.ml.leakage_audit import LeakageAuditor
from stockpilot.ml.features import FeatureEngineeringPipeline
from stockpilot.ml.labeling import TripleBarrierLabeler
from stockpilot.ml.validation import PurgedTimeSeriesSplit
from stockpilot.ml.models import MarketRegimeDetector, MetaLabelClassifier
from stockpilot.ml.explain import FeatureAttributor
from stockpilot.ml.pipeline import MLEngine, ml_engine

__all__ = [
    "TargetGenerator",
    "TimeSeriesSplitter",
    "LeakageFreeScaler",
    "LeakageAuditor",
    "FeatureEngineeringPipeline",
    "TripleBarrierLabeler",
    "PurgedTimeSeriesSplit",
    "MarketRegimeDetector",
    "MetaLabelClassifier",
    "FeatureAttributor",
    "MLEngine",
    "ml_engine",
]

