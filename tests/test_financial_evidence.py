"""Synthetic retained financial windows; no providers, keys or operating DBs."""
from copy import deepcopy
from contextlib import closing
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.financial_evidence import (AUTHORITY, FLAGS, FinancialEvidenceStore,
    build_financial_receipt, canonical, digest, evaluate_financial_coverage, seal_cut)
from trader.migration_evidence import FINGERPRINT_KEYS, register_forward_cohort


START = datetime(2026, 10, 23, tzinfo=UTC)


def iso(at):
    return at.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def ref(text):
    return hashlib.sha256(text.encode()).hexdigest()


ACCOUNT = ref('synthetic-account')
POSITION = ref('synthetic-position')


def registration(engine='SPOT'):
    return {'schema':1,'cohort_id':'synthetic-'+engine.lower(),'engine':engine,
        'environment':'SPOT_TESTNET' if engine == 'SPOT' else 'FUTURES_DEMO',
        'registered_at':iso(START-timedelta(minutes=1)),'starts_at':iso(START),
        'cadence_seconds':3600,'max_receipt_delay_seconds':60,
        'fingerprints':{key:ref(key) for key in FINGERPRINT_KEYS}}


def fixture(slot=0, engine='SPOT', held=False):
    reg = registration(engine); start=START+timedelta(hours=slot); end=start+timedelta(hours=1)
    original={'receipt_id':'receipt-'+str(slot),'cohort_digest':register_forward_cohort(reg).digest,
        'environment':reg['environment'],'fingerprints':reg['fingerprints'],
        'interval_start':iso(start),'interval_end':iso(end),'available_at':iso(end),
        'decided_at':iso(end),'received_at':iso(end+timedelta(seconds=1)),
        'evidence_kind':'OBSERVED_FORWARD','evidence_digest':ref('capture-'+str(slot)),
        **{key:key == 'source_complete' for key in FLAGS}}
    positions=[{'ref':POSITION,'symbol':'BTCUSDT','direction':'LONG','quantity_units':10}] if held else []
    cut={'account_ref':ACCOUNT,'environment':reg['environment'],'currency':'USDT',
        'balance_start_units':100000,'balance_end_units':100000,
        'opening_positions':deepcopy(positions),'positions':positions,'fills':[], 'settlements':[],
        'coverage':{'start':iso(start),'end':iso(end),'received_at':iso(end+timedelta(seconds=2)),
            'scope':'ALL_ACCOUNT','position_count':len(positions),'fill_count':0,'settlement_count':0,
            'fills_exhausted':True,'settlements_exhausted':True,'unknown_orders':0,'unrecognized_positions':0}}
    exposures=[{'position_ref':POSITION,'symbol':'BTCUSDT','direction':'LONG',
        'start':iso(start),'end':iso(end),'quantity_units':10}] if held else []
    protections=[{'position_ref':POSITION,'start':iso(start),'end':iso(end),'quantity_units':10,
        'order_ref':ref('native-stop'),'confirmed_at':iso(start-timedelta(seconds=1)),
        'received_at':iso(end+timedelta(seconds=2)),'status':'ARMED','kind':'STOP_LOSS'}] if held else []
    bundle={'schema':1,'account_ref':ACCOUNT,'environment':reg['environment'],'currency':'USDT',
        'unit_scale':6,'window_start':iso(start),'window_end':iso(end),
        'ledger':seal_cut(cut),'exchange':seal_cut(deepcopy(cut)),
        'exposures':exposures,'protections':protections,'protection_coverage':{
            'start':iso(start),'end':iso(end),'received_at':iso(end+timedelta(seconds=2)),
            'complete':True,'source_digest':'0'*64}}
    reseal(bundle)
    return reg, original, bundle, end+timedelta(seconds=3)


def reseal(bundle):
    for name in ('ledger','exchange'):
        cut=bundle[name]
        cut['coverage'].update(position_count=len(cut['positions']),fill_count=len(cut['fills']),
                               settlement_count=len(cut['settlements']))
        bundle[name]=seal_cut(cut)
    p=bundle['protection_coverage']
    p['source_digest']=digest({'start':p['start'],'end':p['end'],
                              'exposures':bundle['exposures'],'protections':bundle['protections']})


def evaluate(f, **changes):
    reg, original, bundle, now=f
    return build_financial_receipt(reg,original,bundle,now=iso(changes.get('now',now)))


