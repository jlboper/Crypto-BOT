import io
import json
import os
import time
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from trader.ai_advisor import AIAdvisor
from trader.broker import PaperBroker
from trader.config import load_config
from trader.database import Database
from trader.domain import Signal, Candle
from trader.engine import TradingEngine
from trader.remote_agent import RemoteAgent
from trader.remote_portal import Portal, digest, password_hash


def signal():
    return Signal("BTCUSDT", "BUY", 80, 100., 95., 110., 2., 60., 101., 99., 1.3, "test", "now")


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = load_config()
        self.config = replace(config, bot=replace(config.bot, mode='paper', database_path=self.root/"test.db", kill_switch_path=self.root/"kill"))
        self.db = Database(self.config.bot.database_path)
        self.broker = PaperBroker(self.db, config.paper, config.risk)

    def test_buy_failure_rolls_back_all_accounting(self):
        with patch.object(self.db, "record_trade", side_effect=RuntimeError("injected disk failure")):
            with self.assertRaises(RuntimeError):
                self.broker.buy(signal(), 1, "test")
        self.assertEqual(self.db.cash(), 1000)
        self.assertEqual(self.db.positions(), [])
        self.assertEqual(self.db.recent("trades"), [])

    def test_concurrent_sells_credit_once(self):
        position = self.broker.buy(signal(), 1, "test")
        def sell(_):
            broker = PaperBroker(Database(self.db.path), self.config.paper, self.config.risk)
            try:
                broker.sell(position, 110, "test")
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(sell, range(2))), 1)
        self.assertEqual(len(self.db.recent("trades")), 2)
        self.assertLess(self.db.cash(), 1010)

    def test_cost_inclusive_risk_and_cash(self):
        engine = TradingEngine(self.config)
        quantity = engine._position_size(signal(), 1000, 1000, 0, 1)
        fill = 100 * 1.0005
        stop = 95 * .9995
        self.assertLessEqual(quantity*(fill-stop+.001*(fill+stop)), 7.5)
        self.assertLessEqual(quantity*fill, 150)
        tiny = engine._position_size(signal(), 1000, 1, 0, 1)
        self.assertLessEqual(tiny*fill*1.001, 1)

    def test_signal_claim_survives_database_reopen(self):
        self.assertTrue(self.db.claim_entry("BTCUSDT", 100))
        self.assertFalse(Database(self.db.path).claim_entry("BTCUSDT", 100))
        self.assertTrue(self.db.claim_entry("BTCUSDT", 101))

    def test_daily_ai_budget_survives_restart(self):
        config = replace(self.config, ai=replace(self.config.ai, max_reviews_per_day=1))
        self.assertTrue(TradingEngine(config)._claim_ai_budget())
        self.assertFalse(TradingEngine(config)._claim_ai_budget())

    def test_daily_loss_halt_survives_rebound_and_restart(self):
        engine = TradingEngine(self.config)
        self.assertTrue(engine._risk_halt(970))
        self.assertTrue(TradingEngine(self.config)._risk_halt(1000))

    def test_candle_cache_and_stale_history(self):
        engine = TradingEngine(self.config)
        duration = 14400000
        close = int(time.time()*1000)-1000
        candles = [Candle(close-duration, 100, 101, 99, 100, 1000, close)]
        with patch.object(engine.exchange, "candles", return_value=candles) as fetch:
            engine._cached_candles("BTCUSDT")
            engine._cached_candles("BTCUSDT")
            self.assertEqual(fetch.call_count, 1)
        engine._candle_cache.clear()
        with patch.object(engine.exchange, "candles", return_value=[replace(candles[0], close_time=1)]):
            with self.assertRaises(RuntimeError):
                engine._cached_candles("BTCUSDT")

    def test_protection_tick_works_while_killed(self):
        self.broker.buy(signal(), 1, "test")
        engine = TradingEngine(self.config)
        self.config.bot.kill_switch_path.write_text("pause")
        with patch.object(engine.exchange, "latest_prices", return_value={"BTCUSDT": 94}):
            engine.protection_tick()
        self.assertEqual(self.db.positions(), [])

    def test_universe_failure_does_not_prevent_protective_exit(self):
        self.broker.buy(signal(), 1, "test")
        engine = TradingEngine(self.config)
        with patch.object(engine.exchange, "latest_prices", return_value={"BTCUSDT": 94}), patch.object(engine.exchange, "top_usdt_symbols", side_effect=RuntimeError("network")):
            with self.assertRaises(RuntimeError):
                engine.cycle()
        self.assertEqual(self.db.positions(), [])

    def test_protection_without_candles(self):
        self.broker.buy(signal(), 1, "test")
        TradingEngine(self.config)._manage_positions({}, {"BTCUSDT": 94})
        self.assertEqual(self.db.positions(), [])

    def test_invalid_quantities_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.broker.buy(signal(), value, "test")

    def test_agent_replay_does_not_undo_local_pause(self):
        agent = RemoteAgent(self.config, "https://portal.example", "t"*40)
        agent.apply({"id": 1, "action": "resume", "expires": 110}, now=100)
        self.config.bot.kill_switch_path.write_text("local emergency")
        agent.apply({"id": 1, "action": "resume", "expires": 110}, now=100)
        self.assertTrue(self.config.bot.kill_switch_path.exists())
        with self.assertRaises(ValueError):
            agent.apply({"id": 2, "action": "resume", "expires": 99}, now=100)


