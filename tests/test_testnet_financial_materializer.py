"""Synthetic diagnostics only: no files, network, credentials or trading."""
from copy import deepcopy
import json
import unittest

from trader.account_inventory import HOSTS
from trader.financial_evidence import AUTHORITY, FLAGS, digest
from trader.testnet_financial_materializer import reconcile_testnet_sources, materialize_testnet_sources
from tests.test_financial_evidence import fixture


def packet(engine='SPOT'):
    reg, original, _, _ = fixture(engine=engine)
    scope = reg['environment']
    start = 1792713600000  # 2026-10-23T00:00:00Z
    end = start + 3600000
    ledger = {'at':original['received_at'],'environment':scope,'positions':[],
              'trades':[],'latest_equity':None,'native_protection':None,'scope':'LOCAL_LEDGER_ONLY'}
    result = {'schema':1,'environment':scope,'registration':reg,'original':original,
              'baseline':{'ledger':deepcopy(ledger)},'closing_ledger':deepcopy(ledger),
              'symbol_universe':['BTCUSDT'],'source_scope':'BOUNDED_SYMBOLS',
              'sources':[],'source_refs':[]}
    if engine == 'SPOT':
        account = {'uid':123,'balances':[{'asset':'USDT','free':'100','locked':'5'},
                                          {'asset':'BTC','free':'0.1','locked':'0'}]}
        add(result,'/api/v3/account',account)
        add(result,'/api/v3/myTrades',[],{'symbol':'BTCUSDT','startTime':start,'endTime':end-1,'limit':1000})
    else:
        account = {'assets':[{'asset':'USDT','walletBalance':'100'}],
                   'positions':[{'symbol':'BTCUSDT','positionAmt':'0.1','positionSide':'BOTH'}]}
        add(result,'/fapi/v3/account',account)
        add(result,'/fapi/v3/balance',[{'asset':'USDT','balance':'100','accountAlias':'synthetic'}])
        add(result,'/fapi/v1/userTrades',[],{'symbol':'BTCUSDT','startTime':start,'endTime':end-1,'limit':1000})
        add(result,'/fapi/v1/income',[],{'startTime':start,'endTime':end-1,'limit':1000})
    return result


def add(value,endpoint,response,params=None):
    source = {'schema':1,'environment':value['environment'],'host':HOSTS[value['environment']],
              'endpoint':endpoint,'params':params or {},'started_ms':1792717200001,
              'received_ms':1792717200002,'response':response}
    value['sources'].append(source)
    reseal(value)


def reseal(value):
    value['source_refs'] = [{'file':f'responses/{i:012d}.dpapi','sha256':digest(source),
                            'encrypted_sha256':'a'*64} for i,source in enumerate(value['sources'])]


def trade(*,futures=False,**changes):
    result = {'symbol':'BTCUSDT','id':10,'orderId':20,'time':1792713600000,
              'qty':'0.1','quoteQty':'10','price':'100','commission':'0.01','commissionAsset':'USDT'}
    result.update({'side':'BUY','positionSide':'BOTH','realizedPnl':'0'} if futures else {'isBuyer':True})
    result.update(changes)
    return result


def history(value):
    return next(source for source in value['sources'] if source['endpoint'].endswith(('myTrades','userTrades')))


