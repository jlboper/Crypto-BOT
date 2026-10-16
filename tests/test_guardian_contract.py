"""Optional Observer projection cannot remove existing financial/protection views."""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from scripts.export_paper_snapshot import compatible_remote_projection
from tests.emit_guardian_fixture import make_dashboard
from trader.portal_snapshot import platform_projection


class GuardianContractTests(unittest.TestCase):
    def test_real_local_marks_build_guardian_before_legacy_remote_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            local = make_dashboard(Path(directory))
        guardian = deepcopy(local['portfolio_guardian'])
        future = guardian['scopes'][1]
        self.assertEqual(future['gross_usdt'], 102)
        self.assertEqual(future['net_usdt'], -102)
        self.assertEqual(future['assets'][0]['mark_price'], 102)
        self.assertEqual(future['assets'][0]['nominal_stop_risk_usdt'], 8)
        self.assertIn('mark_price', local['futures_forward']['positions'][0])
        remote = compatible_remote_projection(deepcopy(local))
        self.assertNotIn('mark_price', remote['futures_forward']['positions'][0])
        self.assertNotIn('priced_at', remote['futures_forward']['positions'][0])
        self.assertEqual(remote['portfolio_guardian'], guardian)
        self.assertLess(len(json.dumps(remote, allow_nan=False).encode()), 480_000)
        self.assertFalse(remote['quant']['enabled'])
        self.assertTrue(all(value is None for value in remote['quant']['performance'].values()))
        self.assertEqual(len(remote['engine_catalog']), 4)

    def test_guardian_failure_and_unserializable_result_isolate_optional_fallback(self):
        for result in (None, {'unsafe': float('nan')}, {'unsafe': 'x' * 15000}):
            with self.subTest(result=str(result)[:40]):
                with patch('trader.portfolio_guardian.build_guardian', return_value=result):
                    projected = platform_projection({'status': {'mode': 'PAPER'}})
                self.assertEqual(projected['portfolio_guardian']['state'], 'DEGRADED')
                self.assertEqual(len(projected['portfolio_guardian']['scopes']), 4)
                self.assertFalse(projected['portfolio_guardian']['can_veto'])
                self.assertEqual(projected['quant']['state'], 'NOT_STARTED')

    def test_real_snapshot_guardian_exception_retains_spot_futures_pulse(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = make_dashboard(Path(directory), degraded=True)
        self.assertEqual(payload['portfolio_guardian']['state'], 'DEGRADED')
        self.assertEqual(len(payload['positions']), 1)
        self.assertEqual(len(payload['futures_forward']['positions']), 1)
        self.assertEqual(payload['market_pulse']['state'], 'NOT_STARTED')
        self.assertNotIn('private-data', json.dumps(payload))

    def test_missing_observer_module_does_not_break_existing_dashboard(self):
        with patch.dict('sys.modules', {'trader.portfolio_guardian': None}):
            self.assertEqual(platform_projection({'status': {'mode': 'PAPER'}}), {})

    def test_optional_expansion_near_dashboard_budget_preserves_existing_evidence(self):
        payload = {'status': {'mode': 'PAPER'}, 'events': [{'message': 'x' * 479000}]}
        before = deepcopy(payload)
        self.assertLess(len(json.dumps(payload).encode()), 480_000)
        self.assertEqual(platform_projection(payload), {})
        self.assertEqual(payload, before)