class AIValidationTests(unittest.TestCase):
    def test_invalid_reviews_fail_closed_and_zero_is_preserved(self):
        config = load_config()
        for values in [dict(verdict="ALLOW", confidence=float("nan"), risk_multiplier=1, reason="x"),
                       dict(verdict="ALLOW", confidence=True, risk_multiplier=1, reason="x"),
                       dict(verdict="UNKNOWN", confidence=.9, risk_multiplier=1, reason="x"),
                       dict(verdict="ALLOW", confidence=.9, risk_multiplier=None, reason="x")]:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-for-tests"}), patch("urllib.request.urlopen") as call:
                call.return_value.__enter__.return_value.read.return_value = json.dumps({"output_text": json.dumps(values)}).encode()
                self.assertEqual(AIAdvisor(config.ai).review(signal(), True, {}).verdict, "REJECT")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-for-tests"}), patch("urllib.request.urlopen") as call:
            call.return_value.__enter__.return_value.read.return_value = json.dumps({"output_text": json.dumps(dict(verdict="ALLOW", confidence=.9, risk_multiplier=0, reason="x"))}).encode()
            self.assertEqual(AIAdvisor(config.ai).review(signal(), True, {}).risk_multiplier, 0)
            sent = json.loads(call.call_args.args[0].data)
            self.assertFalse(sent["store"])
            self.assertEqual(sent["max_output_tokens"], 800)



    def test_futures_review_uses_same_model_and_fails_closed(self):
        config = load_config()
        proposal = {"direction": "LONG", "score": 82, "price": 100000.0, "atr": 2000.0,
                    "rsi": 61.0, "ema_fast": 99000.0, "ema_slow": 97000.0, "volume_ratio": 1.4}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-for-tests"}), patch("urllib.request.urlopen") as call:
            call.return_value.__enter__.return_value.read.return_value = json.dumps({
                "output_text": json.dumps({"verdict": "ALLOW", "confidence": .91, "reason": "coherent"})
            }).encode()
            review = AIAdvisor(config.ai).review_futures(proposal, {"wallet_balance": 5000.0})
            self.assertEqual(review.verdict, "ALLOW")
            sent = json.loads(call.call_args.args[0].data)
            self.assertEqual(sent["model"], config.ai.model)
            self.assertIn("1x isolated leverage", sent["instructions"])
            self.assertFalse(sent["store"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-for-tests"}), patch("urllib.request.urlopen") as call:
            call.return_value.__enter__.return_value.read.return_value = json.dumps({
                "output_text": json.dumps({"verdict": "ALLOW", "confidence": .2, "reason": "weak"})
            }).encode()
            self.assertEqual(AIAdvisor(config.ai).review_futures(proposal, {}).verdict, "REJECT")


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.password = "testing-password-only-123"
        self.app = Portal(Path(self.temp.name)/"portal.db", "https://portal.example", password_hash(self.password), digest("t"*40))
        self.cookie, self.csrf = "", ""

    def request(self, path, body=None, **override):
        raw = json.dumps(body).encode() if body is not None else b""
        env = {"PATH_INFO": path, "REQUEST_METHOD": "POST" if body is not None else "GET",
            "HTTP_HOST": "portal.example", "HTTP_ORIGIN": "https://portal.example", "HTTP_COOKIE": self.cookie,
            "HTTP_X_CSRF_TOKEN": self.csrf, "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": io.BytesIO(raw), **override}
        result = {}
        def start(status, headers):
            result.update(status=int(status.split()[0]), headers=dict(headers))
        result["body"] = b"".join(self.app(env, start))
        return result

    def login(self):
        result = self.request("/v1/login", {"password": self.password})
        self.assertEqual(result["status"], 200)
        self.cookie = result["headers"]["Set-Cookie"].split(";")[0]
        self.csrf = json.loads(result["body"])["csrf"]
        self.assertIn("HttpOnly", result["headers"]["Set-Cookie"])

    def test_auth_csrf_idempotency_and_device_ack(self):
        self.assertEqual(self.request("/v1/status")["status"], 401)
        self.login()
        command = {"action": "kill", "request_id": "a"*20}
        self.assertEqual(self.request("/v1/commands", command, HTTP_X_CSRF_TOKEN="wrong")["status"], 403)
        first = self.request("/v1/commands", command)
        second = self.request("/v1/commands", command)
        self.assertEqual(first["body"], second["body"])
        packet = {"snapshot": {"mode": "PAPER"}, "acks": []}
        self.assertEqual(self.request("/v1/device/sync", packet)["status"], 401)
        delivered = self.request("/v1/device/sync", packet, HTTP_AUTHORIZATION="Bearer " + "t"*40)
        identifier = json.loads(delivered["body"])["commands"][0]["id"]
        packet["acks"] = [identifier]
        done = self.request("/v1/device/sync", packet, HTTP_AUTHORIZATION="Bearer " + "t"*40)
        self.assertEqual(json.loads(done["body"])["commands"], [])
        self.assertEqual(json.loads(self.request("/v1/status")["body"])["commands"][0]["status"], "applied")

    def test_login_throttling_origin_and_command_allowlist(self):
        self.assertEqual(self.request("/v1/login", {"password": self.password}, HTTP_ORIGIN="https://evil.example")["status"], 403)
        self.login()
        self.assertEqual(self.request("/v1/commands", {"action": "shell", "request_id": "a"*20})["status"], 400)
        for _ in range(10):
            self.request("/v1/login", {"password": "incorrect-password"})
        self.assertEqual(self.request("/v1/login", {"password": self.password})["status"], 429)

    def test_later_kill_supersedes_pending_resume(self):
        self.login()
        self.request("/v1/commands", {"action": "resume", "request_id": "r"*20})
        self.request("/v1/commands", {"action": "kill", "request_id": "k"*20})
        result = self.request("/v1/device/sync", {"snapshot": {"mode": "PAPER"}}, HTTP_AUTHORIZATION="Bearer "+"t"*40)
        self.assertEqual([c["action"] for c in json.loads(result["body"])["commands"]], ["kill"])


if __name__ == "__main__":
    unittest.main()