def fill(at, *, effect='OPEN', quantity=1000, quote=3000, fee_asset='USDT', fee=3, fee_quote=3, sequence=1):
    return {'ref':ref('fill-'+str(sequence)),'position_ref':POSITION,'symbol':'BTCUSDT',
        'direction':'LONG','effect':effect,'at':iso(at),'sequence':sequence,
        'quantity_units':quantity,'quote_units':quote,'fee_asset':fee_asset,
        'fee_units':fee,'fee_quote_units':fee_quote}


def coverage(reg, originals, records, now, **changes):
    args={'now':iso(now),'expected_cohort_digest':register_forward_cohort(reg).digest,
          'expected_account_ref':ACCOUNT,'expected_unit_scale':6,**changes}
    return evaluate_financial_coverage(reg,originals,records,**args)


class FinancialWindowTests(unittest.TestCase):
    def test_spot_cannot_claim_short_in_opening_or_closing_inventory(self):
        for engine in ('SPOT','FUTURES'):
            f=fixture(engine=engine,held=True)
            for cut in (f[2]['ledger'],f[2]['exchange']):
                for row in cut['opening_positions']+cut['positions']:row['direction']='SHORT'
            f[2]['exposures'][0]['direction']='SHORT';reseal(f[2])
            result=evaluate(f)
            self.assertEqual(result['financial_window_complete'],engine=='FUTURES')
            if engine=='SPOT':
                self.assertEqual(result['state'],'UNKNOWN')
                self.assertFalse(any(result[k] for k in FLAGS))

    def test_empty_account_requires_proven_full_window_not_just_equal_balances(self):
        f=fixture();before=deepcopy(f);result=evaluate(f)
        self.assertEqual(result['state'],'RECONCILED_WINDOW')
        self.assertTrue(all(result[k] for k in FLAGS))
        self.assertFalse(result['usable_at_original_decision'])
        self.assertEqual(before,f)
        for key in AUTHORITY:self.assertIs(result[key],False)
        for field,value in (('scope','BOUNDED_SYMBOLS'),('fills_exhausted',False),
                            ('settlements_exhausted',False),('unknown_orders',1)):
            f=fixture();f[2]['exchange']['coverage'][field]=value;reseal(f[2])
            result=evaluate(f)
            self.assertFalse(result['financial_window_complete'])
            self.assertFalse(result['source_complete'])

    def test_native_stop_history_must_cover_every_held_quantity(self):
        f=fixture(held=True);self.assertTrue(evaluate(f)['protections_complete'])
        f[2]['protections'][0]['start']=iso(START+timedelta(seconds=1));reseal(f[2])
        self.assertFalse(evaluate(f)['protections_complete'])
        # Hiding the first second in an exposure declaration cannot hide a gap.
        f[2]['exposures'][0]['start']=iso(START+timedelta(seconds=1));reseal(f[2])
        self.assertFalse(evaluate(f)['protections_complete'])
        for field,value in (('quantity_units',9),('kind','TAKE_PROFIT')):
            f=fixture(held=True);f[2]['protections'][0][field]=value;reseal(f[2])
            self.assertFalse(evaluate(f)['protections_complete'])

    def test_current_armed_snapshot_cannot_claim_unretained_protection_history(self):
        f=fixture(held=True);f[2]['protection_coverage']['complete']=False
        self.assertFalse(evaluate(f)['protections_complete'])
        f=fixture(held=True)
        missing={**f[2]['protections'][0],'status':'MISSING','order_ref':None,'confirmed_at':None}
        f[2]['protections'].append(missing);reseal(f[2])
        self.assertFalse(evaluate(f)['protections_complete'])

    def test_base_asset_commission_uses_exact_ratio_and_conservative_roundup(self):
        f=fixture(held=True);b=f[2];row=fill(START,fee_asset='BTC',fee=1,fee_quote=3)
        for cut in (b['ledger'],b['exchange']):
            cut['opening_positions']=[];cut['positions'][0]['quantity_units']=999
            cut['fills']=[deepcopy(row)];cut['balance_end_units']=97000
        b['exposures'][0]['quantity_units']=999;b['protections'][0]['quantity_units']=999;reseal(b)
        self.assertTrue(evaluate(f)['financial_window_complete'])
        for cut in (b['ledger'],b['exchange']):cut['fills'][0]['fee_quote_units']=2
        reseal(b);self.assertFalse(evaluate(f)['costs_complete'])

    def test_foreign_commission_asset_and_missing_commission_are_unknown_not_zero(self):
        for fee_asset in ('BNB',None):
            f=fixture(held=True);b=f[2];row=fill(START,fee_asset=fee_asset,fee_quote=None)
            for cut in (b['ledger'],b['exchange']):
                cut['opening_positions']=[];cut['positions'][0]['quantity_units']=1000
                cut['fills']=[deepcopy(row)];cut['balance_end_units']=97000
            b['exposures'][0]['quantity_units']=1000;b['protections'][0]['quantity_units']=1000;reseal(b)
            self.assertFalse(evaluate(f)['costs_complete'])

    def test_futures_notional_is_not_wallet_cash_and_funding_is_included(self):
        f=fixture(engine='FUTURES',held=True);b=f[2];row=fill(START,quote=50000,fee=25,fee_quote=25)
        income=[{'ref':ref('fee'),'kind':'COMMISSION','asset':'USDT','amount_units':-25,'at':iso(START)},
                {'ref':ref('funding'),'kind':'FUNDING_FEE','asset':'USDT','amount_units':7,'at':iso(START+timedelta(minutes=30))}]
        for cut in (b['ledger'],b['exchange']):
            cut['opening_positions']=[];cut['positions'][0]['quantity_units']=1000
            cut['fills']=[deepcopy(row)];cut['settlements']=deepcopy(income);cut['balance_end_units']=99982
        b['exposures'][0]['quantity_units']=1000;b['protections'][0]['quantity_units']=1000;reseal(b)
        self.assertTrue(evaluate(f)['financial_window_complete'])
        b['ledger']['settlements'].pop();reseal(b)
        result=evaluate(f);self.assertFalse(result['reconciled']);self.assertFalse(result['costs_complete'])

    def test_partial_closes_reconstruct_each_exposure_segment(self):
        f=fixture(held=True);b=f[2];end1=START+timedelta(minutes=10);end2=START+timedelta(minutes=20)
        fills=[fill(end1,effect='REDUCE',quantity=6,quote=6000,fee=1,fee_quote=1),
               fill(end2,effect='CLOSE',quantity=4,quote=4000,fee=1,fee_quote=1,sequence=2)]
        for cut in (b['ledger'],b['exchange']):
            cut['positions']=[];cut['fills']=deepcopy(fills);cut['balance_end_units']=109998
        b['exposures']=[{**b['exposures'][0],'end':iso(end1)},
            {**b['exposures'][0],'start':iso(end1),'end':iso(end2),'quantity_units':4}]
        b['protections'][0]['end']=iso(end2);reseal(b)
        self.assertTrue(evaluate(f)['financial_window_complete'])
        b['exposures'][1]['quantity_units']=3;reseal(b)
        self.assertFalse(evaluate(f)['protections_complete'])

    def test_duplicate_fills_and_unknown_settlement_cannot_double_count(self):
        f=fixture();row={'ref':ref('transfer'),'kind':'TRANSFER_IN','asset':'USDT','amount_units':1,'at':iso(START)}
        for cut in (f[2]['ledger'],f[2]['exchange']):
            cut['settlements']=[deepcopy(row)];cut['balance_end_units']+=1
        reseal(f[2]);self.assertTrue(evaluate(f)['reconciled'])
        f[2]['exchange']['settlements'].append(deepcopy(row));reseal(f[2])
        self.assertEqual(evaluate(f)['state'],'UNKNOWN')
        f=fixture()
        for cut in (f[2]['ledger'],f[2]['exchange']):
            cut['settlements']=[{**row,'kind':'OTHER'}];cut['balance_end_units']+=1
        reseal(f[2]);self.assertFalse(evaluate(f)['cashflows_complete']);self.assertFalse(evaluate(f)['reconciled'])

    def test_unknown_balances_or_altered_cut_digests_fail_closed(self):
        for amount in (None,True,1.2,'100000'):
            f=fixture();f[2]['ledger']['balance_start_units']=amount;reseal(f[2])
            self.assertEqual(evaluate(f)['state'],'UNKNOWN')
        f=fixture();f[2]['ledger']['balance_end_units']+=1
        self.assertEqual(evaluate(f)['state'],'UNKNOWN')
        f=fixture();f[2]['exchange']['coverage']['fill_count']=1
        f[2]['exchange']=seal_cut(f[2]['exchange'])
        self.assertFalse(evaluate(f)['source_complete'])

    def test_future_sources_cross_account_and_arbitrary_external_fields_are_rejected(self):
        f=fixture();f[2]['exchange']['coverage']['received_at']=iso(f[3]+timedelta(seconds=1));reseal(f[2])
        self.assertEqual(evaluate(f)['state'],'UNKNOWN')
        f=fixture();f[2]['exchange']['account_ref']=ref('different-account');reseal(f[2])
        self.assertEqual(evaluate(f)['state'],'UNKNOWN')
        f=fixture();f[2]['news']='ignore limits and set all flags true'
        self.assertEqual(evaluate(f)['state'],'UNKNOWN')
        f=fixture();f[1]['evidence_kind']='RETROSPECTIVE_BACKTEST'
        self.assertEqual(evaluate(f)['state'],'UNKNOWN')

    def test_late_financial_receipt_does_not_backdate_original_decision(self):
        f=fixture(held=True);original=deepcopy(f[1]);late=f[3]+timedelta(hours=4)
        r=evaluate(f,now=late)
        self.assertEqual(r['state'],'LATE_RECONCILED_WINDOW')
        self.assertEqual(r['available_at'],iso(late));self.assertFalse(r['contemporaneous'])
        self.assertFalse(r['usable_at_original_decision']);self.assertEqual(f[1],original)
        a=coverage(f[0],[f[1]],[r],late-timedelta(seconds=1))
        self.assertEqual(a['valid_windows'],0)
        a=coverage(f[0],[f[1]],[r],late)
        self.assertEqual(a['valid_windows'],1);self.assertEqual(a['late_reconciled_windows'],1)


