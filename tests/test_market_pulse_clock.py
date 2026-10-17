import tempfile
import unittest
from unittest.mock import Mock

from trader.market_pulse import MarketPulseService, MarketWindow, PulseConfig


NOW = 1_800_000_000.0


def trade(identity, provider_at, price=100):
    return {"a": identity, "p": str(price), "q": "1", "T": provider_at * 1000,
            "E": provider_at * 1000}


def depth():
    return {"bids": [["99.98", "1000"]], "asks": [["100.02", "1000"]]}


class PulseClockTests(unittest.TestCase):
    def test_received_two_second_provider_lead_is_fresh_without_future_buckets(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        for index in range(311):
            received = NOW - 310 + index
            window.trade(trade(index + 1, received + 2, 900 if received > NOW - 2 else 100), received)
        window.depth(depth(), NOW)
        metrics = window.metrics(NOW)
        self.assertTrue(metrics["fresh"])
        self.assertTrue(metrics["complete"])
        # Future provider buckets remain excluded even though already received.
        self.assertEqual(metrics["price"], 100)
        self.assertEqual(window.buckets[-1][2], 900)

    def test_provider_future_tolerance_remains_five_seconds_at_ingestion(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        self.assertTrue(window.trade(trade(1, NOW + 5), NOW))
        self.assertTrue(window.trade_fresh(NOW))
        for payload in (trade(2, NOW + 5.001), dict(trade(2, NOW + 5), E=(NOW + 5.001) * 1000)):
            with self.assertRaisesRegex(ValueError, "Future market event"):
                window.trade(payload, NOW)
        self.assertEqual(window.last_id, 1)

    def test_receipt_expires_even_when_provider_lead_remains_in_date(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        window.trade(trade(1, NOW - 1), NOW - 1)
        window.trade(trade(2, NOW + 2), NOW)
        later = NOW + window.config.stale_seconds + 0.001
        window.depth(depth(), later)
        self.assertLess(later - window.last_trade_at, window.config.stale_seconds)
        self.assertFalse(window.trade_fresh(later))
        self.assertFalse(window.metrics(later)["fresh"])

    def test_provider_age_expires_independently_of_recent_receipt(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        window.trade(trade(1, NOW - 14), NOW)
        window.depth(depth(), NOW + 2)
        self.assertFalse(window.trade_fresh(NOW + 2))
        self.assertFalse(window.metrics(NOW + 2)["fresh"])
        self.assertFalse(window.trade(trade(2, NOW - 16), NOW))

    def test_decision_before_receipt_cannot_use_fresh_trade(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        window.trade(trade(1, NOW - 1), NOW)
        window.depth(depth(), NOW - 1)
        self.assertFalse(window.trade_fresh(NOW - 0.001))
        self.assertFalse(window.metrics(NOW - 0.001)["fresh"])

    def test_future_provider_trade_cannot_make_old_eligible_price_fresh(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        window.trade(trade(1, NOW - 25), NOW - 25)
        window.trade(trade(2, NOW + 2, 900), NOW)
        window.depth(depth(), NOW)
        self.assertTrue(window.trade_fresh(NOW))
        self.assertEqual(window.metrics(NOW)["price"], 100)
        self.assertFalse(window.metrics(NOW)["fresh"])

    def test_only_future_provider_bucket_stays_unavailable_until_eligible(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        window.trade(trade(1, NOW + 2, 900), NOW)
        window.depth(depth(), NOW)
        self.assertIsNone(window.metrics(NOW)["price"])
        self.assertFalse(window.metrics(NOW)["fresh"])
        self.assertTrue(window.metrics(NOW + 2)["fresh"])

    def test_coverage_and_trade_sequence_gates_are_unchanged(self):
        window = MarketWindow("BTCUSDT", PulseConfig())
        window.trade(trade(1, NOW - 1), NOW - 1)
        window.trade(trade(3, NOW + 2), NOW)
        window.depth(depth(), NOW)
        self.assertTrue(window.metrics(NOW)["fresh"])
        self.assertFalse(window.metrics(NOW)["complete"])
        self.assertEqual(window.gap_at, NOW)

    def test_periodic_protective_monitor_uses_received_bounded_clock_skew(self):
        with tempfile.TemporaryDirectory() as folder:
            service = MarketPulseService(folder, clock=lambda: NOW)
            service._initialize()
            window = service.windows["BTCUSDT"]
            window.trade(trade(1, NOW + 2), NOW)
            window.depth(depth(), NOW)
            service._positions["BTCUSDT"] = {"symbol": "BTCUSDT"}
            # Remove the synthetic position before unrelated ledger valuation.
            service._protective_check = Mock(side_effect=lambda *_: service._positions.clear())
            service.evaluate(NOW, project=False)
            service._protective_check.assert_called_once_with("BTCUSDT", 100, NOW)


if __name__ == "__main__":
    unittest.main()
