"""Remote-only journal detail thinning; numerical and protection data stay intact."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.emit_guardian_fixture import make_dashboard
from tests.emit_opportunity_fixture import make_opportunity
from trader import portal_snapshot as portal
from trader.database import Database


LIMIT=480_000


def encoded_size(payload):
    return len(json.dumps(payload,allow_nan=False).encode())


class OpportunityProjectionBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer=make_opportunity(at=1_800_000_000.)

    def base(self):
        return {'status':{'mode':'PAPER'},'research':{'mode':'RESEARCH_ONLY','assets':[],'note':''},
            'positions':[{'symbol':'BTCUSDT','quantity':1,'stop_price':90}],
            'futures_forward':{'positions':[{'symbol':'ETHUSDT','quantity':2}],
                'native_protection':{'positions':{'ETHUSDT':{'status':'ARMED'}}},
                'pause_diagnostics':{'active':True,'pending_reconciliation':True}},
            'guardian_intelligence':{'preserve':'existing intelligence'},
            'capital_lab':{'preserve':'independent synthetic evidence'}}

    def candidate(self,count):
        return {**self.observer,'recent_records':self.observer['recent_records'][:count]}

    def pad(self,payload,candidate,*,extra=0,unicode=False):
        needed=LIMIT+extra-encoded_size({**payload,'opportunity_shadow':candidate})
        self.assertGreaterEqual(needed,0)
        payload['research']['note']=('ñ'*(needed//6)+'x'*(needed%6)) if unicode else 'x'*needed
        self.assertEqual(encoded_size({**payload,'opportunity_shadow':candidate}),LIMIT+extra)
        return payload

    def test_full_projection_fits_without_mutating_payload_or_observer(self):
        payload=self.base();before=deepcopy((payload,self.observer))
        result=portal._fit_opportunity_shadow(payload,self.observer)
        self.assertEqual(result,self.observer)
        self.assertIsNot(result,self.observer)
        self.assertIsNot(result['recent_records'],self.observer['recent_records'])
        self.assertEqual((payload,self.observer),before)
        result['recent_records'].pop()
        self.assertEqual(self.observer,before[1])

    def test_largest_newest_prefix_is_kept_and_only_oldest_rows_are_removed(self):
        payload=self.pad(self.base(),self.candidate(3));before=deepcopy(payload)
        result=portal._fit_opportunity_shadow(payload,self.observer)
        self.assertEqual(result['recent_records'],self.observer['recent_records'][:3])
        self.assertEqual(encoded_size({**payload,'opportunity_shadow':result}),LIMIT)
        self.assertGreater(encoded_size({**payload,'opportunity_shadow':self.candidate(4)}),LIMIT)
        self.assertEqual(payload,before)
        for key in self.observer:
            if key!='recent_records':self.assertEqual(result[key],self.observer[key],key)

    def test_summary_only_keeps_counts_scopes_freshness_and_all_disabled_authority(self):
        payload=self.pad(self.base(),self.candidate(0))
        result=portal._fit_opportunity_shadow(payload,self.observer)
        self.assertEqual(result['recent_records'],[])
        self.assertGreater(result['health']['records'],0)
        for key in ('health','coverage','scopes','freshness','updated_at','state','autonomy_level',
                    'controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed'):
            self.assertEqual(result[key],self.observer[key])
        self.assertEqual(encoded_size({**payload,'opportunity_shadow':result}),LIMIT)

    def test_summary_over_budget_is_omitted_without_changing_existing_dashboard(self):
        payload=self.pad(self.base(),self.candidate(0),extra=1)
        before=deepcopy((payload,self.observer))
        self.assertIsNone(portal._fit_opportunity_shadow(payload,self.observer))
        self.assertEqual((payload,self.observer),before)
        self.assertLess(encoded_size(payload),LIMIT)

    def test_exact_boundary_uses_default_ascii_escaping_not_compact_utf8_size(self):
        payload=self.pad(self.base(),self.candidate(1),unicode=True)
        full={**payload,'opportunity_shadow':self.observer}
        self.assertGreater(encoded_size(full),LIMIT)
        self.assertLess(len(json.dumps(full,ensure_ascii=False,separators=(',',':')).encode()),LIMIT)
        result=portal._fit_opportunity_shadow(payload,self.observer)
        self.assertEqual(result['recent_records'],self.observer['recent_records'][:1])
        self.assertEqual(encoded_size({**payload,'opportunity_shadow':result}),LIMIT)
        payload['research']['note']+='x'
        result=portal._fit_opportunity_shadow(payload,self.observer)
        self.assertEqual(result['recent_records'],[])

    def test_at_most_seven_candidates_are_serialized_and_invalid_cardinality_is_not_expanded(self):
        payload=self.pad(self.base(),self.candidate(0),extra=1)
        original=portal.json.dumps
        with patch.object(portal.json,'dumps',wraps=original) as dump:
            self.assertIsNone(portal._fit_opportunity_shadow(payload,self.observer))
        self.assertEqual(dump.call_count,7)
        for invalid in (None,{},dict(self.observer,recent_records=None),
                        dict(self.observer,recent_records=self.observer['recent_records']+[self.observer['recent_records'][0]])):
            with self.subTest(kind=type(invalid).__name__),patch.object(portal.json,'dumps') as dump:
                self.assertIsNone(portal._fit_opportunity_shadow({},invalid))
                dump.assert_not_called()

    def test_existing_protection_and_optional_evidence_are_never_thinned_to_fit_observer(self):
        payload=self.pad(self.base(),self.candidate(2));before=deepcopy(payload)
        result=portal._fit_opportunity_shadow(payload,self.observer)
        self.assertEqual(len(result['recent_records']),2)
        for key in ('positions','futures_forward','guardian_intelligence','capital_lab'):
            self.assertEqual(payload[key],before[key])
        self.assertTrue(payload['futures_forward']['pause_diagnostics']['active'])
        self.assertTrue(payload['futures_forward']['pause_diagnostics']['pending_reconciliation'])

    def padded_dashboard(self,root,*,padding=0,remote=True):
        # These are real new synthetic ledgers and a normal RESEARCH_ONLY report.
        # Each public event remains within the existing 1000-character bound;
        # ASCII escaping makes their default JSON cost exceed compact UTF-8.
        original=portal.dashboard_snapshot
        def populate(config,**kwargs):
            db=Database(config.bot.database_path)
            for index in range(50):db.event('INFO','ñ'*1000)
            report={'mode':'RESEARCH_ONLY','assets':[],'note':'x'*padding}
            self.assertLess(encoded_size(report),240_000)
            config.research.report_path.write_text(json.dumps(report,allow_nan=False),encoding='utf-8')
            return original(config,**kwargs)
        with patch('tests.emit_guardian_fixture.dashboard_snapshot',side_effect=populate):
            return make_dashboard(root,remote=remote)

    def test_remote_dashboard_retains_summary_when_valid_unicode_history_fills_budget(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root=Path(directory)
            with patch.object(portal,'opportunity_shadow_projection',return_value=None):
                base=self.padded_dashboard(root/'base')
            # Allow ordinary clock/health timestamp-size differences, but less
            # than one recent event. No engine/protection field is removed.
            empty=self.candidate(0)
            overhead=encoded_size({**base,'opportunity_shadow':empty})-encoded_size(base)
            padding=LIMIT-encoded_size(base)-overhead-256
            self.assertGreater(padding,0)
            captured=[]
            fit=portal._fit_opportunity_shadow
            def preserve(payload,value):
                captured.append(deepcopy(payload))
                return fit(payload,value)
            with patch.object(portal,'opportunity_shadow_projection',return_value=self.observer), \
                    patch.object(portal,'_fit_opportunity_shadow',side_effect=preserve):
                remote=self.padded_dashboard(root/'remote',padding=padding)
        self.assertEqual(len(captured),1)
        self.assertIn('opportunity_shadow',remote)
        self.assertEqual(remote['opportunity_shadow']['recent_records'],[])
        self.assertEqual(remote['opportunity_shadow']['health'],self.observer['health'])
        self.assertEqual(remote['opportunity_shadow']['coverage'],self.observer['coverage'])
        self.assertLessEqual(encoded_size(remote),LIMIT)
        self.assertEqual({key:value for key,value in remote.items() if key!='opportunity_shadow'},captured[0])
        for key in ('guardian_intelligence','capital_lab','portfolio_guardian','engine_catalog'):
            self.assertIn(key,remote)
        self.assertIn('native_protection',remote['futures_forward'])
        self.assertIn('pause_diagnostics',remote['futures_forward'])

    def test_local_projection_keeps_existing_all_or_nothing_behavior(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root=Path(directory)
            with patch.object(portal,'opportunity_shadow_projection',return_value=self.observer), \
                    patch.object(portal,'_fit_opportunity_shadow',side_effect=AssertionError('local used remote fitter')):
                local=self.padded_dashboard(root/'local',remote=False)
        self.assertEqual(local['opportunity_shadow'],self.observer)


if __name__=='__main__':unittest.main()
