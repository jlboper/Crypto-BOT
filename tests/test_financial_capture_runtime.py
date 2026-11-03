from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from trader.config import load_config
from trader.engine import TradingEngine
from trader.financial_capture_runtime import CombinedFinancialCaptureService, FinancialCaptureWorker, create_capture_worker


class FinancialCaptureRuntimeTests(unittest.TestCase):
    def test_combined_services_split_budget_and_keep_failure_and_stop_separate(self):
        first,second = Mock(),Mock()
        first.tick.side_effect=OSError('synthetic-private-provider-text')
        second.tick.return_value={'state':'SYNTHETIC_OBSERVED','execution_enabled':False}
        service=CombinedFinancialCaptureService((first,second))
        result=service.tick(max_calls=15)
        first.tick.assert_called_once_with(max_calls=8,should_stop=None)
        second.tick.assert_called_once_with(max_calls=7,should_stop=None)
        self.assertEqual(result['services'][0],{'state':'CAPTURE_SERVICE_UNAVAILABLE','execution_enabled':False})
        self.assertEqual(result['services'][1]['state'],'SYNTHETIC_OBSERVED')
        self.assertFalse(result['ready_for_live'])
        first.tick.reset_mock();second.tick.reset_mock()
        stopped=threading.Event()
        first.tick.side_effect=lambda **kwargs: (stopped.set() or {'state':'STOPPED'})
        service.tick(max_calls=16,should_stop=stopped.is_set)
        first.tick.assert_called_once()
        second.tick.assert_not_called()

    def config(self, root):
        config = load_config()
        return replace(config, bot=replace(config.bot, mode='paper', database_path=Path(root)/'spot.db'),
            market_pulse=replace(config.market_pulse, enabled=False),
            quant_arbitrage=replace(config.quant_arbitrage, enabled=False),
            guardian_intelligence=replace(config.guardian_intelligence, enabled=False))

    def test_absent_vault_does_not_create_evidence_or_load_credentials(self):
        with tempfile.TemporaryDirectory() as root, patch('trader.financial_capture_runtime.LiveCredentialVault') as vault:
            self.assertIsNone(create_capture_worker(self.config(root)))
            vault.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_factory_defers_secret_read_and_uses_existing_forward_universe(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'live-preproduction/credentials.dpapi'
            path.parent.mkdir();path.write_bytes(b'synthetic-not-a-vault')
            with patch('trader.financial_capture_runtime.LiveCredentialVault') as vault:
                worker=create_capture_worker(self.config(root))
                vault.return_value.read.assert_not_called()
                self.assertIsInstance(worker, FinancialCaptureWorker)
                self.assertIn('BTCUSDT', worker.service.symbols)

    def test_capture_factory_sees_current_registered_observer_before_start(self):
        with tempfile.TemporaryDirectory() as root:
            engine=TradingEngine(self.config(root))
            observer,worker=Mock(),Mock()
            observer.start.return_value=True
            worker.start.return_value=True
            current={'registered':False}
            def register(value):
                self.assertIs(value,observer)
                current['registered']=True
                return True
            def capture(config):
                self.assertTrue(current['registered'])
                return worker
            with patch('trader.preproduction_runtime.create_observer',return_value=observer), \
                    patch('trader.preproduction_runtime.register_observer',side_effect=register), \
                    patch('trader.financial_capture_runtime.create_capture_worker',side_effect=capture), \
                    patch.object(engine,'_run_supervised_loop'):
                engine.run_forever()
            worker.start.assert_called_once()
            worker.stop.assert_called_once()

    def test_one_owned_thread_with_bounded_get_budget_and_stop(self):
        with tempfile.TemporaryDirectory() as root:
            entered=threading.Event()
            service=Mock()
            service.tick.side_effect=lambda **kwargs: (entered.set() or {'state':'SYNTHETIC','execution_enabled':False})
            worker=FinancialCaptureWorker(service,Path(root)/'status.json',interval_seconds=60)
            self.assertTrue(worker.start())
            try:
                self.assertTrue(entered.wait(3))
                self.assertFalse(worker.start())
            finally:
                self.assertTrue(worker.stop())
            service.tick.assert_called_once_with(max_calls=16, should_stop=worker._stop.is_set)

    def test_stop_is_observed_in_active_capture_and_joins_before_status_publish(self):
        with tempfile.TemporaryDirectory() as root:
            entered=threading.Event()
            def tick(*,max_calls,should_stop):
                entered.set()
                while not should_stop():
                    threading.Event().wait(0.01)
                return {'state':'CAPTURE_STOP_REQUESTED'}
            service=Mock();service.tick.side_effect=tick
            path=Path(root)/'status.json'
            worker=FinancialCaptureWorker(service,path,interval_seconds=60)
            self.assertTrue(worker.start())
            self.assertTrue(entered.wait(3))
            self.assertTrue(worker.stop())
            self.assertFalse(worker._thread.is_alive())
            self.assertFalse(path.exists())

    def test_stop_cannot_report_success_while_racing_start_has_not_assigned_thread(self):
        with tempfile.TemporaryDirectory() as root:
            entering_clear,allow_clear=threading.Event(),threading.Event()
            stop_called,stop_finished=threading.Event(),threading.Event()
            service=Mock();service.tick.return_value={'state':'SYNTHETIC'}
            worker=FinancialCaptureWorker(service,Path(root)/'status.json',interval_seconds=60)
            original_clear=worker._stop.clear
            def paused_clear():
                entering_clear.set()
                if not allow_clear.wait(3):
                    raise RuntimeError('bounded synthetic start did not resume')
                original_clear()
            result=[]
            def stop():
                stop_called.set()
                result.append(worker.stop())
                stop_finished.set()
            starter=threading.Thread(target=worker.start)
            stopper=threading.Thread(target=stop)
            with patch.object(worker._stop,'clear',side_effect=paused_clear):
                starter.start()
                try:
                    self.assertTrue(entering_clear.wait(3))
                    stopper.start()
                    self.assertTrue(stop_called.wait(3))
                    self.assertFalse(stop_finished.wait(0.05))
                finally:
                    allow_clear.set()
                    starter.join(3)
                    if stopper.ident is not None:
                        stopper.join(3)
                    worker.stop()
            self.assertEqual(result,[True])
            self.assertTrue(stop_finished.is_set())
            self.assertFalse(worker._thread.is_alive())

    def test_worker_failure_cannot_escape_into_protective_engine_loop(self):
        with tempfile.TemporaryDirectory() as root:
            engine=TradingEngine(self.config(root))
            with patch('trader.financial_capture_runtime.create_capture_worker',side_effect=OSError('synthetic')), \
                 patch.object(engine,'_run_supervised_loop') as loop:
                engine.run_forever()
            loop.assert_called_once()

    def test_engine_stops_capture_on_loop_exception_and_never_starts_if_stopped(self):
        with tempfile.TemporaryDirectory() as root:
            engine=TradingEngine(self.config(root));worker=Mock();worker.start.return_value=True
            with patch('trader.financial_capture_runtime.create_capture_worker',return_value=worker), \
                 patch.object(engine,'_run_supervised_loop',side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):engine.run_forever()
            worker.start.assert_called_once();worker.stop.assert_called_once()
            with patch('trader.financial_capture_runtime.create_capture_worker') as factory, \
                 patch.object(engine,'_run_supervised_loop'):
                engine.run_forever(lambda:True)
            factory.assert_not_called()
