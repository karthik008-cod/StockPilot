"""Declarative Registry for the 4 User Recommendation Strategies."""

from typing import Any, Dict, List, Optional

from stockpilot.strategy.models import Condition, Operator, StrategyDefinition, Timeframe

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 1: HIGHER-TIMEFRAME BULLISH + DEEP DAILY PULLBACK
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_1 = StrategyDefinition(
    strategy_id="HTF_BULLISH_DEEP_DAILY_PULLBACK",
    name="HTF Bullish + Deep Daily Pullback",
    description="Identifies stocks with strong monthly and weekly momentum undergoing a sharp short-term daily pullback (RSI 39-45).",
    universe="NIFTY 500",
    purpose=(
        "Searches for stocks showing strong momentum on the higher timeframes (Monthly > 60, Weekly > 60) "
        "while experiencing a considerably weaker short-term daily momentum reading (Daily 39-45). "
        "Represents potential higher-timeframe trend pullback setups."
    ),
    required_timeframes=[Timeframe.MONTHLY, Timeframe.WEEKLY, Timeframe.DAILY],
    required_indicators=["RSI"],
    conditions=[
        Condition(
            timeframe=Timeframe.MONTHLY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=60.0,
            shift=0,
            description="Monthly RSI(14) > 60",
        ),
        Condition(
            timeframe=Timeframe.WEEKLY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=60.0,
            shift=0,
            description="Weekly RSI(14) > 60",
        ),
        Condition(
            timeframe=Timeframe.DAILY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=39.0,
            shift=0,
            description="Daily RSI(14) > 39",
        ),
        Condition(
            timeframe=Timeframe.DAILY,
            indicator="RSI",
            period=14,
            operator=Operator.LT,
            value=45.0,
            shift=0,
            description="Daily RSI(14) < 45",
        ),
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 2: HIGHER-TIMEFRAME BULLISH + MODERATE DAILY MOMENTUM ZONE
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_2 = StrategyDefinition(
    strategy_id="HTF_BULLISH_DAILY_MOMENTUM_ZONE",
    name="HTF Bullish + Daily Momentum Zone",
    description="Identifies stocks with strong monthly and weekly momentum where daily momentum remains relatively strong (RSI 58-63).",
    universe="NIFTY 500",
    purpose=(
        "Searches for stocks with strong higher-timeframe momentum (Monthly > 60, Weekly > 60) "
        "where daily RSI has not fallen deeply but cooled moderately into the 58-63 zone."
    ),
    required_timeframes=[Timeframe.MONTHLY, Timeframe.WEEKLY, Timeframe.DAILY],
    required_indicators=["RSI"],
    conditions=[
        Condition(
            timeframe=Timeframe.MONTHLY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=60.0,
            shift=0,
            description="Monthly RSI(14) > 60",
        ),
        Condition(
            timeframe=Timeframe.WEEKLY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=60.0,
            shift=0,
            description="Weekly RSI(14) > 60",
        ),
        Condition(
            timeframe=Timeframe.DAILY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=58.0,
            shift=0,
            description="Daily RSI(14) > 58",
        ),
        Condition(
            timeframe=Timeframe.DAILY,
            indicator="RSI",
            period=14,
            operator=Operator.LT,
            value=63.0,
            shift=0,
            description="Daily RSI(14) < 63",
        ),
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 3: WEEKLY RSI BULLISH CROSS ABOVE 60
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_3 = StrategyDefinition(
    strategy_id="WEEKLY_RSI_CROSS_ABOVE_60",
    name="Weekly RSI Cross Above 60",
    description="Detects fresh crossover events where Weekly RSI crosses above 60 from at-or-below 60.",
    universe="NIFTY 50",
    purpose=(
        "Detects a fresh momentum breakout event where Weekly RSI crosses above 60 from at-or-below 60, "
        "indicating that the intermediate timeframe has just entered a stronger momentum regime."
    ),
    required_timeframes=[Timeframe.WEEKLY],
    required_indicators=["RSI"],
    conditions=[
        Condition(
            timeframe=Timeframe.WEEKLY,
            indicator="RSI",
            period=14,
            operator=Operator.GT,
            value=60.0,
            shift=0,
            description="Current Weekly RSI(14) > 60",
        ),
        Condition(
            timeframe=Timeframe.WEEKLY,
            indicator="RSI",
            period=14,
            operator=Operator.LTE,
            value=60.0,
            shift=1,
            description="Previous Week RSI(14) <= 60",
        ),
    ],
)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 4: MONTHLY RSI 40–43 ZONE
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_4 = StrategyDefinition(
    strategy_id="MONTHLY_RSI_40_43_ZONE",
    name="Monthly RSI 40–43 Zone",
    description="Identifies stocks whose Monthly RSI lies within the long-term consolidation/support zone (40 <= Monthly RSI <= 43).",
    universe="NIFTY 200",
    purpose=(
        "Identifies stocks whose monthly RSI lies in the 40-43 zone. "
        "Represents potential long-term consolidation or cooling. Note: Not an automatic buy signal."
    ),
    required_timeframes=[Timeframe.MONTHLY],
    required_indicators=["RSI"],
    conditions=[
        Condition(
            timeframe=Timeframe.MONTHLY,
            indicator="RSI",
            period=14,
            operator=Operator.GTE,
            value=40.0,
            shift=0,
            description="Monthly RSI(14) >= 40",
        ),
        Condition(
            timeframe=Timeframe.MONTHLY,
            indicator="RSI",
            period=14,
            operator=Operator.LTE,
            value=43.0,
            shift=0,
            description="Monthly RSI(14) <= 43",
        ),
    ],
)

# Active Strategy Registry
STRATEGY_REGISTRY: Dict[str, StrategyDefinition] = {
    STRATEGY_1.strategy_id: STRATEGY_1,
    STRATEGY_2.strategy_id: STRATEGY_2,
    STRATEGY_3.strategy_id: STRATEGY_3,
    STRATEGY_4.strategy_id: STRATEGY_4,
}


def get_strategy(strategy_id: str) -> Optional[StrategyDefinition]:
    """Retrieves a registered strategy definition by its ID."""
    return STRATEGY_REGISTRY.get(strategy_id.strip().upper())


def list_strategies() -> List[Dict[str, Any]]:
    """Returns a serializable list of all registered strategies."""
    return [strat.to_dict() for strat in STRATEGY_REGISTRY.values()]
