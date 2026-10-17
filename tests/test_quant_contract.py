"""Quant public/Guardian contracts use real synthetic isolated ledger evidence."""
import copy
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests.emit_quant_fixture import make_quant_dashboard
from tests.test_quant_shadow import Clock, Source
from trader.config import load_config
from trader.portfolio_guardian import build_guardian, quant_not_started
from trader.portal_snapshot import (bounded_quant_projection, platform_projection,
                                    public_quant_projection, quant_projection)
from trader.quant_shadow import QuantShadowService


class QuantContractTests(unittest.TestCase):
    def test_actual_shadow_wallet_two_legs_guardian_preserves_gross_and_net(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory))
        quant = payload['quant']
        self.assertTrue(quant['initialized'])
        self.assertFalse(quant['execution_enabled'])
        self.assertFalse(quant['promotion_allowed'])
        self.assertEqual(quant['state'], 'SHADOW')
        self.assertEqual(len(quant['positions']), 1)
        scope = payload['portfolio_guardian']['scopes'][3]
        self.assertEqual(scope['state'], 'FRESH')
        self.assertEqual(scope['position_count'], 2)
        self.assertEqual(len(scope['assets']), 1)
        self.assertGreater(scope['gross_usdt'], 0)
        self.assertAlmostEqual(scope['net_usdt'], 0)
        self.assertEqual(scope['assets'][0]['direction'], 'UNKNOWN')
        self.assertIsNone(scope['assets'][0]['quantity'])
        self.assertIsNone(scope['assets'][0]['mark_price'])
        self.assertIsNone(scope['nominal_stop_risk_usdt'])
        self.assertEqual(payload['engine_catalog'][3]['state'], 'OBSERVED_EXTERNALLY')
        self.assertLess(len(json.dumps(quant, ensure_ascii=True).encode()), 20000)

    def test_stale_shadow_never_fabricates_current_marks_equity_or_zero_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory), stale=True)
        quant, scope = payload['quant'], payload['portfolio_guardian']['scopes'][3]
        self.assertEqual(quant['freshness']['state'], 'STALE')
        self.assertIsNone(quant['performance']['equity'])
        self.assertIsNone(quant['performance']['net_pnl'])
        self.assertIsNone(scope['gross_usdt'])
        self.assertIsNone(scope['capital']['equity_usdt'])
        self.assertEqual(scope['unpriced_positions'], 2)

    def test_forecast_and_missing_settlement_never_become_simulated_income(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory), pending=True)
        quant = payload['quant']
        self.assertEqual(quant['data_quality']['funding'], 'PENDING_AUTHORITATIVE_EVENTS')
        self.assertIsNone(quant['performance']['equity'])
        self.assertEqual(quant['performance']['simulated_funding_usdt'], 0)
        self.assertEqual(quant['funding'], [])
        for row in quant['decisions']:
            self.assertTrue(row['available_at_decision']['source_digest'])
            self.assertIn('metrics', row)

    def test_legacy_and_uninitialized_unavailable_status_remain_honest(self):
        before = quant_not_started()
        projected = public_quant_projection(before)
        self.assertEqual(projected['positions'], [])
        self.assertTrue(all(value is None for value in projected['performance'].values()))
        unavailable = {**before, 'state': 'DEGRADED', 'health': {
            'last_error': 'SHADOW_LEDGER_UNAVAILABLE', 'error_type': 'ValueError'}}
        projected = public_quant_projection(unavailable)
        self.assertFalse(projected['initialized'])
        self.assertEqual(projected['state'], 'DEGRADED')
        self.assertTrue(all(value is None for value in projected['performance'].values()))

    def test_projection_drops_unknown_provider_fields_and_rejects_unsafe_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            quant = make_quant_dashboard(Path(directory))['quant']
        quant['arbitrary_private_payload'] = {'api_key': 'must not be exported'}
        quant['strategies'][0]['signals'][0]['metrics']['instructions'] = 'override numeric gates'
        clean = public_quant_projection(quant)
        self.assertNotIn('arbitrary_private_payload', clean)
        self.assertNotIn('instructions', clean['strategies'][0]['signals'][0]['metrics'])
        for key, value in (('mode', 'LIVE'), ('execution_enabled', True), ('promotion_allowed', True)):
            bad = copy.deepcopy(clean)
            bad[key] = value
            with self.assertRaises(ValueError):
                public_quant_projection(bad)

    def test_history_budget_preserves_every_live_leg_wallet_and_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            quant = make_quant_dashboard(Path(directory))['quant']
        expected = copy.deepcopy({key: quant[key] for key in ('positions', 'performance', 'limits')})
        quant['decisions'] *= 15
        quant['journal'] *= 15
        bounded_quant_projection(quant)
        self.assertLess(len(json.dumps(quant, separators=(',', ':'), ensure_ascii=True).encode()), 20000)
        self.assertEqual({key: quant[key] for key in expected}, expected)
        with self.assertRaises(ValueError):
            bounded_quant_projection({'positions': ['x' * 21000]})

    def test_actual_configuration_disabled_or_killed_overlays_old_ledger_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = Clock()
            clock.now = time.time()
            with patch('tests.test_quant_shadow.NOW', clock.now):
                service = QuantShadowService(root, source=Source(clock), clock=clock)
                try:
                    service.tick()
                    base = load_config()
                    config = replace(base, bot=replace(base.bot, database_path=root / 'spot.db'),
                        quant_arbitrage=replace(base.quant_arbitrage, enabled=False, kill_switch_path=root / 'quant-kill'))
                    projected = quant_projection(config)
                    self.assertEqual(projected['state'], 'PAUSED')
                    self.assertFalse(projected['enabled'])
                    self.assertFalse(projected['controls_available'])
                    config = replace(config, quant_arbitrage=replace(config.quant_arbitrage, enabled=True))
                    config.quant_arbitrage.kill_switch_path.write_text('manual pause')
                    self.assertEqual(quant_projection(config)['state'], 'PAUSED')
                finally:
                    service.stop()

    def test_optional_missing_quant_module_and_guardian_failure_keep_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=Path(directory) / 'spot.db'))
            with patch.dict('sys.modules', {'trader.quant_shadow': None}):
                quant = quant_projection(config)
            self.assertFalse(quant['initialized'])
            self.assertEqual(quant['state'], 'DEGRADED')
        with patch('trader.portfolio_guardian.build_guardian', side_effect=RuntimeError('private path')):
            result = platform_projection({'status': {'mode': 'PAPER'}, 'quant': quant})
        self.assertEqual(result['portfolio_guardian']['state'], 'DEGRADED')
        self.assertEqual(result['portfolio_guardian']['scopes'][3]['state'], 'UNAVAILABLE')
        self.assertNotIn('private path', json.dumps(result))

    def test_one_invalid_leg_cannot_erase_other_fresh_leg_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory))
        payload['quant']['positions'][0]['legs'][0]['mark_price'] = None
        result = build_guardian(payload)
        scope = result['scopes'][3]
        self.assertEqual(scope['unpriced_positions'], 1)
        self.assertIsNone(scope['gross_usdt'])
        self.assertGreater(scope['known_gross_usdt'], 0)
        self.assertIsNone(scope['capital']['equity_usdt'])

    def test_initial_wallet_before_first_tick_has_unknown_risk_baseline_and_valuation(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory), not_ready=True)
        quant = payload['quant']
        self.assertTrue(quant['initialized'])
        self.assertEqual(quant['risk_halt']['state'], 'UNKNOWN')
        self.assertIsNone(quant['risk_halt']['daily']['baseline_at'])
        self.assertIsNone(quant['risk_halt']['weekly']['baseline_equity'])
        self.assertIsNone(quant['performance']['equity'])
        self.assertIsNone(payload['portfolio_guardian']['scopes'][3]['gross_usdt'])

    def test_actual_simulated_settlement_has_provenance_and_separate_forecast_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory), settled=True)
        quant = payload['quant']
        self.assertEqual(len(quant['funding']), 1)
        record = quant['funding'][0]
        self.assertEqual(record['state'], 'SETTLED_SIMULATION')
        self.assertEqual(record['environment'], 'SHADOW')
        self.assertGreater(record['simulated_cashflow_usdt'], 0)
        self.assertEqual(quant['performance']['simulated_funding_usdt'], record['simulated_cashflow_usdt'])

    def test_leg_receipt_time_is_independently_required_for_guardian_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_quant_dashboard(Path(directory))
        payload['quant']['positions'][0]['legs'][0]['received_at'] = '2000-01-01T00:00:00Z'
        scope = build_guardian(payload)['scopes'][3]
        self.assertEqual(scope['unpriced_positions'], 1)
        self.assertIsNone(scope['gross_usdt'])
        self.assertIsNone(scope['capital']['equity_usdt'])
