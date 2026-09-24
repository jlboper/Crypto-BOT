import unittest

from trader.testnet import SyntheticOrderLifecycle, TestnetPlanError, plan_order


class TestnetPlanningTests(unittest.TestCase):
    def setUp(self):
        self.info = {
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "10", "applyToMarket": True},
            ],
        }

    def test_plan_is_normalized_and_cannot_submit(self):
        plan = plan_order("BTCUSDT", "BUY", "100", self.info, quote_amount="10.09")
        self.assertEqual(plan.quantity, "0.1")
        self.assertEqual(plan.estimated_notional, "10")
        self.assertEqual(plan.status, "READY_FOR_MANUAL_REVIEW")
        self.assertFalse(plan.order_submission_enabled)
        self.assertEqual(plan.execution_mode, "READ_ONLY_DRY_RUN")

    def test_plan_blocks_notional_and_invalid_lifecycle_transitions(self):
        plan = plan_order("BTCUSDT", "BUY", "100", self.info, quote_amount="5")
        self.assertEqual(plan.status, "BLOCKED")
        self.assertIn("MIN_NOTIONAL_ESTIMATE", plan.reasons)
        lifecycle = SyntheticOrderLifecycle("id-1")
        lifecycle.apply("e1", "PARTIALLY_FILLED", "0.01")
        self.assertEqual(lifecycle.apply("e1", "PARTIALLY_FILLED", "0.01")["events_seen"], 1)
        with self.assertRaises(TestnetPlanError):
            lifecycle.apply("e2", "NEW", "0.01")


if __name__ == "__main__":
    unittest.main()
