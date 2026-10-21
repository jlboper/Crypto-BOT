"""Remote budgets apply after legacy compatibility, without weaker safety data."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import export_paper_snapshot
from tests.emit_guardian_fixture import make_dashboard
from trader.opportunity_observer import opportunity_snapshot
from trader.portal_snapshot import paper_scorecard


class RemoteOptionalBudgetTests(unittest.TestCase):
    def test_discarded_legacy_financial_detail_cannot_hide_observer(self):
        # Reproduces the previous ordering failure: a rich local snapshot fitted
        # below 480000 bytes but omitted the Observer. The actual remote shape
        # had ample space after its existing legacy financial omission.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            observer = opportunity_snapshot(root / 'missing-observer')

            def rich_scorecard(*args, **kwargs):
                value = paper_scorecard(*args, **kwargs)
                value['financial'] = {'existing_legacy_detail': 'x' * 462000}
                return value

            with patch('trader.portal_snapshot.paper_scorecard', side_effect=rich_scorecard), \
                 patch('trader.portal_snapshot.opportunity_shadow_projection', return_value=observer):
                local = make_dashboard(root / 'local')
                remote = make_dashboard(root / 'remote', remote=True)

        self.assertLessEqual(len(json.dumps(local, allow_nan=False).encode()), 480000)
        self.assertNotIn('opportunity_shadow', local)
        self.assertEqual(remote['opportunity_shadow'], observer)
        self.assertNotIn('financial', remote['paper_scorecard'])
        self.assertIn('portfolio_guardian', remote)
        self.assertIn('guardian_intelligence', remote)
        self.assertIn('capital_lab', remote)
        self.assertEqual(len(remote['engine_catalog']), 4)
        self.assertLessEqual(len(json.dumps(remote, allow_nan=False).encode()), 480000)

    def test_rich_marks_are_observed_before_remote_omissions(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            remote = make_dashboard(Path(directory), remote=True)
        future = remote['portfolio_guardian']['scopes'][1]
        self.assertEqual(future['gross_usdt'], 102)
        self.assertEqual(future['assets'][0]['mark_price'], 102)
        self.assertEqual(future['assets'][0]['nominal_stop_risk_usdt'], 8)
        self.assertNotIn('mark_price', remote['futures_forward']['positions'][0])
        self.assertNotIn('priced_at', remote['futures_forward']['positions'][0])
        self.assertEqual(remote['futures_forward']['positions'][0]['quantity'], 1)
        self.assertEqual(remote['futures_forward']['positions'][0]['stop_price'], 110)
        self.assertIn('native_protection', remote['futures_forward'])
        self.assertIn('pause_diagnostics', remote['futures_forward'])
        self.assertEqual(export_paper_snapshot.compatible_remote_projection(deepcopy(remote)), remote)

    def test_required_evidence_over_budget_still_fails_closed(self):
        def oversized_scorecard(*args, **kwargs):
            value = paper_scorecard(*args, **kwargs)
            value['required_evidence'] = 'x' * 480000
            return value

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, \
             patch('trader.portal_snapshot.paper_scorecard', side_effect=oversized_scorecard):
            with self.assertRaisesRegex(ValueError, 'Dashboard projection exceeds size budget'):
                make_dashboard(Path(directory), remote=True)

    def test_actual_exporter_requests_remote_budgeting(self):
        settings = object()
        output = io.StringIO()
        with patch('sys.argv', ['export_paper_snapshot.py', '--source', str(export_paper_snapshot.ROOT)]), \
             patch.object(export_paper_snapshot, 'source_settings', return_value=settings), \
             patch.object(export_paper_snapshot, 'dashboard_snapshot', return_value={'safe': True}) as snapshot, \
             redirect_stdout(output):
            export_paper_snapshot.main()
        snapshot.assert_called_once_with(settings,
            export_paper_snapshot.ROOT / 'data/research/latest.json', remote=True)
        self.assertEqual(json.loads(output.getvalue()), {'safe': True})
