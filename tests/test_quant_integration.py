"""Synthetic ownership, activation and owner-control safety for Quant SHADOW."""
import json
import io
import importlib.util
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from trader.config import load_config, QuantArbitrageSettings
from trader.dashboard import DashboardServer
from trader.database import Database
from trader.engine import TradingEngine
from trader.operational_controls import execute
from trader.quant_shadow import QuantShadowService, quant_snapshot


class QuantIntegrationTests(unittest.TestCase):
    def test_installed_control_script_dispatches_quant_without_spot_database(self):
        script=Path(__file__).resolve().parents[1]/'scripts/execute_paper_control.py'
        spec=importlib.util.spec_from_file_location('isolated_quant_control_script', script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();config=self.config(root)
            for action in ('quant_arbitrage_pause','quant_arbitrage_resume'):
                result={'ok':True,'quant':{'mode':'SHADOW','paused':action.endswith('pause')}}
                with patch.object(module,'ROOT',root), patch.object(module.sys,'argv',['control',str(root)]), \
                     patch.object(module.sys,'stdin',io.StringIO(json.dumps({'action':action,'payload':{}}))), \
                     patch.object(module.sys,'stdout',io.StringIO()) as output, \
                     patch.object(module,'source_settings',return_value=config), patch.object(module,'Database') as database, \
                     patch.object(module,'execute') as paper, patch.object(module,'atomic_json') as write, \
                     patch('trader.operational_controls.execute',return_value=result) as operation:
                    module.main()
                    operation.assert_called_once_with(root,action,{})
                    database.assert_not_called();paper.assert_not_called()
                    self.assertEqual(json.loads(output.getvalue()),result)
                    self.assertEqual(write.call_args.args[1]['action'],action)

    def config(self, root):
        base = load_config()
        return replace(base, bot=replace(base.bot, mode='paper', database_path=root/'data/spot.db', kill_switch_path=root/'data/spot-kill'),
            market_pulse=replace(base.market_pulse, enabled=False),
            quant_arbitrage=replace(base.quant_arbitrage, kill_switch_path=root/'data/quant-kill'),
            research=replace(base.research, automatic=False, report_path=root/'data/research.json'))

    def test_quant_startup_and_cleanup_failure_do_not_interrupt_existing_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = TradingEngine(self.config(Path(directory)))
            service = Mock()
            service.start.side_effect = RuntimeError('synthetic start error')
            service.stop.side_effect = RuntimeError('synthetic cleanup error')
            with patch.object(engine, '_create_quant_shadow', return_value=service), patch.object(engine, '_run_supervised_loop') as loop:
                engine.run_forever()
                loop.assert_called_once()
                service.stop.assert_called_once()

    def test_quant_shutdown_failure_still_stops_pulse_and_never_restarts_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = TradingEngine(self.config(Path(directory)))
            engine.config = replace(engine.config, market_pulse=replace(engine.config.market_pulse, enabled=True))
            quant, pulse = Mock(), Mock()
            quant.stop.side_effect = RuntimeError('synthetic stop error')
            with patch.object(engine, '_create_quant_shadow', return_value=quant), patch.object(engine, '_create_market_pulse', return_value=pulse), patch.object(engine, '_run_supervised_loop', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    engine.run_forever()
            quant.start.assert_called_once(); quant.stop.assert_called_once()
            pulse.start.assert_called_once(); pulse.stop.assert_called_once()

    def test_candidate_stop_or_disabled_observer_never_starts_quant(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = TradingEngine(self.config(Path(directory)))
            with patch.object(engine, '_create_quant_shadow') as create, patch.object(engine, '_run_supervised_loop'):
                engine.run_forever(lambda: True)
                engine.config = replace(engine.config, quant_arbitrage=replace(engine.config.quant_arbitrage, enabled=False))
                engine.run_forever()
            create.assert_not_called()

    def test_factory_subordinates_virtual_risk_to_existing_caps_and_locks_shadow(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = TradingEngine(self.config(Path(directory)))
            engine.config = replace(engine.config, risk=replace(engine.config.risk,
                risk_per_trade_pct=.001, max_total_exposure_pct=.1, max_positions=1,
                daily_loss_limit_pct=.005, weekly_loss_limit_pct=.01))
            with patch('trader.quant_shadow.QuantShadowService') as create:
                engine._create_quant_shadow()
            config = create.call_args.kwargs['config']
            self.assertEqual(config.mode, 'SHADOW')
            self.assertEqual(config.risk_per_trade, .001)
            self.assertEqual(config.daily_loss_limit, .005)
            self.assertEqual(config.weekly_loss_limit, .01)
            self.assertEqual(config.max_exposure_fraction, .1)
            self.assertEqual(config.max_positions, 1)
            self.assertGreaterEqual(config.fee_bps, 10)
            self.assertGreaterEqual(config.slippage_bps, 10)
            self.assertEqual(create.call_args.args[0], engine.config.bot.database_path.parent)
        for mode in ('LIVE', 'TESTNET', 'PAPER'):
            with self.assertRaises(ValueError):
                QuantArbitrageSettings(mode=mode)

    def test_config_refuses_execution_and_unreviewed_risk_overrides(self):
        text = (Path(__file__).resolve().parents[1]/'config.toml').read_text(encoding='utf-8')
        prefix = text.split('[quant_arbitrage]')[0]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'config.toml'
            for settings in ('enabled=true\nmode="LIVE"', 'enabled="yes"', 'enabled=true\nrisk_per_trade=1', 'enabled=true\nexecution_enabled=true'):
                target.write_text(prefix+'[quant_arbitrage]\n'+settings+'\n')
                with self.subTest(settings=settings), self.assertRaises(ValueError):
                    load_config(target)

    def test_owner_pause_is_independent_and_resume_does_not_clear_manual_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            service = QuantShadowService(config.bot.database_path.parent, source=Mock(), kill_switch_path=config.quant_arbitrage.kill_switch_path)
            service.initialize()
            (root/'data/spot-kill').write_text('owner Spot pause')
            (root/'data/futures-kill').write_text('owner Futures pause')
            with patch('trader.operational_controls.load_config', return_value=config):
                self.assertTrue(execute(root, 'quant_arbitrage_pause', {})['quant']['paused'])
                self.assertTrue(quant_snapshot(config.bot.database_path.parent)['paused'])
                self.assertFalse(execute(root, 'quant_arbitrage_resume', {})['quant']['paused'])
                config.quant_arbitrage.kill_switch_path.write_text('local emergency')
                with self.assertRaisesRegex(ValueError, 'requires local release'):
                    execute(root, 'quant_arbitrage_resume', {})
                with self.assertRaises(ValueError):
                    execute(root, 'quant_arbitrage_pause', {'mode': 'TESTNET'})
            self.assertEqual((root/'data/spot-kill').read_text(), 'owner Spot pause')
            self.assertEqual((root/'data/futures-kill').read_text(), 'owner Futures pause')
            self.assertTrue(config.quant_arbitrage.kill_switch_path.exists())

    def test_quant_control_routes_keep_auth_origin_and_empty_payload_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            dashboard = DashboardServer(config, Database(config.bot.database_path))
            dashboard.token = 'synthetic-owner'
            server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard._handler())
            thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            address = f'http://127.0.0.1:{server.server_port}'
            def post(payload, token=True, origin=address):
                headers = {'Content-Type':'application/json', 'Origin':origin}
                if token:headers['X-Dashboard-Token'] = dashboard.token
                return urllib.request.urlopen(urllib.request.Request(address+'/api/quant-arbitrage/pause', data=json.dumps(payload).encode(), headers=headers, method='POST'))
            try:
                with patch('trader.dashboard.subprocess.Popen') as run:
                    for payload,token,origin,code in (({},False,address,401), ({},True,'https://untrusted.example',403), ({'risk':1},True,address,409)):
                        with self.assertRaises(urllib.error.HTTPError) as rejected:
                            post(payload,token,origin)
                        self.assertEqual(rejected.exception.code,code)
                    run.assert_not_called()
                    with post({}) as response:self.assertEqual(response.status,202)
                    request = json.loads(run.return_value.stdin.write.call_args.args[0])
                    self.assertEqual(request, {'action':'quant_arbitrage_pause','payload':{}})
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
