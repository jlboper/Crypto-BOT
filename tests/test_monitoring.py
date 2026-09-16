import unittest
from datetime import UTC, datetime, timedelta

from trader.config import load_config
from trader.domain import Position
from trader.monitoring import activity_status, position_metrics


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


if __name__ == "__main__":
    unittest.main()