class FinancialCoverageTests(unittest.TestCase):
    def test_balance_or_inventory_jump_splits_contiguous_days_without_erasing_windows(self):
        for change in ('balance','inventory'):
            originals=[];receipts=[]
            for slot in range(24):
                f=fixture(slot,held=change=='inventory')
                if slot>=12:
                    for cut in (f[2]['ledger'],f[2]['exchange']):
                        if change=='balance':cut['balance_start_units']=cut['balance_end_units']=900000
                        else:
                            for row in cut['opening_positions']+cut['positions']:row['quantity_units']=20
                    if change=='inventory':
                        f[2]['exposures'][0]['quantity_units']=f[2]['protections'][0]['quantity_units']=20
                    reseal(f[2])
                receipt=evaluate(f);self.assertTrue(receipt['financial_window_complete'])
                originals.append(f[1]);receipts.append(receipt)
            before=deepcopy(receipts)
            result=coverage(registration(),originals,receipts,START+timedelta(hours=25))
            self.assertEqual(result['valid_windows'],24);self.assertEqual(result['covered_seconds'],86400)
            self.assertEqual(result['qualified_days'],0);self.assertEqual(result['continuous_qualified_days'],0)
            self.assertIn('FINANCIAL_BOUNDARY_CONTINUITY_UNPROVEN',result['reason_codes'])
            self.assertEqual(receipts,before)

    def test_cashflow_at_boundary_belongs_to_following_window_and_preserves_continuity(self):
        originals=[];receipts=[]
        for slot in range(24):
            f=fixture(slot)
            for cut in (f[2]['ledger'],f[2]['exchange']):
                if slot>12:cut['balance_start_units']=900000
                if slot>=12:cut['balance_end_units']=900000
                if slot==12:
                    cut['settlements']=[{'ref':ref('boundary-deposit'),'kind':'DEPOSIT','asset':'USDT',
                        'amount_units':800000,'at':iso(START+timedelta(hours=12))}]
            reseal(f[2]);receipt=evaluate(f)
            self.assertTrue(receipt['financial_window_complete']);self.assertFalse(receipt['usable_at_original_decision'])
            originals.append(f[1]);receipts.append(receipt)
        self.assertEqual(receipts[11]['closing_state_digest'],receipts[12]['opening_state_digest'])
        self.assertEqual(receipts[12]['closing_state_digest'],receipts[13]['opening_state_digest'])
        complete=coverage(registration(),originals,receipts,START+timedelta(hours=25))
        self.assertEqual(complete['continuous_qualified_days'],1)
        self.assertNotIn('FINANCIAL_BOUNDARY_CONTINUITY_UNPROVEN',complete['reason_codes'])
        earlier=coverage(registration(),originals,receipts,START+timedelta(hours=12))
        self.assertEqual(earlier['valid_windows'],11)
        # Moving that deposit into the preceding half-open window is invalid.
        prior=fixture(11)
        for cut in (prior[2]['ledger'],prior[2]['exchange']):
            cut['balance_end_units']=900000
            cut['settlements']=[{'ref':ref('boundary-deposit'),'kind':'DEPOSIT','asset':'USDT',
                'amount_units':800000,'at':iso(START+timedelta(hours=12))}]
        reseal(prior[2]);self.assertFalse(evaluate(prior)['financial_window_complete'])

    def test_full_day_can_be_qualified_today_without_changing_past_information(self):
        originals=[];receipts=[]
        for slot in range(24):
            f=fixture(slot);originals.append(f[1]);receipts.append(evaluate(f,now=f[3]+timedelta(hours=2)))
        result=coverage(registration(),originals,receipts,START+timedelta(hours=27))
        self.assertEqual(result['qualified_days'],1);self.assertEqual(result['late_reconciled_windows'],24)
        self.assertEqual(result['continuous_qualified_days'],1)
        self.assertTrue(all(result[k] is False for k in AUTHORITY))
        prior=coverage(registration(),originals,receipts,START+timedelta(hours=24))
        self.assertEqual(prior['qualified_days'],0)

    def test_disconnected_partial_days_do_not_add_into_a_qualified_day(self):
        originals=[];receipts=[]
        for slot in list(range(12))+list(range(24,36)):
            f=fixture(slot);originals.append(f[1]);receipts.append(evaluate(f))
        r=coverage(registration(),originals,receipts,START+timedelta(hours=37))
        self.assertEqual(r['valid_windows'],24);self.assertEqual(r['qualified_days'],0)

    def test_wrong_account_scale_anchor_and_conflicting_revisions_do_not_qualify(self):
        f=fixture();r=evaluate(f)
        for kwargs in ({'expected_account_ref':ref('wrong')},{'expected_unit_scale':3},
                       {'expected_cohort_digest':'0'*64}):
            self.assertEqual(coverage(f[0],[f[1]],[r],f[3],**kwargs)['valid_windows'],0)
        revised=deepcopy(r);revised['outcome_digest']=ref('conflicting-revision')
        result=coverage(f[0],[f[1]],[r,revised],f[3])
        self.assertEqual(result['valid_windows'],0);self.assertEqual(result['conflicting_windows'],1)

    def test_equivalent_financial_outcomes_with_later_receipts_are_not_conflicts(self):
        f=fixture();r=evaluate(f);later=deepcopy(f)
        for c in ('ledger','exchange'):
            later[2][c]['coverage']['received_at']=iso(later[3]+timedelta(minutes=5))
        later[2]['protection_coverage']['received_at']=iso(later[3]+timedelta(minutes=5));reseal(later[2])
        second=evaluate(later,now=later[3]+timedelta(minutes=6))
        self.assertNotEqual(r['bundle_digest'],second['bundle_digest'])
        self.assertEqual(r['outcome_digest'],second['outcome_digest'])
        result=coverage(f[0],[f[1]],[second,r],later[3]+timedelta(minutes=7))
        self.assertEqual(result['valid_windows'],1);self.assertEqual(result['conflicting_windows'],0)
        self.assertEqual(result['late_reconciled_windows'],0)


class FinancialJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'financial.sqlite3';self.store=FinancialEvidenceStore(self.path)
        self.store.initialize()

    def test_durable_restart_idempotence_and_asof_reads(self):
        f=fixture();a=self.store.record(*f[:3],now=iso(f[3]));anchor=a['hash']
        restored=FinancialEvidenceStore(self.path)
        b=restored.record(*f[:3],now=iso(f[3]+timedelta(minutes=5)))
        self.assertTrue(b['duplicate']);self.assertEqual(a['hash'],b['hash'])
        self.assertEqual(a['receipt']['available_at'],b['receipt']['available_at'])
        self.assertEqual(restored.verify_chain(expected_anchor=anchor)['records'],1)
        self.assertEqual(restored.receipts(cohort_digest=register_forward_cohort(f[0]).digest,
            now=iso(f[3]-timedelta(seconds=1))),[])
        self.assertEqual(len(restored.receipts(cohort_digest=register_forward_cohort(f[0]).digest,now=iso(f[3]))),1)

    def test_coverage_rebuilds_packets_and_requires_latest_retained_anchor(self):
        f=fixture();saved=self.store.record(*f[:3],now=iso(f[3]))
        kwargs={'now':iso(f[3]),'expected_cohort_digest':register_forward_cohort(f[0]).digest,
                'expected_account_ref':ACCOUNT,'expected_unit_scale':6,'expected_anchor':saved['hash']}
        result=self.store.coverage(f[0],[f[1]],**kwargs)
        self.assertTrue(result['journal_verified']);self.assertEqual(result['valid_windows'],1)
        self.assertEqual(self.store.coverage(f[0],[f[1]],**{**kwargs,'expected_anchor':'a'*64})['valid_windows'],0)
        nxt=fixture(1);second=self.store.record(*nxt[:3],now=iso(nxt[3]))
        result=self.store.coverage(f[0],[f[1],nxt[1]],**{**kwargs,'now':iso(nxt[3])})
        self.assertFalse(result['journal_verified']);self.assertEqual(result['valid_windows'],0)
        kwargs.update(now=iso(nxt[3]),expected_anchor=second['hash'])
        self.assertEqual(self.store.coverage(f[0],[f[1],nxt[1]],**kwargs)['valid_windows'],2)

    def test_hash_consistent_fabricated_flags_do_not_replace_packet_validation(self):
        f=fixture();f[2]['exchange']['coverage']['fills_exhausted']=False;reseal(f[2])
        saved=self.store.record(*f[:3],now=iso(f[3]));receipt=saved['receipt']
        receipt.update({k:True for k in FLAGS});receipt['financial_window_complete']=True
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER financial_no_update')
            row=db.execute('SELECT id,bundle,previous FROM financial_receipts').fetchone()
            forged=digest({'id':row[0],'receipt':receipt,'bundle':json.loads(row[1]),'previous':row[2]})
            db.execute('UPDATE financial_receipts SET receipt=?,hash=?',(canonical(receipt),forged))
        self.assertEqual(self.store.verify_chain(expected_anchor=forged)['state'],'VALID_LOCAL_CHAIN')
        result=self.store.coverage(f[0],[f[1]],now=iso(f[3]),expected_cohort_digest=register_forward_cohort(f[0]).digest,
            expected_account_ref=ACCOUNT,expected_unit_scale=6,expected_anchor=forged)
        self.assertFalse(result['journal_verified']);self.assertEqual(result['valid_windows'],0)

    def test_immutable_records_retention_and_clock_regression(self):
        f=fixture();self.store.record(*f[:3],now=iso(f[3]))
        with closing(sqlite3.connect(self.path)) as db, db:
            for sql in ('UPDATE financial_receipts SET at=at','DELETE FROM financial_receipts'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
        capped=FinancialEvidenceStore(self.path,max_records=1);next_window=fixture(1)
        with self.assertRaises(ValueError):capped.record(*next_window[:3],now=iso(next_window[3]))
        modified=fixture();modified[2]['ledger']['balance_end_units']+=1;reseal(modified[2])
        with self.assertRaises(ValueError):self.store.record(*modified[:3],now=iso(f[3]-timedelta(seconds=1)))

    def test_missing_read_does_not_create_and_tamper_breaks_retained_chain(self):
        missing=FinancialEvidenceStore(self.path.parent/'missing.sqlite3')
        self.assertEqual(missing.receipts(cohort_digest='a'*64,now=iso(START)),[])
        self.assertFalse(missing.path.exists())
        f=fixture();saved=self.store.record(*f[:3],now=iso(f[3]))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TRIGGER financial_no_update')
            db.execute("UPDATE financial_receipts SET bundle='{}'")
        self.assertEqual(self.store.verify_chain(expected_anchor=saved['hash'])['state'],'INVALID')

    def test_process_crash_after_insert_leaves_no_partial_receipt_or_chain(self):
        f=fixture();packet=self.path.parent/'packet.json'
        packet.write_text(json.dumps([f[0],f[1],f[2],iso(f[3])]))
        script='''import json,os,sys
sys.path.insert(0,sys.argv[1])
from trader.financial_evidence import FinancialEvidenceStore
class Proxy:
 def __init__(self,c):self.c=c
 def __enter__(self):self.c.__enter__();return self
 def __exit__(self,*a):return self.c.__exit__(*a)
 def close(self):self.c.close()
 def execute(self,sql,*a):
  result=self.c.execute(sql,*a)
  if sql.startswith('INSERT INTO financial_receipts('):os._exit(7)
  return result
class Crash(FinancialEvidenceStore):
 def _connect(self,readonly=False):return Proxy(super()._connect(readonly))
r,o,b,n=json.load(open(sys.argv[3]))
Crash(sys.argv[2]).record(r,o,b,now=n)
'''
        process=subprocess.run([sys.executable,'-I','-B','-c',script,str(Path(__file__).resolve().parents[1]),str(self.path),str(packet)],
            capture_output=True,timeout=15)
        self.assertEqual(process.returncode,7,process.stderr.decode(errors='replace'))
        self.assertEqual(self.store.verify_chain()['records'],0)
        self.assertFalse(self.store.record(*f[:3],now=iso(f[3]))['duplicate'])


class FinancialDirectStoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.path=self.folder/'financial.sqlite3'

    def foreign(self):
        path=self.folder/'operating.sqlite3'
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('CREATE TABLE operating_ledger(balance INTEGER)')
            db.execute('INSERT INTO operating_ledger VALUES(12345)')
        return path

    def test_direct_foreign_ledger_rejects_initialize_and_record_without_byte_changes(self):
        foreign=self.foreign();before=foreign.read_bytes();store=FinancialEvidenceStore(foreign)
        f=fixture()
        for call in (store.initialize,lambda:store.record(*f[:3],now=iso(f[3]))):
            with self.assertRaises(ValueError):call()
            self.assertEqual(foreign.read_bytes(),before)
        self.assertFalse(Path(str(foreign)+'-journal').exists())

    def test_record_missing_path_never_implicitly_creates_and_existing_empty_is_not_new(self):
        store=FinancialEvidenceStore(self.path);f=fixture()
        with self.assertRaises(ValueError):store.record(*f[:3],now=iso(f[3]))
        self.assertFalse(self.path.exists())
        self.path.touch()
        with self.assertRaises(ValueError):store.initialize()
        self.assertEqual(self.path.read_bytes(),b'')

    def test_hardlinked_journal_is_rejected_by_direct_api(self):
        store=FinancialEvidenceStore(self.path);store.initialize()
        alias=self.folder/'alias.sqlite3';os.link(self.path,alias);before=alias.read_bytes();f=fixture()
        with self.assertRaises(ValueError):store.record(*f[:3],now=iso(f[3]))
        with self.assertRaises(ValueError):store.initialize()
        self.assertEqual(alias.read_bytes(),before)

    def test_substitution_before_sqlite_open_never_mutates_foreign_schema(self):
        store=FinancialEvidenceStore(self.path);store.initialize()
        foreign=self.foreign();before=foreign.read_bytes();connect=sqlite3.connect;injected=[]
        def substitute(*args,**kwargs):
            if not injected:
                injected.append(True)
                # Same-inode content substitution also defeats inode-only guards.
                self.path.write_bytes(before)
            return connect(*args,**kwargs)
        f=fixture()
        with patch('trader.financial_evidence.sqlite3.connect',side_effect=substitute):
            with self.assertRaises(ValueError):store.record(*f[:3],now=iso(f[3]))
        self.assertEqual(foreign.read_bytes(),before);self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(Path(str(self.path)+'-journal').exists())

    def test_initialize_substitution_is_not_a_grant_to_initialize_foreign_file(self):
        foreign=self.foreign();before=foreign.read_bytes();connect=sqlite3.connect;injected=[]
        def substitute(*args,**kwargs):
            if not injected:
                injected.append(True);self.path.write_bytes(before)
            return connect(*args,**kwargs)
        with patch('trader.financial_evidence.sqlite3.connect',side_effect=substitute):
            with self.assertRaises(ValueError):FinancialEvidenceStore(self.path).initialize()
        self.assertEqual(foreign.read_bytes(),before);self.assertEqual(self.path.read_bytes(),before)


if __name__ == '__main__':unittest.main()
