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

    def test_pulse_rejection_keeps_spot_futures_and_signed_update_delivery(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'},
            'futures_forward': {'killed': False}, 'market_pulse': {'mode': 'SHADOW'}}
        self.agent.update_provider = lambda: {'version': '0.10.31', 'enabled': True}
        requests = []
        def send(request, timeout):
            body = json.loads(request.data)
            requests.append(json.loads(json.dumps(body)))
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                    io.BytesIO(b'{"error":"Invalid Market Pulse status"}'))
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertEqual(len(requests), 2)
        self.assertIn('market_pulse', requests[0]['snapshot']['dashboard'])
        final = requests[1]['snapshot']
        self.assertNotIn('market_pulse', final['dashboard'])
        self.assertIn('futures_forward', final['dashboard'])
        self.assertEqual(final['bot_update']['version'], '0.10.31')
        self.assertEqual(self.agent.last_error, 'DASHBOARD_REJECTED:Invalid Market Pulse status')

    def test_futures_history_rejection_keeps_authenticated_update_delivery(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider=lambda:{'status':{'mode':'TESTNET'}}
        self.agent.jobs=Mock();self.agent.jobs.results.return_value=[]
        self.agent.update_provider=lambda:{'version':'0.10.28','enabled':True}
        calls=[]
        job={'id':3,'action':'update_install','release_id':'a'*64}
        def send(request,timeout):
            body=json.loads(request.data);calls.append(body)
            if len(calls)==1:
                raise urllib.error.HTTPError(request.full_url,400,'Bad Request',{},
                      io.BytesIO(b'{"error":"Invalid Futures forward status"}'))
            return io.BytesIO(json.dumps({'commands':[],'jobs':[job]}).encode())
        with patch.object(self.agent.opener,'open',side_effect=send):self.agent.sync()
        self.assertEqual(len(calls),2);self.assertNotIn('dashboard',calls[1]['snapshot'])
        self.assertEqual(calls[1]['snapshot']['bot_update']['version'],'0.10.28')
        self.agent.jobs.accept.assert_called_once_with(job)
        self.assertEqual(self.agent.last_error,'DASHBOARD_REJECTED:Invalid Futures forward status')

    def test_optional_guardian_quant_and_catalog_rejection_retains_all_existing_engines(self):
        Database(self.config.bot.database_path)
        labels = {'Invalid Portfolio Guardian status': 'portfolio_guardian',
                  'Invalid Quant Arbitrage status': 'quant', 'Invalid engine catalog': 'engine_catalog'}
        for label, field in labels.items():
            with self.subTest(label=label):
                self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'},
                    'futures_forward': {'killed': False}, 'market_pulse': {'mode': 'SHADOW'},
                    'portfolio_guardian': {'mode': 'OBSERVER'}, 'quant': {'mode': 'SHADOW'},
                    'engine_catalog': []}
                self.agent.update_provider = lambda: {'version': '0.10.35', 'enabled': True}
                requests = []
                def send(request, timeout):
                    requests.append(json.loads(request.data))
                    if len(requests) == 1:
                        raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                            io.BytesIO(json.dumps({'error': label}).encode()))
                    return io.BytesIO(b'{"commands":[],"jobs":[]}')
                with patch.object(self.agent.opener, 'open', side_effect=send):
                    self.agent.sync()
                self.assertEqual(len(requests), 2)
                final = requests[-1]['snapshot']
                for optional in ('portfolio_guardian', 'quant', 'engine_catalog'):
                    self.assertNotIn(optional, final['dashboard'])
                self.assertIn('futures_forward', final['dashboard'])
                self.assertIn('market_pulse', final['dashboard'])
                self.assertEqual(final['bot_update']['version'], '0.10.35')
                self.assertEqual(self.agent.last_error, 'DASHBOARD_REJECTED:' + label)

    def test_previous_worker_multiple_coupled_schema_rejections_need_only_one_retry(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'},
            'positions': [], 'futures_forward': {'killed': False}, 'market_pulse': {'mode': 'SHADOW'},
            'portfolio_guardian': {'mode': 'OBSERVER', 'scopes': [{'id': 'QUANT_ARBITRAGE', 'state': 'FRESH'}]},
            'quant': {'mode': 'SHADOW', 'state': 'SHADOW'},
            'engine_catalog': [{'id': 'QUANT_ARBITRAGE', 'state': 'OBSERVED_EXTERNALLY'}]}
        self.agent.update_provider = lambda: {'version': '0.10.37', 'enabled': True}
        self.agent.jobs = Mock()
        self.agent.jobs.results.return_value = [{'id': 7, 'status': 'completed'}]
        requests = []
        def send(request, timeout):
            body = json.loads(request.data)
            requests.append(body)
            dashboard = body['snapshot']['dashboard']
            # A real old receiver would reject each incompatible field in turn.
            for field, label in (('portfolio_guardian', 'Invalid Portfolio Guardian status'),
                                 ('quant', 'Invalid Quant Arbitrage status'),
                                 ('engine_catalog', 'Invalid engine catalog')):
                if field in dashboard:
                    raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                        io.BytesIO(json.dumps({'error': label}).encode()))
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertEqual(len(requests), 2)
        self.assertEqual(set(requests[-1]['snapshot']['dashboard']),
                         {'status', 'positions', 'futures_forward', 'market_pulse'})
        self.assertEqual(requests[-1]['snapshot']['bot_update']['version'], '0.10.37')
        self.assertEqual(requests[-1]['job_results'], [{'id': 7, 'status': 'completed'}])

    def test_previous_worker_unknown_quant_capability_drops_coupled_fields_once(self):
        Database(self.config.bot.database_path)
        self.agent.paper_controls = Mock(available=True, quant_available=True)
        self.agent.paper_controls.results.return_value = []
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'},
            'futures_forward': {}, 'market_pulse': {}, 'quant': {'state': 'SHADOW'},
            'portfolio_guardian': {}, 'engine_catalog': []}
        requests = []
        def send(request, timeout):
            body = json.loads(request.data)
            requests.append(body)
            if 'quant_controls' in body['snapshot']:
                raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                    io.BytesIO(b'{"error":"Unknown snapshot field"}'))
            self.assertEqual(set(body['snapshot']['dashboard']),
                             {'status', 'futures_forward', 'market_pulse'})
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        self.assertEqual(len(requests), 2)
        self.assertIs(requests[0]['snapshot']['quant_controls'], True)
        self.assertNotIn('quant_controls', requests[1]['snapshot'])
        self.assertTrue(requests[1]['snapshot']['operations_controls'])
        self.assertTrue(requests[1]['snapshot']['paper_controls'])

    def test_quant_capability_requires_literal_implemented_property(self):
        Database(self.config.bot.database_path)
        for capability in (False, None, Mock(), True):
            with self.subTest(capability=capability):
                self.agent.paper_controls = Mock(available=True, quant_available=capability)
                self.agent.paper_controls.results.return_value = []
                calls = []
                def send(request, timeout):
                    calls.append(json.loads(request.data))
                    return io.BytesIO(b'{"commands":[],"jobs":[]}')
                with patch.object(self.agent.opener, 'open', side_effect=send):
                    self.agent.sync()
                self.assertEqual('quant_controls' in calls[0]['snapshot'], capability is True)

    def test_previous_worker_unknown_field_omits_only_new_observer_contracts(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'},
            'futures_forward': {'killed': False}, 'market_pulse': {'mode': 'SHADOW'},
            'portfolio_guardian': {'mode': 'OBSERVER'}, 'quant': {'mode': 'SHADOW'}, 'engine_catalog': []}
        requests = []
        def send(request, timeout):
            requests.append(json.loads(request.data))
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                    io.BytesIO(b'{"error":"Unknown dashboard field"}'))
            return io.BytesIO(b'{"commands":[],"jobs":[]}')
        with patch.object(self.agent.opener, 'open', side_effect=send):
            self.agent.sync()
        final = requests[-1]['snapshot']['dashboard']
        self.assertEqual(set(final), {'status', 'futures_forward', 'market_pulse'})
        self.assertEqual(self.agent.last_error, 'DASHBOARD_REJECTED:Unknown dashboard field')

    def test_four_engine_worker_downgrade_omits_only_guardian_intelligence_once(self):
        Database(self.config.bot.database_path)
        self.config.bot.kill_switch_path.write_text('manual retained kill\n')
        before = self.config.bot.database_path.read_bytes()
        original = {'status': {'mode': 'PAPER'}, 'positions': [],
            'futures_forward': {'killed': False}, 'market_pulse': {'mode': 'SHADOW'},
            'portfolio_guardian': {'mode': 'OBSERVER'}, 'quant': {'mode': 'SHADOW'},
            'engine_catalog': [{'id': 'QUANT_ARBITRAGE'}],
            'guardian_intelligence': {'mode': 'SHADOW', 'execution_enabled': False}}
        for label in ('Unknown dashboard field', 'Invalid Guardian Intelligence status'):
            with self.subTest(label=label):
                self.agent.dashboard_provider = lambda: json.loads(json.dumps(original))
                self.agent.paper_controls = Mock(available=True, quant_available=True)
                self.agent.paper_controls.results.return_value = []
                self.agent.update_provider = lambda: {'version': '0.10.42', 'enabled': True}
                self.agent.jobs = Mock()
                self.agent.jobs.results.return_value = [{'id': 7, 'status': 'completed'}]
                job = {'id': 8, 'action': 'update_install', 'release_id': 'a'*64}
                requests, auth = [], []
                def send(request, timeout):
                    requests.append(json.loads(request.data))
                    auth.append(request.get_header('Authorization'))
                    if len(requests) == 1:
                        raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                            io.BytesIO(json.dumps({'error': label}).encode()))
                    return io.BytesIO(json.dumps({'commands': [], 'jobs': [job]}).encode())
                with patch.object(self.agent.opener, 'open', side_effect=send):
                    self.agent.sync()
                self.assertEqual(len(requests), 2)
                expected = {key: value for key, value in original.items() if key != 'guardian_intelligence'}
                self.assertEqual(requests[1]['snapshot']['dashboard'], expected)
                self.assertIn('guardian_intelligence', requests[0]['snapshot']['dashboard'])
                self.assertIs(requests[1]['snapshot']['quant_controls'], True)
                self.assertIs(requests[1]['snapshot']['operations_controls'], True)
                self.assertEqual(requests[1]['snapshot']['bot_update']['version'], '0.10.42')
                self.assertEqual(requests[1]['job_results'], [{'id': 7, 'status': 'completed'}])
                self.assertEqual(auth, ['Bearer '+'x'*43]*2)
                self.agent.jobs.accept.assert_called_once_with(job)
                self.assertEqual(self.agent.last_error, 'DASHBOARD_REJECTED:'+label)
        self.assertEqual(self.config.bot.kill_switch_path.read_text(), 'manual retained kill\n')
        self.assertEqual(self.config.bot.database_path.read_bytes(), before)

    def test_guardian_incompatible_retry_is_bounded_and_private_rejection_is_redacted(self):
        Database(self.config.bot.database_path)
        self.agent.dashboard_provider = lambda: {'status': {'mode': 'PAPER'},
            'quant': {'state': 'SHADOW'}, 'guardian_intelligence': {'mode': 'SHADOW'}}
        requests = []
        def send(request, timeout):
            requests.append(json.loads(request.data))
            reason = 'Invalid Guardian Intelligence status' if len(requests) == 1 else 'private sk-synthetic-secret body'
            raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {},
                io.BytesIO(json.dumps({'error': reason}).encode()))
        with patch.object(self.agent.opener, 'open', side_effect=send), self.assertRaises(urllib.error.HTTPError):
            self.agent.sync()
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]['snapshot']['dashboard'],
                         {'status': {'mode': 'PAPER'}, 'quant': {'state': 'SHADOW'}})
        self.assertEqual(self.agent.last_error, 'HTTPError:400')
        self.assertNotIn('private', self.agent.last_error)

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

    def test_broken_supervisor_metadata_keeps_heartbeat_but_withdraws_rollout(self):
        Database(self.config.bot.database_path)
        for provider in ('update_provider', 'restore_provider'):
            with self.subTest(provider=provider):
                self.agent.update_provider = lambda: {'enabled': True}
                self.agent.restore_provider = lambda: {'enabled': True}
                def unavailable():
                    raise ModuleNotFoundError('private/path/native_protection_compat')
                setattr(self.agent, provider, unavailable)
                received = []
                def send(request, timeout):
                    received.append(json.loads(request.data))
                    return io.BytesIO(b'{"commands":[],"jobs":[]}')
                with patch.object(self.agent.opener, 'open', side_effect=send):
                    self.agent.sync()
                self.assertEqual(len(received), 1)
                snapshot = received[0]['snapshot']
                self.assertEqual(snapshot['mode'], self.config.bot.mode.upper())
                self.assertEqual(snapshot['update_state'], 'manual_signed_install_only')
                self.assertNotIn('bot_update', snapshot)
                self.assertNotIn('bot_restore', snapshot)
                self.assertEqual(self.agent.last_error, 'SUPERVISOR_UNAVAILABLE:ModuleNotFoundError')

        self.agent.update_provider = lambda: None
        self.agent.restore_provider = lambda: None
        with patch.object(self.agent.opener, 'open', return_value=io.BytesIO(b'{"commands":[],"jobs":[]}')) as send:
            self.agent.sync()
        self.assertEqual(json.loads(send.call_args.args[0].data)['snapshot']['update_state'], 'signed_rollout')
        self.assertIsNone(self.agent.last_error)

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
