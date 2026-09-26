import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.futures_testnet import FuturesTestnetLab
from trader.futures_testnet_transport import FuturesTestnetExecutionError, HOST, signed_request


class FuturesTestnetLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = load_config()
        self.settings = replace(
            base.futures_testnet,
            database_path=Path(self.temp.name) / "futures-testnet.db",
            default_leverage=2,
            max_leverage=3,
            smoke_margin_usdt=10.0,
        )
        self.lab = FuturesTestnetLab(self.settings)
        self.position_amt = 0.0
        self.leverage = 2
        self.direction = "LONG"

    def public(self, method, endpoint, fields=None):
        fields = fields or {}
        if endpoint == "/fapi/v1/exchangeInfo":
            symbol = fields["symbol"]
            return {"symbols": [{
                "symbol": symbol,
                "filters": [
                    {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }]}
        if endpoint == "/fapi/v1/ticker/price":
            return {"symbol": fields["symbol"], "price": "100"}
        if endpoint == "/fapi/v1/premiumIndex":
            return {"symbol": fields["symbol"], "lastFundingRate": "0.0001"}
        raise AssertionError(endpoint)

    def signed(self, method, endpoint, fields=None):
        fields = fields or {}
        if endpoint == "/fapi/v3/account":
            return {"canTrade": True, "totalWalletBalance": "1000", "availableBalance": "900"}
        if endpoint == "/fapi/v3/positionRisk":
            if self.position_amt == 0:
                return []
            return [{
                "symbol": fields.get("symbol", "BTCUSDT"),
                "positionAmt": str(self.position_amt),
                "entryPrice": "100",
                "liquidationPrice": "70" if self.position_amt > 0 else "130",
                "leverage": str(self.leverage),
                "marginType": "isolated",
            }]
        if endpoint == "/fapi/v1/positionSide/dual":
            return {"code": 200}
        if endpoint == "/fapi/v1/marginType":
            return {"code": 200}
        if endpoint == "/fapi/v1/leverage":
            self.leverage = int(fields["leverage"])
            return {"symbol": fields["symbol"], "leverage": self.leverage}
        if endpoint == "/fapi/v1/order" and method == "POST":
            qty = float(fields["quantity"])
            if fields.get("reduceOnly") == "true":
                self.position_amt = 0.0
                return {"symbol": fields["symbol"], "clientOrderId": fields["newClientOrderId"],
                        "status": "FILLED", "avgPrice": "101", "executedQty": str(qty), "orderId": 2}
            self.direction = "LONG" if fields["side"] == "BUY" else "SHORT"
            self.position_amt = qty if self.direction == "LONG" else -qty
            return {"symbol": fields["symbol"], "clientOrderId": fields["newClientOrderId"],
                    "status": "FILLED", "avgPrice": "100", "executedQty": str(qty), "orderId": 1}
        raise AssertionError((method, endpoint, fields))

    def test_long_smoke_is_isolated_bounded_and_flat_after_close(self):
        with patch("trader.futures_testnet.public_request", side_effect=self.public),              patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.smoke(direction="LONG", leverage=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["direction"], "LONG")
        self.assertEqual(result["leverage"], 2)
        self.assertEqual(result["margin_type"], "ISOLATED")
        self.assertEqual(result["position_mode"], "ONE_WAY")
        self.assertEqual(result["position_notional_usdt"], 20.0)
        self.assertTrue(result["position_closed"])
        self.assertEqual(self.position_amt, 0.0)
        self.assertEqual(self.lab.ledger.latest()["status"], "COMPLETED")

    def test_short_smoke_closes_with_reduce_only(self):
        with patch("trader.futures_testnet.public_request", side_effect=self.public),              patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.smoke(direction="SHORT", leverage=3)
        self.assertEqual(result["direction"], "SHORT")
        self.assertEqual(result["leverage"], 3)
        self.assertTrue(result["position_closed"])
        self.assertEqual(self.position_amt, 0.0)

    def test_leverage_above_three_is_rejected_before_write(self):
        with self.assertRaisesRegex(ValueError, "1x, 2x or 3x"):
            self.lab.smoke(direction="LONG", leverage=4)

    def test_recovery_refuses_position_with_different_leverage(self):
        run_id = self.lab.ledger.start("BTCUSDT", "LONG", 2, "ISOLATED")
        self.lab.ledger.fail(run_id)
        self.position_amt = 0.1
        self.leverage = 3
        with patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            with self.assertRaisesRegex(FuturesTestnetExecutionError, "leverage mismatch"):
                self.lab.recover()
        self.assertEqual(self.position_amt, 0.1)

    def test_transport_has_no_production_host_and_blocks_unknown_endpoint(self):
        self.assertEqual(HOST, "https://testnet.binancefuture.com")
        self.assertNotIn("fapi.binance.com", HOST)
        with self.assertRaisesRegex(FuturesTestnetExecutionError, "endpoint blocked"):
            signed_request("POST", "/fapi/v1/withdraw", {})

    def test_config_caps_futures_leverage(self):
        config = load_config()
        self.assertEqual(config.futures_testnet.max_leverage, 3)
        source = Path("config.toml").read_text(encoding="utf-8").replace("max_leverage = 3", "max_leverage = 4")
        path = Path(self.temp.name) / "bad.toml"
        path.write_text(source, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "1x/2x/3x"):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
