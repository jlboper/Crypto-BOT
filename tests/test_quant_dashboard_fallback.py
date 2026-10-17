"""Unrelated dashboard failures cannot falsely label an initialized Quant as absent."""
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests.test_quant_shadow import Clock, Source
from trader.config import load_config
from trader.dashboard import DashboardServer
from trader.database import Database
from trader.quant_shadow import QuantShadowService


class QuantDashboardFallbackTests(unittest.TestCase):
    def config(self, root):
        base = load_config()
        return replace(base, bot=replace(base.bot, mode='paper', database_path=root/'spot.db'),
            quant_arbitrage=replace(base.quant_arbitrage, kill_switch_path=root/'quant-kill'),
            research=replace(base.research, automatic=False, report_path=root/'missing-research.json'))

    def test_broader_dashboard_failure_retains_independently_observed_quant_wallet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = Clock()
            clock.now = time.time()
            with patch('tests.test_quant_shadow.NOW', clock.now):
                service = QuantShadowService(root, clock=clock, source=Source(clock))
                try:
                    service.tick()
                    config = self.config(root)
                    server = DashboardServer(config, Database(config.bot.database_path))
                    before = service.snapshot()
                    with patch('trader.portal_snapshot.dashboard_snapshot', side_effect=RuntimeError('private unrelated ledger path')):
                        result = server._platform_snapshot()
                    self.assertTrue(result['quant']['initialized'])
                    self.assertEqual(result['quant']['state'], 'SHADOW')
                    self.assertEqual(result['quant']['performance']['equity'], before['performance']['equity'])
                    self.assertEqual(len(result['quant']['positions']), 1)
                    self.assertEqual(result['engine_catalog'][3]['state'], 'OBSERVED_EXTERNALLY')
                    self.assertEqual(result['portfolio_guardian']['state'], 'DEGRADED')
                    self.assertIsNone(result['portfolio_guardian']['scopes'][3]['gross_usdt'])
                    self.assertNotIn('private unrelated', json.dumps(result))
                finally:
                    service.stop()

    def test_unavailable_quant_during_dashboard_failure_is_unknown_not_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            server = DashboardServer(config, Database(config.bot.database_path))
            with patch('trader.portal_snapshot.dashboard_snapshot', side_effect=RuntimeError('private dashboard path')), \
                 patch('trader.portal_snapshot.quant_projection', side_effect=RuntimeError('private Quant path')):
                result = server._platform_snapshot()
            self.assertEqual(result['quant']['state'], 'DEGRADED')
            self.assertFalse(result['quant']['initialized'])
            self.assertFalse(result['quant']['execution_enabled'])
            self.assertTrue(all(value is None for value in result['quant']['performance'].values()))
            self.assertNotIn('private', json.dumps(result))

    def test_verified_missing_quant_ledger_can_still_report_not_started(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            server = DashboardServer(config, Database(config.bot.database_path))
            with patch('trader.portal_snapshot.dashboard_snapshot', side_effect=RuntimeError('unrelated failure')):
                result = server._platform_snapshot()
            self.assertEqual(result['quant']['state'], 'NOT_STARTED')
            self.assertFalse(result['quant']['initialized'])
            self.assertFalse((root/'quant-shadow.db').exists())
