"""Real native algorithms -> constrained AI -> retained central fake workflow.

All credentials, approval, prices and balances are synthetic. Socket connections
are prohibited. No operating engine is constructed and no real API is called.
"""
from contextlib import closing
from dataclasses import asdict, replace
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from trader.ai_advisor import AIAdvisor
from trader.central_admission import CentralAdmission, PositionFact, Scope
from trader.config import AISettings, FuturesTestnetSettings, RiskSettings, StrategySettings
from trader.domain import AIReview
from trader.futures_strategy import evaluate_futures_signal
from trader.live_execution_runtime import LiveExecutionCoordinator
from trader.live_proposal_source import (LiveProposalSourceJournal, LivePublicCandleReader,
    NativeEntryBudget, NativeLiveProposalSource, NativeVenueSnapshot, PublicCandleCut)
from trader.live_strategy_adapter import LiveStrategyPlanStore, VenueExecutionEvidence, prepare_strategy_entry
from trader.live_transport import LiveError, LiveOrderTransport, LiveSubmissionJournal
from trader.strategy import SwingStrategy
from tests.test_central_admission import Clock, NOW, U, facts, policy
from tests.test_live_execution_runtime import FakeSpotVenue, FakeVenue, SyntheticOwner
from tests.test_live_preproduction import pair


