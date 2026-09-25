import unittest
import json
import urllib.error
from unittest.mock import patch

from trader.testnet import SyntheticOrderLifecycle, TestnetPlanError, plan_order, validate_test_order


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

    def test_signed_validation_only_calls_testnet_order_test_once(self):
        plan = plan_order("BTCUSDT", "SELL", "100", self.info, quantity="0.1")
        with patch("urllib.request.urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value=json.dumps({}).encode()
            result=validate_test_order(plan,api_key="test-key",api_secret="test-secret")
        self.assertEqual(open_url.call_count,1)
        request=open_url.call_args.args[0]
        self.assertEqual(request.full_url,"https://testnet.binance.vision/api/v3/order/test")
        self.assertEqual(request.get_method(),"POST")
        self.assertIn(b"side=SELL",request.data)
        self.assertNotIn(b"test-secret",request.data)
        self.assertFalse(result["order_submission_enabled"])

    def test_validation_fails_closed_for_blocked_plan_and_http_error(self):
        blocked=plan_order("BTCUSDT","BUY","100",self.info,quote_amount="5")
        with patch("urllib.request.urlopen") as open_url,self.assertRaises(TestnetPlanError):
            validate_test_order(blocked,api_key="test-key",api_secret="test-secret")
        open_url.assert_not_called()
        ready=plan_order("BTCUSDT","BUY","100",self.info,quote_amount="25")
        error=urllib.error.HTTPError("https://testnet.binance.vision/api/v3/order/test",400,"bad",{},None)
        with patch("urllib.request.urlopen",side_effect=error) as open_url,self.assertRaises(TestnetPlanError):
            validate_test_order(ready,api_key="test-key",api_secret="test-secret")
        open_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
