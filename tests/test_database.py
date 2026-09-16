import tempfile
import unittest
from pathlib import Path

from trader.database import Database


class DatabaseTests(unittest.TestCase):
    def test_market_snapshot_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "test.db")
            created_at = db.record_market_snapshot({"BTCUSDT": 123.45})
            prices, prices_at = db.market_snapshot()
            self.assertEqual(prices, {"BTCUSDT": 123.45})
            self.assertEqual(prices_at, created_at)


if __name__ == "__main__":
    unittest.main()
