"""Synthetic Testnet/Demo source pipeline, never operating accounts."""
from copy import deepcopy
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.account_inventory import TestnetReadOnlyTransport,InventoryError
from trader.config import load_config
from trader.financial_capture import _load_cipher,_save_cipher
from trader.financial_evidence import digest,seal_cut,FinancialEvidenceStore
from trader.financial_evidence_io import read_financial_overlay
from trader.testnet_financial_capture import TestnetFinancialCaptureService,create_testnet_capture_service
from trader.testnet_financial_capture import read_next_original,read_current_original
from trader.operational_cohort import OperationalCohortStore,FLAGS
from trader.migration_evidence import register_forward_cohort
import sqlite3
from tests.test_financial_evidence import fixture,iso


def cipher(raw):return bytes(x^0xa5 for x in raw)


class TestnetFinancialProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.f=fixture();self.now=[self.f[3].timestamp()-3633]
        self.pairs={'SPOT_TESTNET':('k'*64,'s'*64)}
        self.uid=123
        self.calls=[]

    def original(self,path,scope,*,after,at):
        return (self.f[0],self.f[1]) if after < self.f[3].timestamp()-3600 else None

    def ledger(self,path,scope,*,at,since):
        return {'at':iso(self.f[3]),'environment':scope,'positions':[],'trades':[],
                'native_protection':None,'scope':'LOCAL_LEDGER_ONLY'}

    def get(self,scope,endpoint,params=None):
        self.calls.append((scope,endpoint,params))
        if endpoint.endswith('/account'):
            return {'uid':self.uid,'balances':[{'asset':'USDT','free':'1','locked':'0'}]}
        return []

    def service(self,materializer=None,**extra):
        return TestnetFinancialCaptureService(lambda:self.pairs,self.root,
            ledger_paths={'SPOT_TESTNET':self.root/'no-ledger-constructor.db'},
            symbols={'SPOT_TESTNET':['BTCUSDT']},clock=lambda:self.now[0],
            protect=cipher,unprotect=cipher,ledger_reader=self.ledger,
            original_reader=self.original,materializer=materializer,**extra)

    def baseline(self,service):
        result=service.tick(max_calls=8)
        self.assertEqual(result['state'],'PROSPECTIVE_BASELINE_OR_WINDOW_PENDING')
        self.now[0]=self.f[3].timestamp()

    def bundle(self,packet,*,whole=False):
        bundle=deepcopy(self.f[2]);bundle['unit_scale']=8
        account=digest({'environment':'SPOT_TESTNET','reported_uid':'123'})
        bundle['account_ref']=account
        for name in ('ledger','exchange'):
            bundle[name]['account_ref']=account
            bundle[name]['coverage']['scope']='ALL_ACCOUNT' if whole else 'BOUNDED_SYMBOLS'
            bundle[name]=seal_cut(bundle[name])
        return bundle

    def test_factory_defers_environment_and_creates_no_source_directory(self):
        config=load_config()
        config=replace(config,bot=replace(config.bot,mode='testnet',database_path=self.root/'spot.db'))
        with patch('trader.testnet_financial_capture.os.getenv') as env:
            service=create_testnet_capture_service(config)
            self.assertIsInstance(service,TestnetFinancialCaptureService)
            self.assertIs(service.original_reader,read_current_original)
        env.assert_not_called();self.assertEqual(list(self.root.iterdir()),[])

    def test_default_retains_actual_sources_without_qualifying_or_resetting_history(self):
        service=self.service()
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service)
            result=service.tick(max_calls=8)
        self.assertEqual(result['state'],'RAW_CAPTURED_QUALIFICATION_BLOCKED')
        self.assertEqual(result['retained_windows'],1)
        self.assertFalse(result['financial_window_complete']);self.assertFalse(result['history_reset'])
        scope=service.directory/'SPOT_TESTNET'
        self.assertFalse((scope/'financial-evidence.sqlite3').exists())
        self.assertEqual(len(list((scope/'responses').glob('*.dpapi'))),7)
        self.assertEqual(len(list((scope/'windows').glob('*/sources.dpapi'))),1)
        self.assertTrue(all(not p.read_bytes().find(b'uid')>=0 for p in (scope/'responses').glob('*.dpapi')))
        self.assertEqual(json.loads((scope/'binding.json').read_text())['identity_state'],'REPORTED')

    def test_materializer_can_append_incomplete_window_and_verified_overlay_without_fake_scope(self):
        service=self.service(materializer=self.bundle)
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);service.tick(max_calls=8)
        scope=service.directory/'SPOT_TESTNET'
        journal=scope/'financial-evidence.sqlite3';anchor=scope/'financial-evidence.anchor.json'
        self.assertEqual(FinancialEvidenceStore(journal).verify_chain()['records'],1)
        overlay=read_financial_overlay(journal,anchor,self.f[0],[self.f[1]],now=iso(self.f[3]),
            expected_cohort_digest=self.f[1]['cohort_digest'],
            expected_account_ref=digest({'environment':'SPOT_TESTNET','reported_uid':'123'}),expected_unit_scale=8)
        self.assertTrue(overlay['journal_verified']);self.assertEqual(overlay['valid_windows'],0)
        self.assertFalse(overlay['coverage_verified'])

    def test_callback_cannot_relabel_bounded_sources_as_all_account(self):
        service=self.service(materializer=lambda p:self.bundle(p,whole=True))
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);result=service.tick(max_calls=8)
        self.assertIn('TESTNET_MATERIALIZER_CANNOT_EXPAND_SOURCE_SCOPE',result['reason_codes'])
        self.assertFalse((service.directory/'SPOT_TESTNET'/'financial-evidence.sqlite3').exists())

    def test_last_baseline_get_failure_retries_without_advancing_failed_response(self):
        fail=[True]
        def get(scope,endpoint,params=None):
            if endpoint.endswith('/openOrderList') and fail[0]:
                fail[0]=False;raise InventoryError('READ_NETWORK_UNAVAILABLE')
            return self.get(scope,endpoint,params)
        service=self.service()
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=get):
            first=service.tick(max_calls=8)
            self.assertIn('READ_NETWORK_UNAVAILABLE',first['reason_codes'])
            self.baseline(service)
            self.assertEqual(service.tick(max_calls=8)['retained_windows'],1)
        state=_load_cipher(service.directory/'controller.dpapi',cipher)
        self.assertEqual(len(state['scopes']['SPOT_TESTNET']['failed_refs']),1)

    def test_current_account_change_between_original_cuts_blocks_materialization(self):
        service=self.service(materializer=self.bundle)
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);self.uid=124;result=service.tick(max_calls=8)
        self.assertIn('TESTNET_REPORTED_ACCOUNT_CHANGED',result['reason_codes'])
        self.assertFalse((service.directory/'SPOT_TESTNET'/'financial-evidence.sqlite3').exists())

    def test_unknown_identity_does_not_permanently_bind_or_block_later_reported_cuts(self):
        self.uid=None
        service=self.service()
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);service.tick(max_calls=8)
            scope=service.directory/'SPOT_TESTNET'
            self.assertEqual(json.loads((scope/'binding.json').read_text())['identity_state'],'UNKNOWN')
            self.assertEqual(list((scope/'bindings').glob('*.json')),[])
            old=list((scope/'windows').glob('*/sources.dpapi'))[0].read_bytes()
            self.uid=123
            for slot in (1,2):
                self.f=fixture(slot=slot);self.now[0]=self.f[3].timestamp()
                self.assertEqual(service.tick(max_calls=8)['retained_windows'],slot+1)
        self.assertEqual(json.loads((scope/'binding.json').read_text())['identity_state'],'REPORTED')
        self.assertEqual(len(list((scope/'bindings').glob('*.json'))),1)
        self.assertIn(old,[p.read_bytes() for p in (scope/'windows').glob('*/sources.dpapi')])

    def test_stop_between_gets_resumes_without_second_request_or_duplicate_source(self):
        stopped=[False]
        def get(*args,**kwargs):
            stopped[0]=True
            return self.get(*args,**kwargs)
        service=self.service()
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=get):
            self.assertEqual(service.tick(max_calls=8,should_stop=lambda:stopped[0])['calls_this_run'],1)
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service)
        self.assertEqual(len(self.calls),3)

    def test_local_activity_symbols_are_captured_without_expanding_account_scope(self):
        service=self.service()
        service.ledger_reader=lambda *a,**kw:{**self.ledger(*a,**kw),
            'positions':[{'symbol':'XRPUSDT'}], 'trades':[{'symbol':'ADAUSDT'}]}
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service)
            for _ in range(3):
                result=service.tick(max_calls=8)
                if result.get('retained_windows'):break
        queried={params['symbol'] for _,endpoint,params in self.calls if endpoint.endswith('/myTrades')}
        self.assertEqual(queried,{'BTCUSDT','XRPUSDT','ADAUSDT'})
        scope=service.directory/'SPOT_TESTNET'
        packet=_load_cipher(next((scope/'windows').glob('*/sources.dpapi')),cipher)
        self.assertEqual(packet['symbol_universe'],sorted(queried))
        self.assertEqual(packet['source_scope'],'BOUNDED_SYMBOLS')
        status=json.loads((scope/'status.json').read_text())
        self.assertFalse(status['source_reconciliation']['financial_window_complete'])
        self.assertTrue(next((scope/'windows').glob('*/reconciliation.dpapi')).exists())

    def test_full_history_page_is_partitioned_and_resume_retains_parent(self):
        service=self.service();parent=[]
        def get(scope,endpoint,params=None):
            if endpoint.endswith('/myTrades') and not parent:
                parent.append(dict(params));return [{'id':n} for n in range(1000)]
            return self.get(scope,endpoint,params)
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=get):
            self.baseline(service)
            self.assertEqual(service.tick(max_calls=8)['retained_windows'],0)
            # A fresh service resumes durable partition cursors, no parent GET retry.
            result=self.service().tick(max_calls=8)
        self.assertEqual(result['retained_windows'],1)
        queries=[params for _,endpoint,params in self.calls if endpoint.endswith('/myTrades')]
        self.assertEqual(len(queries),2)
        left,right=queries
        self.assertEqual(left['startTime'],parent[0]['startTime'])
        self.assertEqual(right['endTime'],parent[0]['endTime'])
        self.assertEqual(left['endTime']+1,right['startTime'])
        packet=_load_cipher(next((service.directory/'SPOT_TESTNET'/'windows').glob('*/sources.dpapi')),cipher)
        self.assertEqual(len(packet['history_partitions']),1)
        self.assertTrue(any(len(source.get('response',[]))==1000 for source in packet['sources']))

    def test_crash_after_durable_full_page_checkpoint_retains_its_split_plan(self):
        service=self.service();parent=[];crashed=[False]
        def get(scope,endpoint,params=None):
            if endpoint.endswith('/myTrades') and not parent:
                parent.append(dict(params));return [{'id':n} for n in range(1000)]
            return self.get(scope,endpoint,params)
        original_save=service._save
        def save(state):
            original_save(state)
            active=state['scopes'].get('SPOT_TESTNET',{}).get('active')
            if active and len(active['refs'])==4 and not crashed[0]:
                crashed[0]=True
                raise OSError('synthetic interruption after durable full-page checkpoint')
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=get):
            self.baseline(service);service._save=save
            service.tick(max_calls=8)
            pending=_load_cipher(service.directory/'controller.dpapi',cipher)['scopes']['SPOT_TESTNET']['active']
            self.assertTrue(crashed[0]);self.assertEqual(len(pending['refs']),4)
            self.assertEqual(len(pending['plan']),6)
            self.assertEqual(len(pending['history_partitions']),1)
            result=self.service().tick(max_calls=8)
        self.assertEqual(result['retained_windows'],1)
        children=[params for _,endpoint,params in self.calls if endpoint.endswith('/myTrades')]
        self.assertEqual(len(children),2)
        self.assertEqual(children[0]['startTime'],parent[0]['startTime'])
        self.assertEqual(children[0]['endTime']+1,children[1]['startTime'])
        self.assertEqual(children[1]['endTime'],parent[0]['endTime'])

    def test_retry_never_overwrites_a_changed_retained_window(self):
        def broken(packet):raise ValueError('SYNTHETIC_MATERIALIZER_FAILURE')
        service=self.service(materializer=broken)
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);service.tick(max_calls=8)
            source=next((service.directory/'SPOT_TESTNET'/'windows').glob('*/sources.dpapi'))
            packet=_load_cipher(source,cipher);packet['reason_codes'].append('SYNTHETIC_CHANGED_SOURCE')
            _save_cipher(source,packet,cipher);before=source.read_bytes()
            service.materializer=None
            result=service.tick(max_calls=8)
        self.assertIn('TESTNET_RETAINED_SOURCE_WINDOW_CHANGED',result['reason_codes'])
        self.assertEqual(source.read_bytes(),before)
        self.assertFalse((service.directory/'SPOT_TESTNET'/'financial-evidence.sqlite3').exists())

    def test_single_millisecond_full_page_stays_explicitly_unresolved(self):
        active={'plan':[]}
        raw={'endpoint':'/api/v3/myTrades','params':{'startTime':1,'endTime':1,'limit':1000,'symbol':'BTCUSDT'},
             'response':[{}]*1000}
        TestnetFinancialCaptureService._split_full_page(active,raw)
        self.assertEqual(active['plan'],[])
        self.assertEqual(active['history_partitions'][0]['gap'],'TESTNET_HISTORY_DENSE_OR_PARTITION_LIMIT')

    def test_cipher_or_fingerprint_mismatch_cannot_become_an_outcome(self):
        service=self.service(expected_fingerprints={'SPOT_TESTNET':{}})
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);result=service.tick(max_calls=8)
        self.assertIn('TESTNET_CURRENT_COHORT_FINGERPRINT_MISMATCH',result['reason_codes'])
        self.assertFalse((service.directory/'SPOT_TESTNET'/'financial-evidence.sqlite3').exists())

    def test_ledger_cut_failure_after_last_closing_get_resumes_same_window(self):
        calls=[0]
        def ledger(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:raise OSError('synthetic transient ledger read')
            return self.ledger(*args,**kwargs)
        service=self.service();service.ledger_reader=ledger
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service)
            self.assertEqual(service.tick(max_calls=8)['state'],'TESTNET_CAPTURE_BLOCKED')
            self.assertEqual(service.tick(max_calls=8)['retained_windows'],1)
        self.assertEqual(calls[0],3)

    def test_rate_limit_stops_capture_and_persists_global_backoff(self):
        service=self.service()
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=InventoryError('RATE_LIMITED')) as get:
            self.assertIn('RATE_LIMITED',service.tick(max_calls=8)['reason_codes'])
            self.assertEqual(service.tick(max_calls=8)['state'],'TESTNET_RATE_LIMITED')
        get.assert_called_once()

    def test_current_cohort_rotates_binding_without_overwriting_old_sources(self):
        service=self.service()
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service);service.tick(max_calls=8)
            first=list((service.directory/'SPOT_TESTNET'/'windows').glob('*/sources.dpapi'))[0].read_bytes()
            self.f=fixture(slot=1)
            self.f[0]['cohort_id']='a-new-synthetic-cohort'
            self.f[1]['cohort_digest']=register_forward_cohort(self.f[0]).digest
            self.now[0]=self.f[3].timestamp()
            self.assertEqual(service.tick(max_calls=8)['retained_windows'],2)
        scope=service.directory/'SPOT_TESTNET'
        self.assertEqual(len(list((scope/'bindings').glob('*.json'))),2)
        self.assertEqual(len(list((scope/'windows').glob('*/sources.dpapi'))),2)
        self.assertIn(first,[p.read_bytes() for p in (scope/'windows').glob('*/sources.dpapi')])

    def test_futures_identity_is_read_from_every_original_balance_cut(self):
        service=self.service()
        rows=lambda alias:{'endpoint':'/fapi/v3/balance','response':[{'accountAlias':alias,'asset':'USDT'}]}
        value=service._identity('FUTURES_DEMO',[rows('a'),rows('a')])
        self.assertIsInstance(value,str)
        with self.assertRaisesRegex(ValueError,'TESTNET_REPORTED_ACCOUNT_CHANGED'):
            service._identity('FUTURES_DEMO',[rows('a'),rows('b')])

    def test_original_reader_replays_chained_flags_and_ignores_cached_financial_bit(self):
        path=self.root/'operational-cohorts.sqlite3'
        store=OperationalCohortStore(path);store.initialize()
        at=self.f[3].timestamp()-3603
        reg=store.register('SPOT','SPOT_TESTNET',self.f[0]['fingerprints'],
            cadence_seconds=60,max_receipt_delay_seconds=30,now=at-61)
        cohort=register_forward_cohort(reg)
        start=cohort.starts_at.timestamp()
        evidence={key:key=='source_complete' for key in FLAGS}
        store.observe(reg,evidence,now=start)
        store.observe(reg,evidence,now=start+60)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('DROP TRIGGER receipts_no_update')
            db.execute('UPDATE receipts SET financial=1')
        observed=read_next_original(path,'SPOT_TESTNET',after=start,at=start+60)
        self.assertIsNotNone(observed)
        self.assertFalse(observed[1]['reconciled'])
        with closing(sqlite3.connect(path)) as db, db:
            payload=json.loads(db.execute('SELECT payload FROM receipts LIMIT 1').fetchone()[0])
            payload['reconciled']=True
            db.execute('UPDATE receipts SET payload=?',(json.dumps(payload),))
        with self.assertRaisesRegex(ValueError,'TESTNET_OPERATIONAL_RECEIPT_REPLAY_MISMATCH'):
            read_next_original(path,'SPOT_TESTNET',after=start,at=start+60)

    def test_current_reader_selects_newest_valid_receipt_while_legacy_order_is_preserved(self):
        path=self.root/'selection-cohorts.sqlite3'
        store=OperationalCohortStore(path);store.initialize()
        at=self.f[3].timestamp()-3603
        reg=store.register('SPOT','SPOT_TESTNET',self.f[0]['fingerprints'],
            cadence_seconds=60,max_receipt_delay_seconds=30,now=at-61)
        start=register_forward_cohort(reg).starts_at.timestamp()
        evidence={key:key=='source_complete' for key in FLAGS}
        for offset in (0,60,120,180):
            store.observe(reg,evidence,now=start+offset)
        oldest=read_next_original(path,'SPOT_TESTNET',after=start,at=start+180)
        newest=read_next_original(path,'SPOT_TESTNET',after=start,at=start+180,latest=True)
        current=read_current_original(path,'SPOT_TESTNET',after=start,at=start+180)
        self.assertEqual(oldest[1]['interval_start'],reg['starts_at'])
        self.assertEqual(newest[1]['interval_start'],iso(datetime.fromtimestamp(start+120,self.f[3].tzinfo)))
        self.assertEqual(current,newest)
        self.assertIsNone(read_current_original(path,'SPOT_TESTNET',after=start+180,at=start+180))
        self.assertFalse(newest[1]['reconciled'])
        with self.assertRaisesRegex(ValueError,'EXPLICIT_ORIGINAL_SELECTION_BOOLEAN_REQUIRED'):
            read_next_original(path,'SPOT_TESTNET',after=start,at=start+180,latest=1)

    def test_restart_keeps_in_flight_original_even_when_reader_now_has_newer_window(self):
        selected=[self.f];calls=[]
        def choose(path,scope,*,after,at):
            calls.append((after,at));return selected[0][0],selected[0][1]
        service=self.service();service.original_reader=choose
        first_original=deepcopy(self.f[1])
        with patch.object(TestnetReadOnlyTransport,'get',side_effect=self.get):
            self.baseline(service)
            service.tick(max_calls=1)
            pending=_load_cipher(service.directory/'controller.dpapi',cipher)['scopes']['SPOT_TESTNET']['active']
            self.assertEqual(len(pending['refs']),1)
            selected[0]=fixture(slot=1)
            resumed=self.service();resumed.original_reader=choose
            self.assertEqual(resumed.tick(max_calls=8)['retained_windows'],1)
        self.assertEqual(len(calls),1)
        scope=service.directory/'SPOT_TESTNET'
        retained=_load_cipher(next((scope/'windows').glob('*/sources.dpapi')),cipher)
        self.assertEqual(retained['original'],first_original)
        self.assertEqual(retained['selection_scope'],'INJECTED_OPERATIONAL_WINDOW')
        self.assertIn('BOUNDED_CAPTURE_DOES_NOT_BACKFILL_EVERY_OPERATIONAL_RECEIPT',retained['reason_codes'])
        status=json.loads((scope/'status.json').read_text())
        self.assertEqual(status['selection_scope'],retained['selection_scope'])
        self.assertFalse(status['financial_window_complete'])
