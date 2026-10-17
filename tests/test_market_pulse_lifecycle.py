import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from trader.config import load_config
from trader.engine import TradingEngine


class PulseLifecycleTests(unittest.TestCase):
    def engine(self, folder):
        config = load_config()
        config = replace(config, bot=replace(config.bot, mode="paper", database_path=Path(folder)/"spot.db"),
                         quant_arbitrage=replace(config.quant_arbitrage, enabled=False))
        return TradingEngine(config)

    def test_pulse_failure_does_not_interrupt_spot_or_futures_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.engine(folder)
            with patch.object(engine, "_create_market_pulse", side_effect=RuntimeError("synthetic")), patch.object(engine, "_run_supervised_loop") as loop:
                engine.run_forever()
                loop.assert_called_once()

    def test_one_owned_service_stops_even_on_loop_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.engine(folder)
            service = Mock()
            with patch.object(engine, "_create_market_pulse", return_value=service) as create, patch.object(engine, "_run_supervised_loop", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt): engine.run_forever()
            create.assert_called_once()
            service.start.assert_called_once()
            service.stop.assert_called_once()

    def test_start_and_cleanup_failures_do_not_escape_to_operating_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.engine(folder)
            service = Mock()
            service.start.side_effect = RuntimeError('thread unavailable')
            service.stop.side_effect = RuntimeError('cannot join unstarted thread')
            with patch.object(engine, '_create_market_pulse', return_value=service), patch.object(engine, '_run_supervised_loop') as loop:
                engine.run_forever()
            loop.assert_called_once()
            service.stop.assert_called_once()

    def test_stop_or_disabled_never_starts_pulse(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.engine(folder)
            with patch.object(engine, "_create_market_pulse") as create, patch.object(engine, "_run_supervised_loop"):
                engine.run_forever(lambda: True)
                engine.config = replace(engine.config, market_pulse=replace(engine.config.market_pulse, enabled=False))
                engine.run_forever()
            create.assert_not_called()
