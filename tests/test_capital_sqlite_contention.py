"""Bounded SQLite contention in an isolated SIM wallet, never order retries."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from trader import capital_manager_shadow as protocol
from tests.test_capital_manager_shadow import Clock, policy, NOW, U


class CapitalSQLiteContentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"SIM_CONTENDED.simulation.sqlite3"
        self.scope = protocol.AccountScope("SHADOW", "SIM_CONTENTION_ACCOUNT", "USDT")
        self.manager = protocol.CapitalManagerShadow(self.path, wallet_name="SIM_CONTENDED",
            scope=self.scope, limits=policy(), clock=Clock())
        self.manager.initialize()
        self.request = protocol.ReservationRequest("SIM_CONTENDED_REQUEST", self.scope, "SIM_SPOT", self.manager.limits.policy_id,
            (protocol.LegRequest("SIM_CONTENDED_LEG", "BTCUSDT", "LONG", "SPOT_REFERENCE", 100*U, 2*U, 5*U),), NOW+60)

    def test_short_busy_writer_waits_then_reserves_once_without_duplicate_money(self):
        original_connect = sqlite3.connect
        attempted = threading.Event()
        def traced_connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            connection.set_trace_callback(lambda sql: attempted.set() if sql.strip().upper() == "BEGIN IMMEDIATE" else None)
            return connection
        with closing(original_connect(self.path)) as holder:
            holder.execute("BEGIN IMMEDIATE")
            with patch.object(protocol.sqlite3, "connect", side_effect=traced_connect), ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.manager.reserve, self.request)
                try:
                    self.assertTrue(attempted.wait(5), "worker never attempted the guarded transaction")
                    # The former 250ms budget raised OperationalError here. The
                    # reservation must wait, not mutate or retry an exchange.
                    with self.assertRaises(FutureTimeout):
                        future.result(timeout=.4)
                finally:
                    holder.commit()
                first = future.result(timeout=10)
        self.assertTrue(first["accepted"])
        self.assertEqual(self.manager.reserve(self.request), first)
        value = self.manager.snapshot()
        self.assertEqual(value["reserved_units"], 102*U)
        self.assertEqual(len(value["requests"]), 1)
        self.assertFalse(value["execution_enabled"])

    def test_exhausted_busy_budget_changes_no_reservation_or_journal(self):
        before = self.manager.snapshot()
        with closing(sqlite3.connect(self.path)) as holder:
            holder.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.manager.reserve, self.request)
                try:
                    with self.assertRaises(sqlite3.OperationalError):
                        future.result(timeout=10)
                finally:
                    holder.commit()
        after = self.manager.snapshot()
        self.assertEqual(after["event_count"], before["event_count"])
        self.assertEqual(after["reserved_units"], 0)
        self.assertEqual(after["book_equity_units"], before["book_equity_units"])
        self.assertFalse(after["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
