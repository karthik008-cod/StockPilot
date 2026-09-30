"""Comprehensive NIFTY 50 constituent metadata (backed by UniverseManager)."""

from typing import Dict, List
from stockpilot.universe import universe

# Dynamic NIFTY 50 list maintained from the official universe registry
NIFTY_50_STOCKS: List[Dict[str, str]] = universe.get_stocks("NIFTY 50")
