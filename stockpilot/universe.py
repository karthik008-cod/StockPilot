"""NIFTY Index and Multi-Tier Universe Manager (NIFTY 50, 100, 200, 500).

Provides access to official benchmark index tickers, sectoral index tickers,
and constituent stock metadata with industry classifications.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import pandas as pd

logger = logging.getLogger(__name__)

# Yahoo Finance Index Tickers
BENCHMARK_INDICES: Dict[str, str] = {
    "NIFTY 50": "^NSEI",
    "NIFTY Next 50": "^NSMIDCP",
    "NIFTY 100": "^CNX100",
    "NIFTY 200": "^CNX200",
    "NIFTY 500": "^CRSLDX",
    "NIFTY Midcap 50": "^NSEMDCP50",
}

SECTOR_INDICES: Dict[str, str] = {
    "Banking": "^NSEBANK",
    "Financial Services": "^NSEBANK",
    "Information Technology": "^CNXIT",
    "Energy": "^CNXENERGY",
    "Oil, Gas & Consumable Fuels": "^CNXENERGY",
    "Automobile": "^CNXAUTO",
    "Healthcare": "^CNXPHARMA",
    "Fast Moving Consumer Goods": "^CNXFMCG",
    "Metals & Mining": "^CNXMETAL",
    "Construction Materials": "^CNXINFRA",
    "Construction": "^CNXINFRA",
    "Telecommunication": "^CNXINFRA",
    "Power": "^CNXENERGY",
    "Consumer Durables": "^CNXFMCG",
    "Consumer Services": "^CNXFMCG",
    "Services": "^CNXINFRA",
    "Capital Goods": "^CNXINFRA",
}

NSE_CSV_URLS = {
    "NIFTY 50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY 100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY 200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "NIFTY 500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
}

DEFAULT_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "universe_nifty500.json"


class UniverseManager:
    """Manages constituent stocks for NIFTY indices with offline caching and dynamic updates."""

    def __init__(self, json_path: Optional[Path] = None):
        self.json_path = Path(json_path) if json_path else DEFAULT_JSON_PATH
        self._stocks: List[Dict[str, Any]] = []
        self._by_symbol: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Loads cached universe JSON if exists, else compiles from bundled data."""
        if self.json_path.exists():
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._stocks = data.get("stocks", [])
                    self._by_symbol = {s["symbol"]: s for s in self._stocks}
                    logger.info("Loaded %d stocks from %s", len(self._stocks), self.json_path)
                    return
            except Exception as e:
                logger.warning("Failed to load universe JSON %s: %s", self.json_path, e)

        # If not present or failed, attempt fetch or rely on internal fallback
        self.refresh_from_nse()

    def refresh_from_nse(self) -> bool:
        """Fetches the latest official constituent lists from NSE India archives."""
        logger.info("Fetching official constituent lists from NSE India...")
        data: Dict[str, Dict[str, Any]] = {}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        for idx_name, url in NSE_CSV_URLS.items():
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    df = pd.read_csv(resp)
                    for _, row in df.iterrows():
                        sym = str(row["Symbol"]).strip() + ".NS"
                        industry = str(row.get("Industry", "")).strip()
                        name = str(row.get("Company Name", "")).strip()
                        isin = str(row.get("ISIN Code", "")).strip()
                        if sym not in data:
                            data[sym] = {
                                "symbol": sym,
                                "name": name,
                                "industry": industry,
                                "sector": industry,
                                "isin": isin,
                                "indices": [idx_name],
                            }
                        else:
                            if idx_name not in data[sym]["indices"]:
                                data[sym]["indices"].append(idx_name)
            except Exception as e:
                logger.warning("Could not fetch %s from NSE: %s", idx_name, e)

        if data:
            self._stocks = sorted(list(data.values()), key=lambda x: x["symbol"])
            self._by_symbol = {s["symbol"]: s for s in self._stocks}
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(self.json_path, "w", encoding="utf-8") as f:
                    json.dump({"total": len(self._stocks), "stocks": self._stocks}, f, indent=2)
                logger.info("Saved %d stocks to %s", len(self._stocks), self.json_path)
                return True
            except Exception as e:
                logger.warning("Failed to save universe JSON %s: %s", self.json_path, e)

        return False

    def get_stocks(
        self,
        index_tier: Optional[str] = None,
        sector: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Filters stocks by index tier (e.g. 'NIFTY 50', 'NIFTY 100', 'NIFTY 200', 'NIFTY 500')

        and/or sector/industry.
        """
        results = self._stocks

        if index_tier and index_tier.strip():
            tier = index_tier.strip().upper()
            if tier != "ALL":
                results = [s for s in results if any(tier == idx.strip().upper() for idx in s.get("indices", []))]

        if sector and sector.strip() and sector.lower() != "all":
            sec_lower = sector.strip().lower()
            results = [s for s in results if s.get("sector", "").lower() == sec_lower or s.get("industry", "").lower() == sec_lower]

        return results

    def get_symbols(self, index_tier: Optional[str] = None, sector: Optional[str] = None) -> List[str]:
        """Returns list of ticker symbols for given tier and/or sector."""
        return [s["symbol"] for s in self.get_stocks(index_tier=index_tier, sector=sector)]

    def get_stock(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns metadata dictionary for a specific ticker symbol."""
        clean_sym = symbol.strip().upper()
        if not clean_sym.endswith(".NS") and not clean_sym.startswith("^"):
            clean_sym += ".NS"
        return self._by_symbol.get(clean_sym)

    def get_all_sectors(self) -> List[str]:
        """Returns sorted list of distinct sectors/industries across the universe."""
        sectors = {s.get("sector") for s in self._stocks if s.get("sector")}
        return sorted(list(sectors))

    def get_sectors_for_tier(self, index_tier: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns sorted list of distinct sectors with stock counts for a specific index tier."""
        stocks = self.get_stocks(index_tier=index_tier)
        counts: Dict[str, int] = {}
        for s in stocks:
            sec = s.get("sector") or "Other"
            counts[sec] = counts.get(sec, 0) + 1
        return [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: x[0])]

    @staticmethod
    def get_benchmark_ticker(index_name: str = "NIFTY 50") -> str:
        """Returns the Yahoo Finance symbol for an index benchmark."""
        for k, v in BENCHMARK_INDICES.items():
            if index_name.lower() in k.lower():
                return v
        return "^NSEI"

    @staticmethod
    def get_sector_ticker(sector_name: str) -> Optional[str]:
        """Returns corresponding sectoral index ticker for a given sector/industry name."""
        if not sector_name:
            return None
        return SECTOR_INDICES.get(sector_name)


# Global singleton instance
universe = UniverseManager()
