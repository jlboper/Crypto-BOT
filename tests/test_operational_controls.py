import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trader.config import load_config
from trader.operational_controls import execute


class _Child:
    pid = 43210
    def poll(self):
        return None


class _Runtime:
    def __init__(self, source, status_path, mode):
        self.source = source
        self.status_path = status_path
        self.mode = mode
        self.started = 0
    def start(self, token=None):
        self.started += 1
        self.status_path.write_text(json.dumps({
            "protocol": 1, "pid": _Child.pid, "version": "0.6.25",
            "phase": "running", "mode": self.mode,
            "dashboard_ready": True, "token": None,
        }), encoding="utf-8")
        return _Child()
    def health(self, child, token):
        return child.pid == _Child.pid
    def stop_owned(self, child):
        return None


class _SmokeDB:
    def __init__(self, existing=None):
        self.closed = False
        self.existing = list(existing or [])
    def positions(self):
        return list(self.existing)
    def cash(self):
        return 1000.0
    def position(self, symbol):
        return None


class _Broker:
    def __init__(self, db, paper, risk):
        self.db = db
        self.reconciles = 0
        self.buys = 0
        self.sells = 0
    def reconcile_pending(self):
        self.reconciles += 1
        return True
    def buy(self, signal, quantity, reason):
        self.buys += 1
        self.signal = signal
        self.quantity = quantity
        return SimpleNamespace(quantity=quantity, entry_price=100.0)
    def sell(self, position, price, reason):
        self.sells += 1
        self.db.closed = True
        return -0.01


class _Client:
    def __init__(self, timeout=10):
        self.timeout = timeout
    def testnet_symbol_info(self, symbol):
        return {"symbol":symbol}
    def testnet_reference_price(self, symbol):
        return 100.0


class OperationalControlsTests(unittest.TestCase):
    def _fixture(self, mode="testnet"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = Path(temp.name)
        (source / "data").mkdir()
        (source / "pyproject.toml").write_text('[project]\nversion="0.6.25"\n', encoding="utf-8")
        (source / "config.toml").write_text('[bot]\nmode="paper"\n', encoding="utf-8")
        (source / ".env.local").write_text("EXECUTION_MODE="+mode+"\nOPENAI_MODEL=gpt-6-luna\n", encoding="utf-8")
        base = load_config()
        config = replace(base, bot=replace(base.bot, mode=mode, database_path=source/"data/testnet-trader.db",
                                           kill_switch_path=source/"data/KILL"))
        status = source / "data/engine-runtime.json"
        status.write_text(json.dumps({
            "protocol":1,"pid":111,"version":"0.6.25","phase":"running",
            "mode":mode,"dashboard_ready":True,"token":None,
        }), encoding="utf-8")
        return source, config, status

    def test_smoke_requires_testnet_before_maintenance(self):
        source, config, status = self._fixture("paper")
        with patch.dict(os.environ, {"EXECUTION_MODE":"paper","OPENAI_MODEL":"gpt-6-luna"}, clear=False), \
             patch("trader.operational_controls.load_config", return_value=config):
            with self.assertRaisesRegex(ValueError, "requires TESTNET"):
                execute(source, "testnet_smoke", {})
        self.assertFalse((source/"data/UPDATE_MAINTENANCE.json").exists())
        self.assertEqual(json.loads(status.read_text())["mode"], "paper")

    def test_smoke_can_use_isolated_symbol_with_existing_positions(self):
        source, config, status = self._fixture("testnet")
        runtime = _Runtime(source, status, "testnet")
        existing = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]
        db = _SmokeDB(existing)
        broker = _Broker(db, config.paper, config.risk)
        with patch.dict(os.environ, {"EXECUTION_MODE":"testnet","OPENAI_MODEL":"gpt-6-luna"}, clear=False), \
             patch("trader.operational_controls.load_config", return_value=config), \
             patch("trader.operational_controls.ProcessRuntime", return_value=runtime), \
             patch("trader.database.Database", return_value=db), \
             patch("trader.testnet_broker.BinanceTestnetBroker", return_value=broker), \
             patch("trader.exchange.BinanceClient", _Client):
            result = execute(source, "testnet_smoke", {})
        self.assertEqual(result["testnet_smoke"]["symbol"], "BNBUSDT")
        self.assertEqual([row.symbol for row in db.positions()], ["BTCUSDT","ETHUSDT"])

    def test_smoke_exclusively_buys_sells_reconciles_and_restarts(self):
        source, config, status = self._fixture("testnet")
        runtime = _Runtime(source, status, "testnet")
        db = _SmokeDB()
        broker = _Broker(db, config.paper, config.risk)
        with patch.dict(os.environ, {"EXECUTION_MODE":"testnet","OPENAI_MODEL":"gpt-6-luna"}, clear=False), \
             patch("trader.operational_controls.load_config", return_value=config), \
             patch("trader.operational_controls.ProcessRuntime", return_value=runtime), \
             patch("trader.database.Database", return_value=db), \
             patch("trader.testnet_broker.BinanceTestnetBroker", return_value=broker), \
             patch("trader.exchange.BinanceClient", _Client):
            result = execute(source, "testnet_smoke", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "testnet")
        self.assertEqual(result["testnet_smoke"]["symbol"], "BTCUSDT")
        self.assertFalse(result["testnet_smoke"]["pending"])
        self.assertEqual(broker.buys, 1)
        self.assertEqual(broker.sells, 1)
        self.assertGreaterEqual(broker.reconciles, 2)
        self.assertEqual(runtime.started, 1)
        self.assertFalse((source/"data/UPDATE_MAINTENANCE.json").exists())


if __name__ == "__main__":
    unittest.main()
