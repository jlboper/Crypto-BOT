import tempfile
from decimal import Decimal
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.futures_testnet import FuturesTestnetLab
from trader.futures_testnet_transport import FuturesTestnetExecutionError, HOST, PUBLIC_FALLBACK_HOST, signed_request


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

    def public(self, method, endpoint, fields=None, **kwargs):
        fields = fields or {}
        if endpoint == "/fapi/v1/exchangeInfo":
            symbol = fields["symbol"]
            return {"symbols": [{
                "symbol": symbol, "status":"TRADING", "contractType":"PERPETUAL", "quoteAsset":"USDT",
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
            row = {
                "symbol": fields.get("symbol", "BTCUSDT"),
                "positionAmt": str(self.position_amt),
                "entryPrice": "100" if self.position_amt else "0",
                "liquidationPrice": ("70" if self.position_amt > 0 else "130") if self.position_amt else "0",
                "leverage": str(self.leverage),
                "marginType": "isolated",
                "positionSide": "BOTH",
                "markPrice": "100",
            }
            return [row]
        if endpoint == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False} if method == "GET" else {"code": 200}
        if endpoint == "/fapi/v1/symbolConfig":
            return [{"symbol": fields.get("symbol","BTCUSDT"), "marginType":"isolated",
                     "leverage": str(self.leverage)}]
        if endpoint == "/fapi/v1/marginType":
            return {"code": 200}
        if endpoint == "/fapi/v1/leverage":
            self.leverage = int(fields["leverage"])
            return {"symbol": fields["symbol"], "leverage": self.leverage}
        if endpoint == "/fapi/v1/order/test" and method == "POST":
            return {}
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



    def test_forward_submission_keeps_durable_two_and_three_x_before_actual_order(self):
        for leverage in (2, 3):
            self.position_amt = 0
            self.lab.ledger.set_setting("forward_pending_order", None)
            self.lab.ledger.set_setting("forward_open_plan", dict(symbol="ADAUSDT", direction="LONG", leverage=leverage))
            def transport(method, endpoint, fields=None):
                if endpoint == "/fapi/v1/order" and method == "POST":
                    self.assertEqual(self.leverage, leverage)
                return self.signed(method, endpoint, fields)
            with patch("trader.futures_testnet.signed_request", side_effect=transport):
                self.lab.forward_submit(symbol="ADAUSDT", side="BUY", quantity=Decimal(".1"), reduce_only=False)
            self.assertEqual(self.leverage, leverage)

    def test_forward_quantity_validates_new_asset_filters_and_never_rounds_above_cap(self):
        with patch("trader.futures_testnet.public_request", side_effect=self.public), \
             patch("trader.futures_testnet.signed_request", side_effect=self.signed) as transport:
            qty, price = self.lab.forward_quantity("ADAUSDT", "LONG", Decimal("60"), Decimal("60"))
            self.assertEqual(qty, Decimal(".588"))
            self.assertLessEqual(qty * price * Decimal("1.02"), 60)
            qty, _ = self.lab.forward_quantity("NEARUSDT", "SHORT", Decimal("1"), Decimal("1"))
            self.assertEqual(qty, 0)
            self.assertEqual(sum(c.args[1] == "/fapi/v1/order" for c in transport.call_args_list), 0)

    def test_forward_quantity_rejects_unavailable_contract_without_order(self):
        with patch.object(self.lab,'_symbol_info',return_value={'status':'BREAK'}), \
             patch('trader.futures_testnet.signed_request') as transport:
            with self.assertRaisesRegex(FuturesTestnetExecutionError,'contract unavailable'):
                self.lab.forward_quantity('NEARUSDT','LONG',Decimal('60'),Decimal('60'))
            transport.assert_not_called()

    def test_trade_probe_is_signed_only_and_never_uses_public_market_data(self):
        captured = {}
        def signed(method, endpoint, fields=None):
            self.assertEqual((method, endpoint), ("POST", "/fapi/v1/order/test"))
            captured.update(fields or {})
            return {}
        with patch("trader.futures_testnet.public_request", side_effect=AssertionError("public data must not be used")), \
             patch("trader.futures_testnet.signed_request", side_effect=signed):
            self.assertTrue(self.lab._trade_probe("BTCUSDT"))
        self.assertEqual(captured["quantity"], "0.001")

    def test_check_uses_test_order_probe_when_account_flag_is_false(self):
        def signed(method, endpoint, fields=None):
            fields = fields or {}
            if endpoint == "/fapi/v3/account":
                return {"canTrade": False, "totalWalletBalance": "1000", "availableBalance": "900"}
            if endpoint == "/fapi/v3/positionRisk":
                return []
            if endpoint == "/fapi/v1/order/test" and method == "POST":
                return {}
            raise AssertionError((method, endpoint, fields))
        with patch("trader.futures_testnet.public_request", side_effect=self.public), \
             patch("trader.futures_testnet.signed_request", side_effect=signed):
            result = self.lab.check()
        self.assertTrue(result["can_trade"])
        self.assertTrue(result["trade_probe"])
        self.assertFalse(result["reported_can_trade"])
        self.assertEqual(result["environment"], "USD-M FUTURES DEMO")

    def test_long_smoke_is_isolated_bounded_and_flat_after_close(self):
        with patch("trader.futures_testnet.public_request", side_effect=AssertionError("smoke must not use public data")), \
             patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.smoke(direction="LONG", leverage=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["direction"], "LONG")
        self.assertEqual(result["leverage"], 2)
        self.assertEqual(result["margin_type"], "ISOLATED")
        self.assertEqual(result["position_mode"], "ONE_WAY")
        self.assertEqual(result["position_notional_usdt"], 0.1)
        self.assertTrue(result["position_closed"])
        self.assertEqual(self.position_amt, 0.0)
        self.assertEqual(self.lab.ledger.latest()["status"], "COMPLETED")


    def test_close_price_falls_back_to_cumquote_without_resubmitting(self):
        order = {"clientOrderId": "close-1", "avgPrice": "0", "executedQty": "0.001", "cumQuote": "0.10125"}
        with patch("trader.futures_testnet.signed_request", side_effect=AssertionError("no query needed")):
            price = self.lab._execution_price(order, "BTCUSDT")
        self.assertEqual(price, Decimal("101.25"))

    def test_close_price_queries_filled_order_when_immediate_result_has_no_price(self):
        order = {"clientOrderId": "close-2", "avgPrice": "0", "executedQty": "0", "cumQuote": "0"}
        def signed(method, endpoint, fields=None):
            self.assertEqual((method, endpoint), ("GET", "/fapi/v1/order"))
            self.assertEqual(fields["origClientOrderId"], "close-2")
            return {"clientOrderId": "close-2", "avgPrice": "101.5", "executedQty": "0.001", "cumQuote": "0.1015"}
        with patch("trader.futures_testnet.signed_request", side_effect=signed):
            price = self.lab._execution_price(order, "BTCUSDT")
        self.assertEqual(price, Decimal("101.5"))

    def test_explicit_smoke_symbol_is_honored_and_closed(self):
        with patch("trader.futures_testnet.public_request", side_effect=AssertionError("smoke must not use public data")), \
             patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.smoke(direction="LONG", leverage=1, symbol="ETHUSDT")
        self.assertEqual(result["symbol"], "ETHUSDT")
        self.assertTrue(result["position_closed"])
        self.assertEqual(self.position_amt, 0.0)

    def test_unknown_explicit_smoke_symbol_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Futures Testnet smoke symbol"):
            self.lab.smoke(direction="LONG", leverage=1, symbol="DOGEUSDT")

    def test_short_smoke_closes_with_reduce_only(self):
        with patch("trader.futures_testnet.public_request", side_effect=AssertionError("smoke must not use public data")), \
             patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.smoke(direction="SHORT", leverage=3)
        self.assertEqual(result["direction"], "SHORT")
        self.assertEqual(result["leverage"], 3)
        self.assertTrue(result["position_closed"])
        self.assertEqual(self.position_amt, 0.0)


    def test_forward_pending_order_not_found_is_classified_without_clearing_journal(self):
        pending = {
            "symbol":"BTCUSDT","side":"BUY","quantity":"0.001","reduce_only":False,
            "kind":"OPEN","created_at":"2026-09-27T00:00:00+00:00",
            "client_order_id":"cait-fwd-missing",
        }
        self.lab.ledger.set_setting("forward_pending_order", pending)
        missing = FuturesTestnetExecutionError("Futures Demo HTTP 400", code=-2013,
                                               api_message="Order does not exist")
        with patch("trader.futures_testnet.signed_request", side_effect=missing):
            result=self.lab.reconcile_forward_pending()
        self.assertEqual(result["status"], "ORDER_NOT_FOUND")
        self.assertFalse(result["resolved"])
        self.assertIsNotNone(self.lab.ledger.setting("forward_pending_order"))

    def test_forward_open_forces_one_x_before_order_and_journal_survives_fill(self):
        self.leverage = 2
        with patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.forward_submit(
                symbol="BTCUSDT", side="BUY", quantity=Decimal("0.001"), reduce_only=False
            )
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(self.leverage, 1)
        pending = self.lab.ledger.setting("forward_pending_order")
        self.assertEqual(pending["symbol"], "BTCUSDT")
        self.assertFalse(pending["reduce_only"])

    def test_forward_reduce_only_close_does_not_reconfigure_symbol(self):
        self.position_amt = 0.001
        self.leverage = 3
        with patch.object(self.lab, "_configure", side_effect=AssertionError("close must not reconfigure")), \
             patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.forward_submit(
                symbol="BTCUSDT", side="SELL", quantity=Decimal("0.001"), reduce_only=True
            )
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(self.leverage, 3)

    def test_flat_hedge_mode_rows_are_repaired_to_one_way_before_symbol_config(self):
        state = {"hedge": True, "leverage": 2, "margin":"cross"}
        calls = []
        def signed(method, endpoint, fields=None):
            fields = fields or {}
            calls.append((method, endpoint, dict(fields)))
            if endpoint == "/fapi/v3/positionRisk":
                return []  # v3 omits flat symbols by design
            if endpoint == "/fapi/v1/positionSide/dual":
                if method == "GET":
                    return {"dualSidePosition": state["hedge"]}
                state["hedge"] = False
                return {"code":200}
            if endpoint == "/fapi/v1/symbolConfig":
                return [{"symbol": fields.get("symbol","BTCUSDT"),
                         "marginType":state["margin"],
                         "leverage":str(state["leverage"])}]
            if endpoint == "/fapi/v1/marginType":
                state["margin"] = "isolated"
                return {"code":200}
            if endpoint == "/fapi/v1/leverage":
                state["leverage"] = int(fields["leverage"])
                return {"symbol":fields["symbol"],"leverage":state["leverage"]}
            raise AssertionError((method, endpoint, fields))
        with patch("trader.futures_testnet.signed_request", side_effect=signed):
            result = self.lab.ensure_flat_forward_configuration("BTCUSDT")
        self.assertFalse(state["hedge"])
        self.assertEqual(state["leverage"], 1)
        self.assertEqual(result["positionSide"], "BOTH")
        self.assertEqual(result["marginType"], "isolated")
        self.assertTrue(any(m=="POST" and e=="/fapi/v1/positionSide/dual" for m,e,_ in calls))

    def test_flat_preflight_with_any_exposure_fails_closed(self):
        def signed(method, endpoint, fields=None):
            if endpoint == "/fapi/v3/positionRisk":
                symbol=(fields or {}).get("symbol","BTCUSDT")
                return [{"symbol":symbol,"positionAmt":"0.1","leverage":"1",
                         "marginType":"cross","positionSide":"LONG"}]
            raise AssertionError((method, endpoint, fields))
        with patch("trader.futures_testnet.signed_request", side_effect=signed):
            with self.assertRaisesRegex(FuturesTestnetExecutionError, "open exposure"):
                self.lab.ensure_flat_forward_configuration("BTCUSDT")

    def test_flat_v3_positionrisk_omission_uses_symbol_config_for_confirmation(self):
        state={"leverage":2,"margin":"cross"}
        def signed(method, endpoint, fields=None):
            fields=fields or {}
            if endpoint=="/fapi/v3/positionRisk":
                return []
            if endpoint=="/fapi/v1/positionSide/dual":
                return {"dualSidePosition":False}
            if endpoint=="/fapi/v1/symbolConfig":
                return [{"symbol":fields["symbol"],"marginType":state["margin"],
                         "leverage":str(state["leverage"])}]
            if endpoint=="/fapi/v1/marginType":
                state["margin"]="isolated"; return {"code":200}
            if endpoint=="/fapi/v1/leverage":
                state["leverage"]=int(fields["leverage"])
                return {"symbol":fields["symbol"],"leverage":state["leverage"]}
            raise AssertionError((method,endpoint,fields))
        with patch("trader.futures_testnet.signed_request", side_effect=signed):
            result=self.lab.ensure_flat_forward_configuration("BTCUSDT")
        self.assertEqual(result["marginType"],"isolated")
        self.assertEqual(int(result["leverage"]),1)

    def test_flat_forward_preflight_repairs_to_isolated_one_x_and_confirms(self):
        self.position_amt = 0.0
        self.leverage = 2
        with patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            state = self.lab.ensure_flat_forward_configuration("BTCUSDT")
        self.assertEqual(self.leverage, 1)
        self.assertEqual(state["marginType"], "isolated")
        self.assertEqual(int(state["leverage"]), 1)
        self.assertEqual(state["positionSide"], "BOTH")

    def test_known_isolated_forward_position_repairs_leverage_to_one_x(self):
        self.position_amt = 0.1
        self.leverage = 3
        row = {
            "symbol": "BTCUSDT", "positionAmt": "0.1", "entryPrice": "100",
            "liquidationPrice": "70", "leverage": "3", "marginType": "isolated",
            "positionSide": "BOTH",
        }
        with patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            refreshed = self.lab.ensure_forward_position_configuration("BTCUSDT", row)
        self.assertEqual(self.leverage, 1)
        self.assertEqual(int(refreshed["leverage"]), 1)

    def test_open_forward_position_never_auto_repairs_cross_or_hedge_mode(self):
        cross = {"symbol": "BTCUSDT", "positionAmt": "0.1", "leverage": "2",
                 "marginType": "cross", "positionSide": "BOTH"}
        with self.assertRaisesRegex(FuturesTestnetExecutionError, "margin is not isolated"):
            self.lab.ensure_forward_position_configuration("BTCUSDT", cross)
        hedge = {"symbol": "BTCUSDT", "positionAmt": "0.1", "leverage": "2",
                 "marginType": "isolated", "positionSide": "LONG"}
        with self.assertRaisesRegex(FuturesTestnetExecutionError, "ONE_WAY"):
            self.lab.ensure_forward_position_configuration("BTCUSDT", hedge)

    def test_leverage_above_three_is_rejected_before_write(self):
        with self.assertRaisesRegex(ValueError, "1x, 2x or 3x"):
            self.lab.smoke(direction="LONG", leverage=4)

    def test_flat_trial_configuration_confirms_two_and_three_x(self):
        for leverage in (2, 3):
            with patch("trader.futures_testnet.signed_request", side_effect=self.signed):
                result = self.lab.ensure_flat_forward_configuration("BTCUSDT", leverage)
            self.assertEqual(int(result['leverage']), leverage)
            self.assertEqual(self.position_amt, 0)

    def test_tracked_three_x_trial_is_preserved_and_drift_repaired_to_its_plan(self):
        self.position_amt = .1
        self.leverage = 3
        row = dict(symbol='BTCUSDT', positionAmt='.1', entryPrice='100',
            leverage='3', marginType='isolated', positionSide='BOTH')
        with patch("trader.futures_testnet.signed_request", side_effect=self.signed) as request:
            result = self.lab.ensure_forward_position_configuration('BTCUSDT', row, 3)
        self.assertEqual(int(result['leverage']), 3)
        self.assertFalse(any(call.args[0] == 'POST' for call in request.call_args_list))
        self.leverage = 1
        row['leverage'] = '1'
        with patch("trader.futures_testnet.signed_request", side_effect=self.signed):
            result = self.lab.ensure_forward_position_configuration('BTCUSDT', row, 3)
        self.assertEqual(int(result['leverage']), 3)
        self.assertEqual(self.position_amt, .1)

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
        self.assertNotEqual(HOST, "https://fapi.binance.com")
        self.assertEqual(PUBLIC_FALLBACK_HOST, "https://fapi.binance.com")
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
