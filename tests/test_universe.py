"""Unit tests for NIFTY Index Universe Manager and tier/sector filtering."""

import unittest
from stockpilot.universe import universe


class TestUniverseManager(unittest.TestCase):
    """Verifies that UniverseManager filters exact constituent counts and sectors."""

    def test_nifty50_exact_count(self):
        stocks = universe.get_stocks("NIFTY 50")
        self.assertEqual(len(stocks), 50, "NIFTY 50 must have exactly 50 stocks (no false matches with NIFTY 500)")

    def test_nifty100_count(self):
        stocks = universe.get_stocks("NIFTY 100")
        self.assertEqual(len(stocks), 100)

    def test_nifty200_count(self):
        stocks = universe.get_stocks("NIFTY 200")
        self.assertEqual(len(stocks), 200)

    def test_nifty500_count(self):
        stocks = universe.get_stocks("NIFTY 500")
        self.assertGreaterEqual(len(stocks), 500)

    def test_sectors_for_tier_nifty50(self):
        sectors = universe.get_sectors_for_tier("NIFTY 50")
        self.assertGreater(len(sectors), 5)
        # Verify counts sum up to 50
        total_stocks = sum(s["count"] for s in sectors)
        self.assertEqual(total_stocks, 50, "Sum of stock counts in NIFTY 50 sectors must be 50")

    def test_sector_filtering(self):
        it_stocks = universe.get_stocks(index_tier="NIFTY 50", sector="Information Technology")
        self.assertGreaterEqual(len(it_stocks), 4)
        symbols = [s["symbol"] for s in it_stocks]
        self.assertIn("TCS.NS", symbols)
        self.assertIn("INFY.NS", symbols)


if __name__ == "__main__":
    unittest.main()
