"""Declarative models and data structures for the StockPilot Strategy Scanner Engine."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd


class Timeframe(str, Enum):
    """Supported technical analysis timeframes."""
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class Operator(str, Enum):
    """Comparison and event operators."""
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    EQ = "=="
    BETWEEN = "between"
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"


@dataclass
class Condition:
    """Declarative specification of an indicator entry/setup condition."""
    timeframe: Timeframe
    indicator: str = "RSI"
    period: int = 14
    operator: Operator = Operator.GT
    value: float = 60.0
    value_high: Optional[float] = None  # For BETWEEN operator
    shift: int = 0  # 0 = current/latest candle, 1 = 1 candle ago
    description: str = ""

    def evaluate(self, current_val: float, prev_val: Optional[float] = None) -> tuple[bool, str]:
        """Evaluates condition against actual indicator values.
        
        Returns:
            (passed, detail_str)
        """
        if current_val is None or np.isnan(current_val):
            return False, "Indicator value is NaN"

        op = self.operator
        if op == Operator.GT:
            passed = current_val > self.value
            return passed, f"{current_val:.2f} > {self.value}"
        elif op == Operator.LT:
            passed = current_val < self.value
            return passed, f"{current_val:.2f} < {self.value}"
        elif op == Operator.GTE:
            passed = current_val >= self.value
            return passed, f"{current_val:.2f} >= {self.value}"
        elif op == Operator.LTE:
            passed = current_val <= self.value
            return passed, f"{current_val:.2f} <= {self.value}"
        elif op == Operator.EQ:
            passed = np.isclose(current_val, self.value, atol=0.01)
            return passed, f"{current_val:.2f} == {self.value}"
        elif op == Operator.BETWEEN:
            low = min(self.value, self.value_high if self.value_high is not None else self.value)
            high = max(self.value, self.value_high if self.value_high is not None else self.value)
            passed = low <= current_val <= high
            return passed, f"{low} <= {current_val:.2f} <= {high}"
        elif op == Operator.CROSS_ABOVE:
            if prev_val is None or np.isnan(prev_val):
                return False, f"Prev value missing for cross_above {self.value}"
            passed = (current_val > self.value) and (prev_val <= self.value)
            return passed, f"Cross above {self.value} (prev: {prev_val:.2f}, curr: {current_val:.2f})"
        elif op == Operator.CROSS_BELOW:
            if prev_val is None or np.isnan(prev_val):
                return False, f"Prev value missing for cross_below {self.value}"
            passed = (current_val < self.value) and (prev_val >= self.value)
            return passed, f"Cross below {self.value} (prev: {prev_val:.2f}, curr: {current_val:.2f})"

        return False, f"Unknown operator {op}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe.value,
            "indicator": self.indicator,
            "period": self.period,
            "operator": self.operator.value,
            "value": self.value,
            "value_high": self.value_high,
            "shift": self.shift,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Condition":
        """Deserializes Condition from dictionary."""
        tf_raw = str(d.get("timeframe", "DAILY")).strip().upper()
        timeframe = Timeframe(tf_raw) if tf_raw in [t.value for t in Timeframe] else Timeframe.DAILY

        op_raw = str(d.get("operator", ">")).strip().lower()
        operator = Operator.GT
        for op in Operator:
            if op.value.lower() == op_raw or op.name.lower() == op_raw:
                operator = op
                break

        val = float(d.get("value", 50.0))
        val_high = float(d["value_high"]) if d.get("value_high") is not None else None

        desc = d.get("description", "")
        if not desc:
            ind_name = f"{d.get('indicator', 'RSI')}({d.get('period', 14)})"
            if operator == Operator.BETWEEN and val_high is not None:
                desc = f"{timeframe.value} {ind_name} between {val} and {val_high}"
            else:
                desc = f"{timeframe.value} {ind_name} {operator.value} {val}"

        return cls(
            timeframe=timeframe,
            indicator=str(d.get("indicator", "RSI")).upper(),
            period=int(d.get("period", 14)),
            operator=operator,
            value=val,
            value_high=val_high,
            shift=int(d.get("shift", 0)),
            description=desc,
        )


@dataclass
class ConditionEvidence:
    """Audit evidence for a single condition evaluation."""
    condition_desc: str
    timeframe: str
    indicator: str
    operator: str
    threshold: float
    threshold_high: Optional[float] = None
    actual_value: float = 0.0
    previous_value: Optional[float] = None
    passed: bool = False
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["condition"] = self.condition_desc
        d["actual"] = round(self.actual_value, 2)
        return d


@dataclass
class StrategyDefinition:
    """Declarative specification of a trading/scanner strategy."""
    strategy_id: str
    name: str
    description: str
    universe: str  # Default universe: "NIFTY 50", "NIFTY 200", "NIFTY 500", "ALL"
    conditions: List[Condition]
    required_timeframes: List[Timeframe] = field(default_factory=list)
    required_indicators: List[str] = field(default_factory=lambda: ["RSI"])
    purpose: str = ""
    is_builtin: bool = True
    is_customized: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "universe": self.universe,
            "purpose": self.purpose,
            "is_builtin": self.is_builtin,
            "is_customized": self.is_customized,
            "required_timeframes": [t.value for t in self.required_timeframes],
            "required_indicators": self.required_indicators,
            "conditions": [c.to_dict() for c in self.conditions],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StrategyDefinition":
        """Deserializes StrategyDefinition from dictionary."""
        conds = [Condition.from_dict(c) for c in d.get("conditions", [])]
        req_tf = list({c.timeframe for c in conds})
        req_ind = list({c.indicator for c in conds})
        return cls(
            strategy_id=str(d.get("strategy_id", "")).strip().upper(),
            name=str(d.get("name", "Custom Strategy")).strip(),
            description=str(d.get("description", "")).strip(),
            universe=str(d.get("universe", "NIFTY 500")).strip(),
            conditions=conds,
            required_timeframes=req_tf,
            required_indicators=req_ind or ["RSI"],
            purpose=str(d.get("purpose", d.get("description", ""))).strip(),
            is_builtin=bool(d.get("is_builtin", False)),
            is_customized=bool(d.get("is_customized", False)),
        )


@dataclass
class ScanCandidate:
    """Audit evidence and metrics for a stock evaluated by a strategy."""
    symbol: str
    company_name: str
    sector: str
    strategy_id: str
    strategy_name: str
    universe: str
    as_of_date: str
    passed: bool
    indicators: Dict[str, Any] = field(default_factory=dict)
    conditions: List[ConditionEvidence] = field(default_factory=list)
    trade_levels: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["conditions"] = [c.to_dict() if hasattr(c, "to_dict") else c for c in self.conditions]
        return res
