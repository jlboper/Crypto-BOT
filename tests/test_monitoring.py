import unittest
from datetime import UTC, datetime, timedelta

from trader.config import load_config
from trader.domain import Position
from trader.monitoring import activity_status, position_metrics, usable_price


class MonitoringTests(unittest.TestCase):
    def test_activity_changes_from_operational_to_offline(self):
        now = datetime(2026, 9, 11, 18, 0, tzinfo=UTC)
        recent = (now - timedelta(minutes=10)).isoformat()
        delayed = (now - timedelta(minutes=30)).isoformat()
        offline = (now - timedelta(hours=1)).isoformat()
        self.assertEqual(activity_status(recent, 900, now)["state"], "operational")
        self.assertEqual(activity_status(delayed, 900, now)["state"], "delayed")
        self.assertEqual(activity_status(offline, 900, now)["state"], "offline")

    def test_position_metrics_include_estimated_costs(self):
        config = load_config()
        position = Position("ETHUSDT", 1.0, 100.0, 90.0, 120.0, 105.0, 5.0, 0.1, "now")
        row = position_metrics(position, 110.0, config.paper)
        self.assertEqual(row["market_price"], 110.0)
        self.assertEqual(row["market_value"], 110.0)
        self.assertGreater(row["unrealized_pnl"], 9.0)
        self.assertGreater(row["unrealized_pct"], 9.0)

    def test_stale_missing_or_invalid_quote_cannot_be_reported_as_pnl(self):
        config = load_config()
        position = Position("ETHUSDT", 1.0, 100.0, 90.0, 120.0, 105.0, 5.0, 0.1, "now")
        now = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
        fresh = (now - timedelta(minutes=1)).isoformat()
        stale = (now - timedelta(hours=1)).isoformat()
        self.assertEqual(usable_price(110.0, fresh, 900, now), 110.0)
        self.assertIsNone(usable_price(110.0, stale, 900, now))
        self.assertIsNone(usable_price(float("nan"), fresh, 900, now))
        self.assertIsNone(usable_price(None, fresh, 900, now))
        row = position_metrics(position, None, config.paper)
        self.assertIsNone(row["market_price"])
        self.assertIsNone(row["market_value"])
        self.assertIsNone(row["unrealized_pnl"])
        self.assertIsNone(row["unrealized_pct"])


if __name__ == "__main__":
    unittest.main()