class TestnetFinancialMaterializerTests(unittest.TestCase):
    def assert_closed(self,result):
        summary = result['summary']
        self.assertFalse(summary['financial_window_complete'])
        self.assertFalse(summary['canonical_bundle_produced'])
        self.assertEqual(summary['source_scope'],'BOUNDED_SYMBOLS')
        self.assertTrue(all(summary[name] is False for name in (*FLAGS,*AUTHORITY)))
        self.assertNotIn('ledger',result)
        self.assertNotIn('exchange',result)

    def test_normalizes_spot_known_quantities_fees_and_observed_total_balance(self):
        value=packet();history(value)['response']=[trade()];reseal(value)
        result=reconcile_testnet_sources(value);self.assert_closed(result)
        row=result['details']['normalized_fills'][0]
        self.assertEqual((row['quantity_units'],row['quote_units'],row['fee_units']),(10000000,1000000000,1000000))
        self.assertEqual(row['order_id'],'20');self.assertFalse(row['ownership_verified'])
        self.assertEqual(result['details']['observed_account_cuts'][0]['assets'][0]['wallet_units'],10500000000)
        totals=result['details']['known_totals']
        self.assertEqual(totals['spot_fill_cash_delta_usdt_units'],-1001000000)
        self.assertEqual(totals['spot_net_inventory_delta_by_symbol_units'],{'BTCUSDT':10000000})

    def test_empty_history_never_establishes_completeness_or_protection(self):
        result=materialize_testnet_sources(packet());self.assert_closed(result)
        self.assertEqual(result['summary']['counts']['normalized_fills'],0)
        self.assertIn('CASHFLOW_SOURCE_COVERAGE_UNPROVEN',result['summary']['reason_codes'])
        self.assertIn('PROTECTION_INTERVALS_UNPROVEN',result['summary']['reason_codes'])
        self.assertFalse(result['details']['history_queries'][0]['pagination_exhaustion_verified'])

    def test_opaque_assets_and_precise_observations_preserve_other_account_facts(self):
        value=packet()
        value['sources'][0]['response']['balances'].extend([
            {'asset':'币安人生','free':'0.0000000001','locked':'0'},
            {'asset':'MixedCase','free':'1','locked':'0'}])
        reseal(value);result=reconcile_testnet_sources(value);self.assert_closed(result)
        assets=result['details']['observed_account_cuts'][0]['assets']
        unknown=next(row for row in assets if row['asset']=='币安人生')
        self.assertIsNone(unknown['wallet_units'])
        self.assertEqual(unknown['free_decimal'],'0.0000000001')
        self.assertTrue(any(row['asset']=='USDT' for row in assets))
        self.assertIn('DECIMAL_NOT_EXACT_AT_UNIT8',result['summary']['reason_codes'])

    def test_out_of_scope_position_does_not_erase_supported_observed_positions(self):
        value=packet('FUTURES')
        value['sources'][0]['response']['positions'].extend([
            {'symbol':'BTCUSDC','positionAmt':'0','positionSide':'BOTH'},
            {'symbol':'ETHUSDT','positionAmt':'0.0000000001','positionSide':'BOTH'}])
        reseal(value);result=reconcile_testnet_sources(value);self.assert_closed(result)
        account=result['details']['observed_account_cuts'][0]
        self.assertEqual(len(account['positions']),2)
        self.assertEqual(len(account['unrecognized_position_rows']),1)
        self.assertIn('ACCOUNT_POSITION_SYMBOL_OUTSIDE_USDT_SCOPE',result['summary']['reason_codes'])

    def test_parent_and_disjoint_children_dedupe_identical_native_ids(self):
        value=packet();parent=history(value);parent['response']=[trade()]
        child=deepcopy(parent);child['params']['endTime']=child['params']['startTime']+1000
        value['sources'].append(child);reseal(value)
        result=reconcile_testnet_sources(value)
        self.assertEqual(result['summary']['counts']['normalized_fills'],1)
        self.assertEqual(result['summary']['counts']['contradictory_native_ids'],0)

    def test_contradictory_same_native_id_is_excluded_and_rejected(self):
        value=packet();history(value)['response']=[trade(),trade(qty='0.2')];reseal(value)
        result=reconcile_testnet_sources(value);self.assert_closed(result)
        self.assertEqual(result['summary']['state'],'DIAGNOSTIC_REJECTED')
        self.assertEqual(result['details']['normalized_fills'],[])
        self.assertIn('DUPLICATE_NATIVE_ID_CONTRADICTION',result['summary']['reason_codes'])
        self.assertEqual(result['details']['known_totals']['fill_fees_by_asset_units'],{})

    def test_stable_ids_ignore_query_page_order_but_include_symbol(self):
        value=packet();history(value)['response']=[trade()];reseal(value)
        first=reconcile_testnet_sources(value)['details']['normalized_fills'][0]['ref']
        value['sources'].reverse();reseal(value)
        second=reconcile_testnet_sources(value)['details']['normalized_fills'][0]['ref']
        self.assertEqual(first,second)
        value['symbol_universe'].append('ETHUSDT')
        add(value,'/api/v3/myTrades',[trade(symbol='ETHUSDT')],
            {'symbol':'ETHUSDT','startTime':1792713600000,'endTime':1792717199999,'limit':1000})
        self.assertEqual(len(reconcile_testnet_sources(value)['details']['normalized_fills']),2)

    def test_exact_unit8_rejects_extra_precision_provider_float_and_nonfinite(self):
        for invalid in ('0.000000001',0.1,'NaN','Infinity',True):
            with self.subTest(invalid=invalid):
                value=packet();history(value)['response']=[trade(qty=invalid)];reseal(value)
                result=reconcile_testnet_sources(value)
                self.assertEqual(result['details']['normalized_fills'],[]);self.assert_closed(result)
                self.assertEqual(result['summary']['counts']['rejected_records'],1)

    def test_extreme_exponents_are_rejected_before_underflow_or_account_formatting(self):
        for extreme in ('1e-2000000','0e-2000000','1e2000000'):
            with self.subTest(extreme=extreme):
                value=packet();history(value)['response']=[trade(qty=extreme)]
                value['sources'][0]['response']['balances'][0]['free']=extreme
                reseal(value);result=reconcile_testnet_sources(value);self.assert_closed(result)
                self.assertEqual(result['details']['normalized_fills'],[])
                asset=result['details']['observed_account_cuts'][0]['assets'][0]
                self.assertIsNone(asset['free_units']);self.assertIsNone(asset['free_decimal'])
                self.assertIsNone(asset['wallet_decimal'])
                self.assertIn('DECIMAL_SOURCE_EXPONENT_OUT_OF_RANGE',result['summary']['reason_codes'])
        # Representable source precision remains exact, with no rounding.
        value=packet();history(value)['response']=[trade(qty='0.100000000000000000')]
        reseal(value);result=reconcile_testnet_sources(value)
        self.assertEqual(result['details']['normalized_fills'][0]['quantity_units'],10000000)

    def test_malformed_nested_objects_return_closed_diagnostics(self):
        for name in ('registration','original','baseline','closing_ledger'):
            for malformed in (None,[],False,'opaque'):
                with self.subTest(name=name,malformed=malformed):
                    value=packet();value[name]=malformed
                    result=reconcile_testnet_sources(value);self.assert_closed(result)
                    self.assertEqual(result['summary']['state'],'DIAGNOSTIC_REJECTED')
                    self.assertIn('NESTED_TESTNET_SOURCE_OBJECT_REQUIRED',result['summary']['reason_codes'])

    def test_half_open_window_and_requested_slice_are_both_enforced(self):
        for at, end in ((1792717200000,1792717199999),(1792713600002,1792713600001)):
            value=packet();source=history(value);source['response']=[trade(time=at)]
            source['params']['endTime']=end;reseal(value)
            result=reconcile_testnet_sources(value)
            self.assertEqual(result['details']['normalized_fills'],[])
            self.assertIn('EVENT_OUTSIDE_REQUESTED_HISTORY_SLICE',result['summary']['reason_codes'])

    def test_invalid_native_ids_and_symbol_mismatch_cannot_become_fills(self):
        for changes in ({'id':True},{'orderId':0},{'id':'nan'},{'symbol':'ETHUSDT'}):
            value=packet();history(value)['response']=[trade(**changes)];reseal(value)
            self.assertEqual(reconcile_testnet_sources(value)['details']['normalized_fills'],[])

    def test_base_asset_fee_is_inventory_debit_and_exact_fraction_not_rounded(self):
        value=packet();history(value)['response']=[trade(qty='3',quoteQty='1',commission='0.00000001',commissionAsset='BTC')];reseal(value)
        result=reconcile_testnet_sources(value);row=result['details']['normalized_fills'][0]
        self.assertIsNone(row['fee_quote_units'])
        self.assertEqual(row['fee_quote_exact_fraction'],{'numerator':100000000,'denominator':300000000})
        self.assertEqual(result['details']['known_totals']['spot_net_inventory_delta_by_symbol_units']['BTCUSDT'],299999999)
        self.assertIn('FEE_QUOTE_VALUATION_NOT_EXACT_UNIT8',result['summary']['reason_codes'])

    def test_third_asset_commission_stays_known_in_asset_with_unknown_quote_value(self):
        value=packet();history(value)['response']=[trade(commissionAsset='BNB')];reseal(value)
        result=reconcile_testnet_sources(value)
        self.assertEqual(result['details']['known_totals']['fill_fees_by_asset_units'],{'BNB':1000000})
        self.assertIsNone(result['details']['normalized_fills'][0]['fee_quote_units'])
        self.assertIn('THIRD_ASSET_FEE_VALUATION_UNPROVEN',result['summary']['reason_codes'])

    def test_futures_keeps_income_separate_and_compares_commission_without_double_count(self):
        value=packet('FUTURES');history(value)['response']=[trade(futures=True)]
        income=next(s for s in value['sources'] if s['endpoint'].endswith('/income'))
        income['response']=[{'incomeType':'COMMISSION','tranId':1,'time':1792713600000,
                             'asset':'USDT','income':'-0.01','symbol':'BTCUSDT','tradeId':'10'},
                            {'incomeType':'FUNDING_FEE','tranId':1,'time':1792713600001,
                             'asset':'USDT','income':'0.002','symbol':'BTCUSDT','tradeId':''}]
        reseal(value);result=reconcile_testnet_sources(value);self.assert_closed(result)
        self.assertEqual(len(result['details']['normalized_income']),2)
        self.assertTrue(result['details']['commission_comparison']['observed_totals_equal'])
        self.assertEqual(result['details']['known_totals']['income_by_kind_asset_units'],
                         {'COMMISSION:USDT':-1000000,'FUNDING_FEE:USDT':200000})

    def test_ledger_quantity_is_compared_independently_without_exchange_copy(self):
        value=packet();value['closing_ledger']['positions']=[{'symbol':'BTCUSDT','quantity':'0.2'}]
        result=reconcile_testnet_sources(value)
        local=result['details']['ledger_observations']['closing']['positions'][0]
        self.assertEqual(local['quantity_units'],20000000)
        comparison=result['details']['comparisons'][0]
        self.assertEqual(comparison['exchange_quantity_units'],10000000)
        self.assertFalse(comparison['observed_units_equal']);self.assertFalse(comparison['reconciliation_verified'])
        self.assertIn('OBSERVED_POSITION_QUANTITY_DIFFERENCE',result['summary']['reason_codes'])

    def test_legacy_real_does_not_gain_exact_source_precision_and_is_never_rounded(self):
        value=packet();value['closing_ledger']['positions']=[{'symbol':'BTCUSDT','quantity':0.1000000001}]
        result=reconcile_testnet_sources(value)
        local=result['details']['ledger_observations']['closing']['positions'][0]
        self.assertIsNone(local['quantity_units']);self.assertFalse(local['exact_original_decimal_source'])
        self.assertIn('LEGACY_FLOAT_PRECISION_UNPROVEN',result['summary']['reason_codes'])
        self.assertIn('DECIMAL_NOT_EXACT_AT_UNIT8',result['summary']['reason_codes'])

    def test_tampered_source_digest_and_changed_account_identity_fail_closed(self):
        value=packet();value['sources'][0]['response']['uid']=999
        result=reconcile_testnet_sources(value)
        self.assertIn('RETAINED_SOURCE_BINDING_INVALID',result['summary']['reason_codes'])
        value=packet();other=deepcopy(value['sources'][0]['response']);other['uid']=999
        add(value,'/api/v3/account',other)
        result=reconcile_testnet_sources(value)
        self.assertIn('TESTNET_REPORTED_ACCOUNT_CHANGED',result['summary']['reason_codes'])
        self.assertEqual(result['summary']['state'],'DIAGNOSTIC_REJECTED')

    def test_safe_summary_has_no_identifiers_amounts_or_provider_bodies(self):
        value=packet();history(value)['response']=[trade(clientOrderId='private-unique-client-id')];reseal(value)
        result=reconcile_testnet_sources(value);safe=json.dumps(result['summary'])
        self.assertNotIn('private-unique-client-id',safe);self.assertNotIn('wallet_units',safe)
        self.assertNotIn('account_ref',safe);self.assertNotIn('trade_id',safe)
        self.assertIn('private-unique-client-id',json.dumps(result['details']))

    def test_malformed_packets_and_raw_failures_return_diagnostics_without_raising(self):
        for invalid in (None,{},[],{'schema':True},packet()|{'source_scope':'ALL_ACCOUNT'}):
            self.assert_closed(reconcile_testnet_sources(invalid))
        value=packet();source=history(value);source.pop('response');source['failure']='PRIVATE RAW ERROR'
        reseal(value);result=reconcile_testnet_sources(value)
        self.assertIn('TESTNET_GET_SOURCE_UNAVAILABLE',result['summary']['reason_codes'])
        self.assertNotIn('PRIVATE RAW ERROR',json.dumps(result['summary']))


if __name__ == '__main__':
    unittest.main()
