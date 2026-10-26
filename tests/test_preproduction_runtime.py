"""Lifecycle and compatibility regressions; only isolated synthetic ledgers."""
from contextlib import closing
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error

from trader.config import load_config
from trader.database import Database
from trader.engine import TradingEngine
from trader.opportunity_contract import build_outcome
from trader.preproduction_runtime import create_observer, enqueue_proposal, register_observer, unregister_observer
from trader.remote_agent import RemoteAgent


class RuntimeObservationTests(unittest.TestCase):
    def config(self, root):
        config = load_config()
        return replace(config, bot=replace(config.bot, mode="paper", database_path=Path(root)/"spot.db"),
                       market_pulse=replace(config.market_pulse, enabled=False),
                       quant_arbitrage=replace(config.quant_arbitrage, enabled=False),
                       guardian_intelligence=replace(config.guardian_intelligence, enabled=False))

    def test_engine_owns_one_observer_and_stops_on_loop_exception(self):
        with tempfile.TemporaryDirectory() as root:
            engine = TradingEngine(self.config(root))
            observer = create_observer(engine.config)
            with patch('trader.preproduction_runtime.create_observer', return_value=observer) as factory, \
                 patch.object(engine, '_run_supervised_loop', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt): engine.run_forever()
            factory.assert_called_once()
            self.assertFalse(observer.snapshot()['health']['worker_alive'])
            self.assertFalse(enqueue_proposal({}))
            self.assertTrue((Path(root)/'operational-cohorts.sqlite3').is_file())

    def test_observer_startup_failure_never_blocks_operating_protection_loop(self):
        with tempfile.TemporaryDirectory() as root:
            engine = TradingEngine(self.config(root))
            with patch('trader.preproduction_runtime.create_observer', side_effect=OSError('synthetic')), \
                 patch.object(engine, '_run_supervised_loop') as loop:
                engine.run_forever()
            loop.assert_called_once()

    def test_only_new_cohort_database_is_created_and_source_gets_no_wallet(self):
        with tempfile.TemporaryDirectory() as root:
            observer = create_observer(self.config(root))
            self.assertFalse((Path(root)/'spot.db').exists())
            observer.initialize(); observer.tick()
            self.assertFalse((Path(root)/'spot.db').exists())
            self.assertFalse(observer.snapshot()['scopes'][0]['source_complete'])

    def test_actual_opportunity_ingress_reaches_durable_cohort_without_callback_io(self):
        from trader.opportunity_observer import OpportunityObserverService
        import trader.opportunity_observer as ingress
        with tempfile.TemporaryDirectory() as root:
            observer = create_observer(self.config(root)); observer.initialize()
            self.assertTrue(register_observer(observer))
            service = OpportunityObserverService(root)
            self.assertTrue(ingress.register_observer(service))
            try:
                event = build_outcome(engine='SPOT', environment='PAPER', origin_ref='synthetic', at=time.time()-1,
                                      stage='LEDGER_COMMIT', state='CLOSED', complete=True)
                with patch('sqlite3.connect', side_effect=AssertionError('producer must not open SQLite')):
                    self.assertTrue(ingress._enqueue(event))
                self.assertEqual(observer._queue.qsize(), 1)
                self.assertTrue(observer.tick())
                import sqlite3
                with closing(sqlite3.connect(observer.store.path)) as db:
                    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                self.assertTrue(rows)
                self.assertEqual(observer._queue.qsize(), 0)
            finally:
                unregister_observer(observer); ingress.unregister_observer(service)

    def test_live_cannot_fall_through_to_paper_or_create_financial_files(self):
        with tempfile.TemporaryDirectory() as root, patch('trader.engine.Database') as database, \
             patch('trader.engine.PaperBroker') as paper:
            config = self.config(root)
            with self.assertRaisesRegex(RuntimeError, 'LIVE_RUNTIME_ADAPTER_NOT_COMMISSIONED'):
                TradingEngine(replace(config, bot=replace(config.bot, mode='live')))
            database.assert_not_called(); paper.assert_not_called()

    def test_previous_worker_retry_drops_only_new_report_once(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.config(root); Database(config.bot.database_path)
            agent = RemoteAgent(config, 'https://portal.example', 'x'*43, state_directory=Path(root)/'agent')
            original = {'status': {'mode': 'PAPER'}, 'market_pulse': {}, 'migration_audit': {}, 'preproduction_readiness': {}}
            for label in ('Unknown dashboard field', 'Invalid Preproduction Readiness status'):
                calls = []
                agent.dashboard_provider = lambda: json.loads(json.dumps(original))
                def send(request, timeout):
                    calls.append(json.loads(request.data))
                    if len(calls) == 1:
                        raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                                                     io.BytesIO(json.dumps({'error': label}).encode()))
                    return io.BytesIO(b'{"commands":[],"jobs":[]}')
                with patch.object(agent.opener, 'open', side_effect=send): agent.sync()
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1]['snapshot']['dashboard'], {k: v for k, v in original.items() if k != 'preproduction_readiness'})

    def test_previous_worker_omits_only_institutional_extension_and_retains_pulse_finance(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.config(root); Database(config.bot.database_path)
            agent = RemoteAgent(config, 'https://portal.example', 'x'*43, state_directory=Path(root)/'agent')
            agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'}, 'market_pulse': {
                'performance': {'environment': 'SHADOW'}, 'positions': [], 'institutional': {},
                'decisions': [{'evidence': {'institutional_context_ids': ['a'*64], 'event_id': 'kept'}}]}}
            calls = []
            def send(request, timeout):
                calls.append(json.loads(request.data))
                if len(calls) == 1:
                    raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                                                 io.BytesIO(b'{"error":"Invalid Market Pulse status"}'))
                return io.BytesIO(b'{"commands":[],"jobs":[]}')
            with patch.object(agent.opener, 'open', side_effect=send): agent.sync()
            self.assertEqual(len(calls), 2)
            pulse = calls[1]['snapshot']['dashboard']['market_pulse']
            self.assertNotIn('institutional', pulse)
            self.assertEqual(pulse['performance']['environment'], 'SHADOW')
            self.assertEqual(pulse['decisions'][0]['evidence'], {'event_id': 'kept'})