def raw_rows(*,at=NOW,direction='UP',count=160):
    end=int(at//3600)*3600_000;start=end-count*3600_000
    prices=([60+i*.2+(8.2 if i==159 else 0) for i in range(count)] if direction=='UP' else
            [200-i*.6-(4.6 if i==159 else 0) for i in range(count)] if direction=='DOWN' else [100.0]*count)
    return tuple((start+i*3600_000,format(Decimal(str(price)),'f'),format(Decimal(str(price))+Decimal('.5'),'f'),
                  format(Decimal(str(price))-Decimal('.5'),'f'),format(Decimal(str(price)),'f'),'120' if i==count-1 else '100',
                  start+(i+1)*3600_000-1,'10000',10,'50','5000','0') for i,price in enumerate(prices))


def candle_cut(environment='FUTURES_LIVE',*,at=NOW,direction='UP',symbol='BTCUSDT'):
    host,path=('https://api.binance.com','/api/v3/klines') if environment=='SPOT_LIVE' else ('https://fapi.binance.com','/fapi/v1/klines')
    return PublicCandleCut(environment,host,path,symbol,'1h',at-1,at,at,raw_rows(at=at,direction=direction))


class PublicResponse:
    def __init__(self,payload,url,*,status=200):self.raw=json.dumps(payload).encode();self.url=url;self.status=status
    def geturl(self):return self.url
    def read(self,size):return self.raw[:size]
    def __enter__(self):return self
    def __exit__(self,*args):return False


class FakePublicVenue:
    def __init__(self,rows,*,at=NOW):self.rows=rows;self.at=at;self.requests=[];self.redirect=False;self.oversized=False
    def open(self,request,timeout):
        self.requests.append(request)
        payload={'serverTime':int(self.at*1000)} if request.full_url.split('?')[0].endswith('/time') else self.rows
        response=PublicResponse(payload,request.full_url if not self.redirect else 'https://other.invalid/capture')
        if self.oversized:response.raw=b'x'*524289
        return response


class NativeSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.clock=Clock();self.policy=policy();self.scope=Scope('SYNTHETIC_NATIVE_ACCOUNT','FUTURES_LIVE','USDT')
        self.strategy=StrategySettings(70,20,50,14,14,20,20)
        self.risk=RiskSettings(10,.9,.9,.03,.1,.2,2,.01,2,1.5,3)
        self.futures=FuturesTestnetSettings(False,self.root/'UNUSED.sqlite3',1,2,'ISOLATED','ONE_WAY',1,
            False,'1h',('BTCUSDT',),10,1,100,70,2,.01,2,self.root/'UNUSED.kill')
        self.ai=AIAdvisor.__new__(AIAdvisor)
        self.ai.settings=AISettings(True,'SYNTHETIC_MODEL',2,.5,True,10,max_reviews_per_day=4)
        self.ai.api_key='SYNTHETIC_NOT_A_CREDENTIAL'
        self.review=patch.object(self.ai,'review',return_value=AIReview('ALLOW',.9,1,'synthetic native review')).start()
        self.review_futures=patch.object(self.ai,'review_futures',return_value=AIReview('ALLOW',.9,1,'synthetic native review')).start()
        self.addCleanup(patch.stopall)
        self.socket=patch('socket.socket.connect',side_effect=AssertionError('No actual network permitted'))
        self.socket.start();self.addCleanup(self.socket.stop)
        self.journal=LiveProposalSourceJournal(self.root/'live-proposal-source-synthetic.sqlite3');self.journal.initialize()
        self.budget=NativeEntryBudget(200*U,100*U,20*U,1000,'CRYPTO_FACTOR','NATIVE_RULES_V1',100,1)
        self.source=self.make_source()

    def make_source(self,**changes):
        params=dict(strategy_settings=self.strategy,risk_settings=self.risk,futures_settings=self.futures,
            advisor=self.ai,journal=self.journal,maximum_reviews_per_day=4,decision_ttl_ms=20000,clock=self.clock)
        return NativeLiveProposalSource(**(params|changes))

    def venue(self,scope=None,*,at=NOW,symbol='BTCUSDT',reference='100'):
        scope=scope or self.scope
        return NativeVenueSnapshot(symbol,VenueExecutionEvidence(scope,'b'*64,at,at,reference,
            '0.001','0.001','100','0.01',5*U,None,10,10,5,1000*U,1000,True,True,True,True))

    def inputs(self,*,environment='FUTURES_LIVE',at=NOW,direction='UP'):
        scope=Scope('SYNTHETIC_NATIVE_ACCOUNT',environment,'USDT');cut=candle_cut(environment,at=at,direction=direction)
        return cut,dict(btc_cut=cut if environment=='SPOT_LIVE' else None,scope=scope,
                        facts=facts(scope,at=at),venue=self.venue(scope,at=at),policy=self.policy,budget=self.budget)

    def produce(self,**changes):
        cut,kw=self.inputs(**changes);return self.source.produce(cut,**kw)

    def coordinator(self,bundle):
        owner=SyntheticOwner()
        admission=CentralAdmission(self.root/'central-admission-native-source.sqlite3',scope=bundle.proposal.scope,
            policy=self.policy,clock=self.clock,capability_verifier=owner.verifier);admission.initialize()
        transport=LiveOrderTransport({bundle.proposal.scope.environment:pair()},clock=self.clock,monotonic=lambda:0,
            journal=LiveSubmissionJournal(self.root/'LIVE_SUBMISSION_native_source.sqlite3'))
        coordinator=LiveExecutionCoordinator(admission,transport,provider=owner,protection_factory=bundle.protection_factory,clock=self.clock)
        venue=FakeSpotVenue(admission) if bundle.decision.engine_id=='SPOT' else FakeVenue(admission)
        patcher=patch.object(transport,'_opener',return_value=venue);patcher.start();self.addCleanup(patcher.stop)
        return coordinator,venue

    def plan(self,result,venue):
        bundle=prepare_strategy_entry(result.decision,venue.evidence,self.policy,now=self.clock(),protection_ttl_ms=20000)
        store=LiveStrategyPlanStore(self.root/'live-strategy-plans-native-source.sqlite3');store.initialize();store.save(bundle)
        return bundle,store

    def test_native_futures_algorithm_ai_plan_exact_central_submit_and_recovery_chain(self):
        cut,kw=self.inputs();expected=evaluate_futures_signal(cut.candles,self.strategy,self.futures)
        result=self.source.produce(cut,**kw)
        self.assertEqual(result.status,'PREPARED');self.assertEqual(result.decision.direction,expected['direction'])
        self.review_futures.assert_called_once();reviewed=self.review_futures.call_args.args[0]
        self.assertEqual(reviewed['score'],expected['score']);self.assertEqual(reviewed['environment'],'FUTURES_LIVE')
        bundle,store=self.plan(result,kw['venue']);coordinator,venue=self.coordinator(bundle);venue.fail_entry=True
        response=bundle.execute(coordinator,kw['facts'],plan_store=store,event_id='NATIVE_SOURCE_ENTRY')
        self.assertEqual(response['state'],'UNKNOWN');self.clock.value+=60;venue.fail_entry=False
        restored=LiveStrategyPlanStore(store.path).load(bundle.proposal.proposal_id)
        coordinator.protection_factory=restored.protection_factory
        recovered=restored.recover(coordinator,plan_store=store,event_id='NATIVE_SOURCE_RESTART')
        self.assertEqual(recovered['state'],'OPEN');self.assertTrue(recovered['protection_verified'])
        self.assertEqual(sum(m=='POST' and p=='/fapi/v1/order' for m,p,_ in venue.requests),1)
        self.review_futures.assert_called_once()

    def test_native_spot_swing_btc_regime_review_and_exact_oco_chain(self):
        cut,kw=self.inputs(environment='SPOT_LIVE')
        original=SwingStrategy(self.strategy,self.risk).evaluate('BTCUSDT',cut.candles,True)
        self.assertEqual(original.action,'BUY')
        result=self.source.produce(cut,**kw);self.assertEqual(result.status,'PREPARED')
        self.review.assert_called_once();self.assertEqual(self.review.call_args.args[0].score,original.score)
        bundle,store=self.plan(result,kw['venue']);coordinator,venue=self.coordinator(bundle)
        response=bundle.execute(coordinator,kw['facts'],plan_store=store,event_id='NATIVE_SPOT_ENTRY')
        self.assertEqual(response['state'],'OPEN');self.assertTrue(response['protection_verified']);self.assertEqual(len(venue.lists),1)

    def test_short_comes_from_existing_algorithm_and_ai_never_chooses_direction(self):
        result=self.produce(direction='DOWN');self.assertEqual(result.status,'PREPARED')
        self.assertEqual(result.decision.direction,'SHORT')
        proposed=self.review_futures.call_args.args[0];self.assertEqual(proposed['direction'],'SHORT')
        self.assertEqual(proposed['short_score'],85)

    def test_hold_is_journalled_without_any_ai_and_survives_restart(self):
        result=self.produce(direction='FLAT');self.assertEqual(result.status,'HOLD');self.assertIsNone(result.decision)
        self.review_futures.assert_not_called();self.review.assert_not_called()
        again=self.make_source().produce(*self.inputs(direction='FLAT')[:1],**self.inputs(direction='FLAT')[1])
        self.assertEqual(result,again)

    def test_same_closed_candle_never_repeats_ai_after_source_restart(self):
        result=self.produce();again=self.make_source().produce(*self.inputs()[:1],**self.inputs()[1])
        self.assertEqual(result,again);self.review_futures.assert_called_once()
        receipt=self.journal.load(result.record_id)
        self.assertEqual(receipt['evidence']['inputs']['cut']['rows'][-1][6],int(NOW*1000)-1)
        self.assertEqual(result.evidence_digest,result.decision.source_digest)

    def test_changed_budget_or_account_cut_cannot_revive_cached_larger_decision(self):
        self.produce();cut,kw=self.inputs()
        for change in ({'budget':replace(self.budget,capital_units=20*U)},
                       {'facts':replace(kw['facts'],free_units=20*U)}):
            with self.assertRaisesRegex(LiveError,'CACHED_INPUTS_CHANGED'):
                self.source.produce(cut,**(kw|change))
        self.review_futures.assert_called_once()

    def test_changed_ai_settings_require_explicit_source_rebuild(self):
        self.ai.settings=replace(self.ai.settings,fail_closed=False)
        with self.assertRaisesRegex(LiveError,'AI_SETTINGS_CHANGED'):self.produce()
        self.review_futures.assert_not_called()

    def test_durable_shared_ai_budget_limits_across_engines(self):
        source=self.make_source(maximum_reviews_per_day=1)
        cut,kw=self.inputs();source.produce(cut,**kw)
        cut,kw=self.inputs(environment='SPOT_LIVE')
        with self.assertRaisesRegex(LiveError,'DAILY_BUDGET_EXHAUSTED'):source.produce(cut,**kw)
        self.review.assert_not_called();self.review_futures.assert_called_once()

    def test_crash_after_review_claim_is_unknown_never_reissued(self):
        with patch.object(self.journal,'finish',side_effect=RuntimeError('synthetic process crash')):
            with self.assertRaises(RuntimeError):self.produce()
        with self.assertRaisesRegex(LiveError,'REVIEW_OUTCOME_UNKNOWN'):self.make_source().produce(*self.inputs()[:1],**self.inputs()[1])
        self.review_futures.assert_called_once()

    def test_ai_failure_rejects_then_caches_without_fallback_allow(self):
        self.review_futures.side_effect=TimeoutError('synthetic timeout')
        result=self.produce();self.assertEqual(result.status,'AI_REJECTED');self.assertIsNone(result.decision)
        self.assertIn('failed safely',self.journal.load(result.record_id)['evidence']['review']['reason'])
        self.produce();self.review_futures.assert_called_once()

    def test_invalid_futures_ai_response_cannot_reverse_reduce_or_create_trade(self):
        for review in ({'verdict':'ALLOW','direction':'SHORT'},AIReview('REDUCE',1,.5,'reduce'),
                       AIReview('ALLOW',float('nan'),1,'nan'),AIReview('ALLOW',.1,1,'low confidence')):
            with self.subTest(review=review):
                journal=LiveProposalSourceJournal(self.root/('live-proposal-source-invalid-'+str(id(review))+'.sqlite3'));journal.initialize()
                source=self.make_source(journal=journal);self.review_futures.return_value=review
                cut,kw=self.inputs();result=source.produce(cut,**kw)
                self.assertEqual(result.status,'AI_REJECTED');self.assertIsNone(result.decision)

    def test_spot_ai_reduce_only_lowers_deterministic_size(self):
        self.review.return_value=AIReview('REDUCE',.9,.25,'reduce to quarter risk')
        result=self.produce(environment='SPOT_LIVE');self.assertEqual(result.status,'PREPARED')
        evidence=self.journal.load(result.record_id)['evidence']
        self.assertLessEqual(evidence['final_sizing']['inclusive_stop_risk_units'],evidence['initial_sizing']['risk_cap_units']//4)
        self.assertLessEqual(Decimal(result.decision.quantity),Decimal(str(self.review.call_args.args[2]['free_capital'])))

    def test_stale_after_ai_blocks_new_entry_but_retains_auditable_review(self):
        def delay(*args):self.clock.value+=31;return AIReview('ALLOW',.9,1,'late')
        self.review_futures.side_effect=delay
        result=self.produce();self.assertEqual(result.status,'QUANTITATIVE_REJECTED');self.assertIsNone(result.decision)
        self.assertIn('STALE',self.journal.load(result.record_id)['evidence']['post_review_block'])

    def test_missing_account_flags_cross_scope_or_stale_facts_do_not_spend_ai(self):
        cut,kw=self.inputs()
        for bad in (replace(kw['facts'],orders_reconciled=False),replace(kw['facts'],cashflows_complete=False),
                    facts(self.scope,at=NOW-31),facts(Scope('OTHER','FUTURES_LIVE','USDT'))):
            with self.subTest(evidence=bad.evidence_id),self.assertRaises(LiveError):self.source.produce(cut,**(kw|{'facts':bad}))
        self.review_futures.assert_not_called()

    def test_unapproved_or_duplicate_asset_is_not_sized_and_no_ai_is_called(self):
        cut,kw=self.inputs();p=PositionFact('EXISTING','FUTURES','BTCUSDT','LONG',100*U,5*U,1000,'CRYPTO_FACTOR',NOW,True)
        with self.assertRaisesRegex(LiveError,'EXISTING_ASSET'):self.source.produce(cut,**(kw|{'facts':facts(self.scope,positions=(p,))}))
        unknown=replace(cut,symbol='SOLUSDT')
        with self.assertRaisesRegex(LiveError,'PARTICIPANT_NOT_APPROVED'):
            self.source.produce(unknown,**(kw|{'venue':self.venue(symbol='SOLUSDT')}))
        self.review_futures.assert_not_called()

    def test_zero_budget_price_chase_filters_and_leverage_block_before_ai(self):
        cut,kw=self.inputs()
        for change in ({'budget':replace(self.budget,capital_units=0)},
                       {'venue':self.venue(reference='102')},
                       {'venue':replace(kw['venue'],evidence=replace(kw['venue'].evidence,filters_complete=False))},
                       {'budget':replace(self.budget,leverage_milli=2000)}):
            with self.subTest(change=list(change)),self.assertRaises(LiveError):self.source.produce(cut,**(kw|change))
        self.review_futures.assert_not_called()

    def test_quantities_and_costs_are_exact_integer_conservative_and_no_capital_default(self):
        cut,kw=self.inputs();budget=replace(self.budget,capital_units=80*U,gross_units=400*U,stop_risk_units=U)
        result=self.source.produce(cut,**(kw|{'budget':budget}));e=self.journal.load(result.record_id)['evidence']['final_sizing']
        self.assertLessEqual(e['principal_units']+e['cost_buffer_units'],80*U)
        self.assertLessEqual(e['inclusive_stop_risk_units'],U)
        self.assertTrue(all(type(e[k]) is int for k in e))
        self.assertEqual(Decimal(result.decision.quantity)%Decimal('.001'),0)
        with self.assertRaises(TypeError):NativeEntryBudget()

    def test_typed_spot_btc_cut_and_approved_futures_configuration_are_required(self):
        cut,kw=self.inputs(environment='SPOT_LIVE')
        with self.assertRaisesRegex(LiveError,'BTC_REGIME_CUT'):self.source.produce(cut,**(kw|{'btc_cut':None}))
        cut,kw=self.inputs();venue=replace(kw['venue'],evidence=replace(kw['venue'].evidence,isolated_margin_verified=False))
        with self.assertRaisesRegex(LiveError,'VENUE_TERMS'):self.source.produce(cut,**(kw|{'venue':venue}))
        self.review_futures.assert_not_called();self.review.assert_not_called()

    def test_fail_open_advisor_is_not_accepted_and_journal_is_separate_explicit(self):
        self.ai.settings=replace(self.ai.settings,fail_closed=False)
        with self.assertRaisesRegex(LiveError,'FAIL_CLOSED_AI'):self.make_source()
        missing=LiveProposalSourceJournal(self.root/'live-proposal-source-missing.sqlite3')
        with self.assertRaisesRegex(LiveError,'NOT_INITIALIZED'):missing.load('UNKNOWN')
        self.assertFalse(missing.path.exists())
        with self.assertRaisesRegex(LiveError,'SEPARATE_NATIVE_SOURCE'):LiveProposalSourceJournal(self.root/'wallet.sqlite3')

    def test_source_journal_rejects_hardlink_before_financial_metadata_is_touched(self):
        financial=self.root/'synthetic-financial.sqlite3'
        with closing(sqlite3.connect(financial)) as db,db:db.execute('CREATE TABLE wallet(balance INTEGER)')
        original=financial.read_bytes();alias=self.root/'live-proposal-source-hardlink.sqlite3'
        try:os.link(financial,alias)
        except PermissionError:self.skipTest('Sandbox denies OS hardlink creation; descriptor nlink guard tested separately')
        guarded=LiveProposalSourceJournal(alias)
        for operation in (guarded.initialize,lambda:guarded.load('UNKNOWN')):
            with self.assertRaisesRegex(LiveError,'NONPRIVATE_NATIVE_SOURCE_JOURNAL'):operation()
        self.assertEqual(financial.read_bytes(),original)
        self.assertFalse(alias.with_name(alias.name+'-journal').exists())

    def test_source_descriptor_link_count_change_is_rejected_before_sqlite_access(self):
        before=self.journal.path.read_bytes();real_fstat=os.fstat
        def linked(descriptor):
            values=list(real_fstat(descriptor));values[3]=2;return os.stat_result(values)
        with patch('trader.live_strategy_adapter.os.fstat',side_effect=linked):
            with self.assertRaisesRegex(LiveError,'NONPRIVATE_NATIVE_SOURCE_JOURNAL'):self.journal.load('UNKNOWN')
        self.assertEqual(self.journal.path.read_bytes(),before)

    def test_source_journal_rejects_named_identity_change_before_sqlite_pragmas(self):
        identity=self.journal._safe()
        with patch.object(self.journal,'_safe',side_effect=[identity,(identity[0],identity[1]+1)]):
            with self.assertRaisesRegex(LiveError,'IDENTITY_CHANGED'):self.journal.load('UNKNOWN')


class PublicLiveCandleReaderTests(unittest.TestCase):
    def setUp(self):
        self.socket=patch('socket.socket.connect',side_effect=AssertionError('No actual network permitted'))
        self.socket.start();self.addCleanup(self.socket.stop)
        self.clock=Clock()
        self.reader=LivePublicCandleReader(timeout_seconds=5,maximum_requests_per_minute=4,clock=self.clock,monotonic=lambda:0)

    def fake(self,**changes):
        venue=FakePublicVenue([list(row) for row in raw_rows()],**changes)
        patcher=patch.object(self.reader,'_opener',return_value=venue);patcher.start();self.addCleanup(patcher.stop)
        return venue

    def test_functional_fixed_get_time_and_klines_reuses_original_client_interface_without_keys(self):
        venue=self.fake()
        for env,host,path in (('SPOT_LIVE','https://api.binance.com','/api/v3/klines'),
                              ('FUTURES_LIVE','https://fapi.binance.com','/fapi/v1/klines')):
            cut=self.reader.fetch(env,'BTCUSDT','1h',limit=250)
            self.assertEqual(cut.host,host);self.assertEqual(cut.endpoint,path);self.assertEqual(len(cut.candles),160)
        self.assertEqual(len(venue.requests),4)
        for request in venue.requests:
            self.assertEqual(request.get_method(),'GET');self.assertIsNone(request.data)
            self.assertNotIn('X-mbx-apikey',dict(request.header_items()));self.assertNotIn('signature',request.full_url)
        self.assertFalse(hasattr(self.reader,'api_key'));self.assertFalse(hasattr(self.reader,'api_secret'))

    def test_reader_never_accepts_testnet_private_writes_or_extra_fields(self):
        self.fake()
        for env in ('SPOT_TESTNET','FUTURES_DEMO','SHADOW','PAPER'):
            with self.assertRaisesRegex(LiveError,'FIXED_LIVE'):self.reader.fetch(env,'BTCUSDT','1h',limit=250)
        with self.assertRaisesRegex(LiveError,'GET_ONLY'):self.reader._request('POST','/api/v3/order')
        with self.assertRaisesRegex(LiveError,'GET_ONLY'):self.reader.server_time()

    def test_open_candle_is_discarded_and_only_closed_data_is_used(self):
        venue=self.fake();row=list(venue.rows[-1]);row[0]+=3600_000;row[6]+=3600_000;venue.rows.append(row)
        cut=self.reader.fetch('FUTURES_LIVE','BTCUSDT','1h',limit=250)
        self.assertEqual(len(cut.rows),160);self.assertLess(cut.rows[-1][6],NOW*1000)

    def test_malformed_gapped_future_nonfinite_ohlc_or_wrong_provenance_is_rejected(self):
        good=candle_cut()
        alternatives=[]
        rows=[list(row) for row in good.rows];rows[20][0]+=3600_000;alternatives.append(tuple(tuple(row) for row in rows))
        rows=[list(row) for row in good.rows];rows[-1][4]='NaN';alternatives.append(tuple(tuple(row) for row in rows))
        rows=[list(row) for row in good.rows];rows[-1][4]='1000';alternatives.append(tuple(tuple(row) for row in rows))
        rows=[list(row) for row in good.rows];rows[-1][6]+=1;alternatives.append(tuple(tuple(row) for row in rows))
        for wrong in alternatives:
            with self.assertRaises(LiveError):replace(good,rows=wrong)
        for change in ({'host':'https://testnet.binancefuture.com'},{'environment':'FUTURES_DEMO'},
                       {'endpoint':'/api/v3/klines'},{'as_of':NOW-30}):
            with self.assertRaises(LiveError):replace(good,**change)

    def test_request_budget_counts_failures_and_no_unbounded_retry(self):
        venue=self.fake();venue.redirect=True
        for _ in range(4):
            with self.assertRaisesRegex(LiveError,'REDIRECT'):self.reader.fetch('SPOT_LIVE','BTCUSDT','1h',limit=250)
        with self.assertRaisesRegex(LiveError,'BUDGET_EXHAUSTED'):self.reader.fetch('SPOT_LIVE','BTCUSDT','1h',limit=250)
        self.assertEqual(len(venue.requests),4)

    def test_oversized_response_and_exchange_clock_drift_fail_closed(self):
        venue=self.fake();venue.oversized=True
        with self.assertRaisesRegex(LiveError,'TOO_LARGE'):self.reader.fetch('SPOT_LIVE','BTCUSDT','1h',limit=250)
        venue.oversized=False;venue.at=NOW+60
        with self.assertRaisesRegex(LiveError,'CLOCK_OR_LATENCY'):self.reader.fetch('SPOT_LIVE','BTCUSDT','1h',limit=250)


if __name__=='__main__':unittest.main()
