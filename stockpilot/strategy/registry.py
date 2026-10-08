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

import copy
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from stockpilot.strategy.models import Condition, Operator, StrategyDefinition, Timeframe

logger = logging.getLogger(__name__)

# Active Strategy Registry
STRATEGY_REGISTRY: Dict[str, StrategyDefinition] = {
    STRATEGY_1.strategy_id: copy.deepcopy(STRATEGY_1),
    STRATEGY_2.strategy_id: copy.deepcopy(STRATEGY_2),
    STRATEGY_3.strategy_id: copy.deepcopy(STRATEGY_3),
    STRATEGY_4.strategy_id: copy.deepcopy(STRATEGY_4),
}

# Immutable reference defaults for resetting
DEFAULT_STRATEGIES: Dict[str, StrategyDefinition] = {
    STRATEGY_1.strategy_id: copy.deepcopy(STRATEGY_1),
    STRATEGY_2.strategy_id: copy.deepcopy(STRATEGY_2),
    STRATEGY_3.strategy_id: copy.deepcopy(STRATEGY_3),
    STRATEGY_4.strategy_id: copy.deepcopy(STRATEGY_4),
}

PERSISTENCE_FILE = Path("data/custom_strategies.json")


def _save_persisted_strategies() -> None:
    """Saves custom strategies and customized built-ins to disk."""
    try:
        PERSISTENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        custom_list = []
        customized_builtins = []

        for strat in STRATEGY_REGISTRY.values():
            if not strat.is_builtin:
                custom_list.append(strat.to_dict())
            elif strat.is_customized:
                customized_builtins.append(strat.to_dict())

        payload = {
            "version": 1,
            "custom_strategies": custom_list,
            "customized_builtins": customized_builtins,
        }
        with open(PERSISTENCE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Persisted %d custom and %d customized strategies", len(custom_list), len(customized_builtins))
    except Exception as e:
        logger.error("Failed to persist custom strategies: %s", e)


def _load_persisted_strategies() -> None:
    """Loads custom strategies and customized built-ins from disk."""
    if not PERSISTENCE_FILE.exists():
        return
    try:
        with open(PERSISTENCE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Load customized built-ins
        for c_dict in data.get("customized_builtins", []):
            try:
                strat = StrategyDefinition.from_dict(c_dict)
                strat.is_builtin = True
                strat.is_customized = True
                STRATEGY_REGISTRY[strat.strategy_id] = strat
            except Exception as e:
                logger.warning("Could not load customized built-in %s: %s", c_dict.get("strategy_id"), e)

        # Load custom strategies
        for s_dict in data.get("custom_strategies", []):
            try:
                strat = StrategyDefinition.from_dict(s_dict)
                strat.is_builtin = False
                strat.is_customized = False
                STRATEGY_REGISTRY[strat.strategy_id] = strat
            except Exception as e:
                logger.warning("Could not load custom strategy %s: %s", s_dict.get("strategy_id"), e)

        logger.info("Loaded custom strategies from %s (Total in registry: %d)", PERSISTENCE_FILE, len(STRATEGY_REGISTRY))
    except Exception as e:
        logger.warning("Failed to load custom strategies file: %s", e)


def get_strategy(strategy_id: str) -> Optional[StrategyDefinition]:
    """Retrieves a registered strategy definition by its ID."""
    return STRATEGY_REGISTRY.get(strategy_id.strip().upper())


def list_strategies() -> List[Dict[str, Any]]:
    """Returns a serializable list of all registered strategies."""
    return [strat.to_dict() for strat in STRATEGY_REGISTRY.values()]


def create_custom_strategy(data: Dict[str, Any]) -> StrategyDefinition:
    """Creates a new custom scanner strategy and persists it to disk."""
    name = str(data.get("name", "Custom Scanner")).strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    strat_id = data.get("strategy_id") or f"CUSTOM_{slug}"

    # Ensure uniqueness
    counter = 1
    base_id = strat_id
    while strat_id in STRATEGY_REGISTRY:
        strat_id = f"{base_id}_{counter}"
        counter += 1

    payload = dict(data)
    payload["strategy_id"] = strat_id
    payload["is_builtin"] = False
    payload["is_customized"] = False

    strat = StrategyDefinition.from_dict(payload)
    if not strat.conditions:
        raise ValueError("A strategy must define at least one valid entry condition.")

    STRATEGY_REGISTRY[strat.strategy_id] = strat
    _save_persisted_strategies()
    return strat


def update_strategy(strategy_id: str, data: Dict[str, Any]) -> StrategyDefinition:
    """Updates/customizes an existing strategy (either built-in or custom)."""
    clean_id = strategy_id.strip().upper()
    existing = STRATEGY_REGISTRY.get(clean_id)
    if not existing:
        raise KeyError(f"Strategy '{clean_id}' does not exist.")

    payload = dict(data)
    payload["strategy_id"] = clean_id
    payload["is_builtin"] = existing.is_builtin

    if existing.is_builtin:
        payload["is_customized"] = True
    else:
        payload["is_customized"] = False

    updated = StrategyDefinition.from_dict(payload)
    if not updated.conditions:
        raise ValueError("A strategy must define at least one valid entry condition.")

    STRATEGY_REGISTRY[clean_id] = updated
    _save_persisted_strategies()
    return updated


def delete_strategy(strategy_id: str) -> bool:
    """Deletes a custom strategy. Built-in strategies cannot be deleted (only reset)."""
    clean_id = strategy_id.strip().upper()
    existing = STRATEGY_REGISTRY.get(clean_id)
    if not existing:
        raise KeyError(f"Strategy '{clean_id}' not found.")

    if existing.is_builtin:
        raise ValueError(f"Cannot delete built-in strategy '{clean_id}'. Use reset_strategy instead.")

    del STRATEGY_REGISTRY[clean_id]
    _save_persisted_strategies()
    return True


def reset_strategy(strategy_id: str) -> StrategyDefinition:
    """Resets a customized built-in strategy back to its default specification."""
    clean_id = strategy_id.strip().upper()
    default_strat = DEFAULT_STRATEGIES.get(clean_id)
    if not default_strat:
        raise ValueError(f"Strategy '{clean_id}' is not a built-in strategy or has no default.")

    # Restore default copy
    restored = copy.deepcopy(default_strat)
    restored.is_builtin = True
    restored.is_customized = False
    STRATEGY_REGISTRY[clean_id] = restored
    _save_persisted_strategies()
    return restored


# Auto-load persisted strategies upon module import
_load_persisted_strategies()
