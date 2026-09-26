import tempfile
import unittest
import io
import json
import urllib.error
from pathlib import Path
from dataclasses import replace
from unittest.mock import Mock, patch
from trader.config import load_config
from trader.database import Database
from trader.remote_agent import RemoteAgent


class RemoteConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.root = root
        config = load_config()
        self.config = replace(config, bot=replace(config.bot, database_path=root/'source/trader.db', kill_switch_path=root/'source/KILL'))
        self.config.bot.database_path.parent.mkdir()
        self.agent = RemoteAgent(self.config, 'https://portal.example', 'x'*43, state_directory=root/'isolated')

    def command(self, identifier, action):
        return {'id':identifier, 'action':action, 'expires':110}

    def test_checkpoint_is_isolated_and_source_database_is_untouched(self):
        Database(self.config.bot.database_path)
        before = self.config.bot.database_path.read_bytes()
        self.agent.snapshot()
        self.agent.apply(self.command(1,'kill'), now=100)
        self.agent.apply(self.command(2,'resume'), now=100)
        self.assertFalse(self.config.bot.kill_switch_path.exists())
        self.assertEqual(self.config.bot.database_path.read_bytes(), before)
        self.assertTrue((self.root/'isolated/remote-state.json').is_file())
        self.assertFalse((self.root/'source/remote-state.json').exists())

    def test_local_halt_cannot_be_claimed_or_cleared_remotely(self):
        kill = self.config.bot.kill_switch_path
        kill.write_text('automatic halt after consecutive errors\n')
        self.agent.apply(self.command(1,'kill'), now=100)
        with self.assertRaises(ValueError):
            self.agent.apply(self.command(2,'resume'), now=100)
        self.assertEqual(kill.read_text(),'automatic halt after consecutive errors\n')
        self.assertEqual(self.agent._last_id(),1)

    def test_live_refused_and_missing_database_not_created(self):
        with self.assertRaises(ValueError):
            RemoteAgent(replace(self.config, bot=replace(self.config.bot, mode='live')), 'https://portal.example', 'x'*43)
        with self.assertRaises(Exception):
            self.agent.snapshot()
        self.assertFalse(self.config.bot.database_path.exists())

    def test_source_guard_prevents_network_and_stop_prevents_loop(self):
        with patch.object(self.agent,'sync') as sync:
            self.agent.run(stop=lambda:True)
            sync.assert_not_called()
            stopped = []
            def report(ok):
                self.assertFalse(ok)
                stopped.append(True)
            def invalid():
                raise ValueError('mode changed')
            self.agent.run(stop=lambda:bool(stopped), validate=invalid, report=report)
            sync.assert_not_called()

    def test_dashboard_rejection_keeps_heartbeat_and_updates_without_exposing_response(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'}}
        calls = []
        def send(request, timeout):
            body = json.loads(request.data)
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                    io.BytesIO(b'{"error":"Oversized PAPER scorecard"}'))
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertEqual(len(calls), 2)
        self.assertIn('dashboard', calls[0]['snapshot'])
        self.assertNotIn('dashboard', calls[1]['snapshot'])
        self.assertEqual(self.agent.last_error, 'DASHBOARD_REJECTED:Oversized PAPER scorecard')

    def test_broken_local_dashboard_still_sends_heartbeat_and_update_jobs(self):
        Database(self.config.bot.database_path)
        def unavailable():
            raise RuntimeError('private credential must never appear in status')
        self.agent.dashboard_provider = unavailable
        self.agent.update_provider = lambda: {
            'version': '0.6.14', 'release_id': 'a'*64, 'sequence': 123,
            'expires': 1800000000, 'commit': 'b'*40, 'enabled': True}
        received = []
        def send(request, timeout):
            received.append(json.loads(request.data))
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['snapshot']['mode'], self.config.bot.mode.upper())
        self.assertEqual(received[0]['snapshot']['bot_update']['version'], '0.6.14')
        self.assertNotIn('dashboard', received[0]['snapshot'])
        self.assertEqual(self.agent.last_error, 'DASHBOARD_UNAVAILABLE:RuntimeError')
        self.assertNotIn('private credential', self.agent.last_error)

    def test_remote_paper_control_executes_after_authenticated_device_sync_and_reports_result(self):
        Database(self.config.bot.database_path)
        self.agent.paper_controls = Mock(available=True)
        self.agent.paper_controls.results.return_value = [{'id': 10, 'status': 'completed', 'message': 'Perfil PAPER aplicado: prudente'}]
        control = {'id': 11, 'action': 'risk_profile', 'payload': {'profile': 'prudente'}, 'expires': 1800000000}
        requests = []
        def send(request, timeout):
            requests.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'commands': [], 'jobs': [], 'paper_controls': [control]}).encode())
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertTrue(requests[0]['snapshot']['paper_controls'])
        self.assertEqual(requests[0]['control_results'][0]['id'], 10)
        self.agent.paper_controls.apply.assert_called_once_with(control)

    def test_config_refresh_accepts_supervised_paper_to_testnet_ledger_switch(self):
        Database(self.config.bot.database_path)
        testnet_path = self.config.bot.database_path.parent / 'testnet-trader.db'
        testnet_config = replace(self.config, bot=replace(self.config.bot, mode='testnet', database_path=testnet_path))
        Database(testnet_path)
        self.agent.config_provider = lambda: testnet_config
        received = []
        def send(request, timeout):
            received.append(json.loads(request.data))
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertEqual(self.agent.config.bot.mode, 'testnet')
        self.assertEqual(self.agent.config.bot.database_path, testnet_path)
        self.assertEqual(received[0]['snapshot']['mode'], 'TESTNET')

    def test_config_refresh_rejects_database_directory_escape(self):
        Database(self.config.bot.database_path)
        foreign = self.root / 'foreign/testnet.db'
        foreign.parent.mkdir()
        Database(foreign)
        changed = replace(self.config, bot=replace(self.config.bot, mode='testnet', database_path=foreign))
        self.agent.config_provider = lambda: changed
        with self.assertRaisesRegex(ValueError, 'Trading installation changed unexpectedly'):
            self.agent.sync()

    def test_dashboard_failure_does_not_hide_core_job_failure(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: 1 / 0
        self.agent.jobs = Mock()
        self.agent.jobs.results.side_effect = ValueError('invalid job state')
        with self.assertRaisesRegex(ValueError, 'invalid job state'):
            self.agent.sync()
        self.assertIsNone(self.agent.last_error)

    def test_unknown_or_core_rejection_never_retries_or_surfaces_raw_body(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'}}
        for body in (b'{"error":"Invalid balance"}', b'{"error":"secret=sensitive"}'):
            def reject(request, timeout):
                raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {}, io.BytesIO(body))
            with patch.object(self.agent.opener, 'open', side_effect=reject) as call:
                with self.assertRaises(urllib.error.HTTPError):
                    self.agent.sync()
                call.assert_called_once()
            self.assertNotIn('sensitive', self.agent.last_error)
