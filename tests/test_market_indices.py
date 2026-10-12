"""Tests for Market Indices API endpoint and fallback mechanisms."""

import unittest
from unittest.mock import patch, MagicMock
import web.app
from web.app import get_market_indices


class TestMarketIndicesAPI(unittest.TestCase):
    """Test suite for live market indices fetching and fallback caching."""

    def setUp(self):
        # Reset cache in web.app module before each test
        web.app._market_indices_cache = {
            "timestamp": 0.0,
            "indices": [],
        }

    def test_get_market_indices_structure(self):
        """Verify get_market_indices returns correct schema and 5 configured indices."""
        res = get_market_indices(refresh=True)
        self.assertIn("status", res)
        self.assertIn("indices", res)
        self.assertIn("timestamp", res)

        indices = res["indices"]
        self.assertEqual(len(indices), 5, "Must return exactly 5 indices")

        expected_names = {"NIFTY 50", "NIFTY NEXT 50", "BANK NIFTY", "INDIA VIX", "NIFTY 500"}
        returned_names = {idx["name"] for idx in indices}
        self.assertEqual(expected_names, returned_names)

        for idx in indices:
            self.assertIn("name", idx)
            self.assertIn("ticker", idx)
            self.assertIn("ltp", idx)
            self.assertIn("change", idx)
            self.assertIn("change_pct", idx)
            self.assertIn("is_positive", idx)
            self.assertIn("date", idx)
            self.assertIsInstance(idx["ltp"], (int, float))
            self.assertIsInstance(idx["change"], (int, float))
            self.assertIsInstance(idx["change_pct"], (int, float))

    def test_get_market_indices_cache_hit(self):
        """Verify cached response is returned when refresh=False and cache is warm."""
        # Warm the cache
        warm_res = get_market_indices(refresh=True)
        self.assertIn(warm_res["status"], ["live", "cache_fallback", "offline_fallback"])

        # Call without refresh
        cached_res = get_market_indices(refresh=False)
        self.assertEqual(cached_res["status"], "cached")
        self.assertEqual(len(cached_res["indices"]), 5)

    @patch("web.app.yf.download")
    def test_get_market_indices_download_failure_fallback(self, mock_download):
        """Verify fallback triggers safely if yfinance download raises exception."""
        mock_download.side_effect = RuntimeError("Simulated network timeout")

        res = get_market_indices(refresh=True)
        self.assertEqual(res["status"], "offline_fallback")
        self.assertEqual(len(res["indices"]), 5)
        for idx in res["indices"]:
            self.assertIn("name", idx)
            self.assertIn("ltp", idx)


if __name__ == "__main__":
    unittest.main()
