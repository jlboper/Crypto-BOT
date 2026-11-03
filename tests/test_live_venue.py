"""GET venue filters and encrypted retention boundary using fake data only."""
import hashlib
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from trader.live_transport import LiveReadOnlyTransport, LiveError, LiveHTTPError
from trader.live_venue import LiveVenueReader
from trader.live_execution_runtime import ConfirmedPosition
from trader.live_transport import LiveOrderIntent
from tests.test_live_preproduction import pair
from tests.test_central_admission import NOW
from tests import test_live_strategy_adapter as fixtures


class LiveVenueTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeStrategyAdapterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.plan = self.fixture.prepare(self.fixture.spot_decision())
        self.rows = [
            {'filterType':'PRICE_FILTER','minPrice':'0.01','maxPrice':'1000000','tickSize':'0.01'},
            {'filterType':'LOT_SIZE','minQty':'0.001','maxQty':'100','stepSize':'0.001'},
            {'filterType':'MARKET_LOT_SIZE','minQty':'0','maxQty':'100','stepSize':'0'},
            {'filterType':'MIN_NOTIONAL','minNotional':'5','applyToMarket':True,'avgPriceMins':0}]
        self.receipts = []
        self.reference = {}
        self.average = {}
        self.orders = []
        self.order_lists = []
        self.transport = LiveReadOnlyTransport({'SPOT_LIVE':pair()}, clock=self.fixture.clock)
        def retain(value):
            self.receipts.append(value)
            return {'sha256':hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()}
        self.reader = LiveVenueReader(self.transport, retain=retain, clock=self.fixture.clock)
        patcher = patch.object(self.transport, 'get', side_effect=self.get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, env, endpoint, params=None):
        self.assertEqual(env, 'SPOT_LIVE')
        if endpoint.endswith('/time'):
            return {'serverTime':int(self.fixture.clock() * 1000)}
        if endpoint.endswith('/exchangeInfo'):
            return {'symbols':[{'symbol':'BTCUSDT','status':'TRADING','quoteAsset':'USDT','filters':self.rows,
                'orderTypes':['MARKET','LIMIT_MAKER','STOP_LOSS_LIMIT'],'ocoAllowed':True}], 'exchangeFilters':[]}
        if endpoint.endswith('/depth'):
            return {'lastUpdateId':1,'bids':[['99.99','10']],'asks':[['100','10']]}
        if endpoint.endswith('/account/commission'):
            zero = {'maker':'0','taker':'0','buyer':'0','seller':'0'}
            return {'symbol':'BTCUSDT','standardCommission':{**zero,'maker':'0.001','taker':'0.001'},
                'specialCommission':zero,'taxCommission':zero}
        if endpoint == '/api/v3/referencePrice':
            return {'symbol':'BTCUSDT','referencePrice':'100','timestamp':int(self.fixture.clock()*1000),**self.reference}
        if endpoint == '/api/v3/avgPrice':
            return {'mins':0,'price':'100','closeTime':int(self.fixture.clock()*1000),**self.average}
        if endpoint == '/api/v3/executionRules':
            return {'symbolRules':[]}
        if endpoint == '/api/v3/openOrders':
            return self.orders
        if endpoint == '/api/v3/openOrderList':
            return self.order_lists
        if endpoint == '/api/v3/account':
            return {'balances':[{'asset':'BTC','free':'0','locked':'0'}]}
        raise AssertionError(endpoint)

    def test_originals_retained_and_exact_filters_checked(self):
        self.assertTrue(self.reader.validate(self.plan, NOW))
        self.assertEqual(len(self.receipts), 6)
        self.rows[1]['maxQty'] = '0.5'
        self.assertFalse(self.reader.validate(self.plan, NOW))

    def test_unknown_filter_blocks_and_missing_average_interval_is_not_guessed(self):
        self.rows.append({'filterType':'FUTURE_NEW_FILTER'})
        self.assertFalse(self.reader.validate(self.plan, NOW))
        self.rows.pop()
        self.reference = {'referencePrice':None}
        self.rows[-1]['avgPriceMins'] = 5
        self.assertFalse(self.reader.validate(self.plan, NOW))

    def test_changed_price_tick_notional_and_expired_plan_rejected(self):
        self.rows[0]['tickSize'] = '1'
        self.assertFalse(self.reader.validate(self.plan, NOW))
        self.rows[0]['tickSize'] = '0.01'
        self.rows[-1]['minNotional'] = '110'
        self.assertFalse(self.reader.validate(self.plan, NOW))
        self.rows[-1]['minNotional'] = '5'
        self.fixture.clock.value += 31
        self.assertFalse(self.reader.validate(self.plan, self.fixture.clock()))

    def test_depth_fee_and_unknown_order_types_do_not_use_fixed_assumptions(self):
        original = self.get
        for route, replacement in (
                ('/api/v3/depth', {'lastUpdateId':1,'bids':[['99.99','0.1']],'asks':[['100','0.1']]}),
                ('/api/v3/account/commission', {'symbol':'BTCUSDT','standardCommission':{}}),
                ('/api/v3/exchangeInfo', {'symbols':[{'symbol':'BTCUSDT','status':'TRADING','quoteAsset':'USDT','filters':self.rows}]})):
            with patch.object(self.transport, 'get', side_effect=lambda env, endpoint, params=None: replacement if endpoint == route else original(env, endpoint, params)):
                try:
                    valid = self.reader.validate(self.plan, NOW)
                except LiveError:
                    valid = False
                self.assertFalse(valid)

    def test_retention_failure_blocks_successful_http(self):
        self.reader.retain = lambda value: {}
        with self.assertRaisesRegex(LiveError, 'RECEIPT_REQUIRED'):
            self.reader.capture('SPOT_LIVE', 'BTCUSDT')

    def test_cli_has_no_write_transport_or_authority_provisioning(self):
        from scripts import diagnose_live_readiness as cli
        from trader.live_account import EncryptedAuditStore
        original = EncryptedAuditStore
        destination = self.fixture.root / 'private-diagnostic'
        # A synthetic encryption function is explicit in this fixture; the CLI
        # production constructor has only Windows-user DPAPI, no plaintext mode.
        with patch.object(cli, 'LiveCredentialVault') as vault, \
                patch.object(cli, 'LiveReadOnlyTransport', return_value=self.transport), \
                patch.object(cli, 'LiveVenueReader', side_effect=lambda transport, retain: LiveVenueReader(transport, retain=retain, clock=self.fixture.clock)), \
                patch.object(cli, 'EncryptedAuditStore', side_effect=lambda path: original(path, protect=lambda raw: b'SYNTHETIC-ENC:' + raw)), \
                patch('trader.live_transport.LiveOrderTransport.__init__', side_effect=AssertionError('No write transport')), \
                patch('sys.stdout', new_callable=io.StringIO) as stdout:
            vault.return_value.read.return_value = {'SPOT_LIVE':pair()}
            code = cli.main(['--source',str(self.fixture.root),'--raw-parent',str(destination),
                '--scope','SPOT_LIVE','--symbol','BTCUSDT'])
            result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(result['commissioned'])
        self.assertFalse(result['execution_enabled'])
        self.assertFalse((self.fixture.root / 'data/live-preproduction/authorization.dpapi').exists())
        self.assertEqual(len(list(destination.glob('*/response-*.dpapi'))), 9)
        self.assertNotIn(pair().api_key, json.dumps(result))

    def test_diagnostic_retains_closed_codes_without_arbitrary_error_text(self):
        from scripts.diagnose_live_readiness import safe_diagnostic
        self.assertEqual(safe_diagnostic(LiveError('VENUE_MARK_PRICE_UNKNOWN')),{'code':'VENUE_MARK_PRICE_UNKNOWN'})
        self.assertEqual(safe_diagnostic(RuntimeError(pair().api_key)),{'code':'RETAINED_GET_DIAGNOSTIC_UNAVAILABLE'})
        self.assertEqual(safe_diagnostic(LiveError('secret '+pair().api_key)),{'code':'RETAINED_GET_DIAGNOSTIC_UNAVAILABLE'})
        result = safe_diagnostic(LiveHTTPError('LIVE_PROVIDER_REJECTED',http_status=400,provider_code=-2043))
        self.assertEqual(result['provider_code'],-2043)

    def actual_spot_filters(self):
        self.rows[-1] = {'filterType':'NOTIONAL','minNotional':'5','maxNotional':'9000000',
            'applyMinToMarket':True,'applyMaxToMarket':False,'avgPriceMins':5}
        self.rows += [
            {'filterType':'PERCENT_PRICE_BY_SIDE','bidMultiplierDown':'0.5','bidMultiplierUp':'1.2',
             'askMultiplierDown':'0.8','askMultiplierUp':'2','avgPriceMins':5},
            {'filterType':'MAX_NUM_ORDERS','maxNumOrders':200},
            {'filterType':'MAX_NUM_ORDER_LISTS','maxNumOrderLists':20},
            {'filterType':'MAX_NUM_ALGO_ORDERS','maxNumAlgoOrders':5},
            {'filterType':'MAX_NUM_ORDER_AMENDS','maxNumOrderAmends':10},
            {'filterType':'ICEBERG_PARTS','limit':10},
            {'filterType':'TRAILING_DELTA','minTrailingAboveDelta':10,'maxTrailingAboveDelta':2000,
             'minTrailingBelowDelta':10,'maxTrailingBelowDelta':2000}]

    def test_live_spot_metadata_filters_resolve_from_references_and_current_counts(self):
        self.actual_spot_filters()
        self.reference = {'referencePrice':None}
        self.average = {'mins':5}
        self.assertTrue(self.reader.validate(self.plan, NOW))
        summary = self.reader.summary(self.reader.capture('SPOT_LIVE','BTCUSDT'))
        self.assertEqual(summary['reasons'], [])
        self.assertTrue(summary['current_order_counts_observed'])
        self.assertIn('MAX_NUM_ORDER_AMENDS', summary['nonapplicable_filters'])

    def test_reference_price_overrides_average_and_percent_side_is_exact(self):
        self.actual_spot_filters()
        self.average = {'mins':999,'price':'1000000'}
        self.assertTrue(self.reader.validate(self.plan, NOW))
        self.assertFalse(any(r['endpoint'] == '/api/v3/avgPrice' for r in self.receipts))
        by_side = next(r for r in self.rows if r['filterType'] == 'PERCENT_PRICE_BY_SIDE')
        by_side['askMultiplierUp'] = '1.05'
        self.assertFalse(self.reader.validate(self.plan, NOW))

    def test_confirmed_no_reference_code_falls_back_to_matching_fresh_average_only(self):
        self.actual_spot_filters()
        self.average = {'mins':5}
        original = self.get
        def no_reference(env, endpoint, params=None):
            if endpoint == '/api/v3/referencePrice':
                raise LiveHTTPError('LIVE_HTTP_UNAVAILABLE', http_status=400, provider_code=-2043)
            return original(env, endpoint, params)
        with patch.object(self.transport, 'get', side_effect=no_reference):
            self.assertTrue(self.reader.validate(self.plan, NOW))
            self.assertTrue(any(r.get('error',{}).get('provider_code') == -2043 for r in self.receipts))
            self.average['mins'] = 1
            self.assertFalse(self.reader.validate(self.plan, NOW))
            self.average.update(mins=5, closeTime=int((NOW-31)*1000))
            with self.assertRaisesRegex(LiveError,'STALE_OR_FUTURE'):
                self.reader.validate(self.plan, NOW)
        with patch.object(self.transport, 'get', side_effect=LiveHTTPError('LIVE_HTTP_UNAVAILABLE', http_status=400, provider_code=-1121)):
            with self.assertRaises(LiveHTTPError):
                self.reader.capture('SPOT_LIVE','BTCUSDT')

    def test_order_headroom_and_base_inventory_use_actual_account_rows(self):
        self.actual_spot_filters()
        self.orders = [{'orderId':i,'symbol':'BTCUSDT','type':'LIMIT'} for i in range(198)]
        self.assertFalse(self.reader.validate(self.plan, NOW))
        self.orders = []
        self.order_lists = [{'orderListId':i,'symbol':'BTCUSDT'} for i in range(20)]
        self.assertFalse(self.reader.validate(self.plan, NOW))
        self.order_lists = []
        self.orders = [{'orderId':i,'symbol':'BTCUSDT','type':'STOP_LOSS_LIMIT'} for i in range(5)]
        self.assertFalse(self.reader.validate(self.plan, NOW))
        self.orders = []
        self.rows.append({'filterType':'MAX_POSITION','maxPosition':'0.5'})
        self.assertFalse(self.reader.validate(self.plan, NOW))

    def test_execution_range_applies_only_when_actual_reference_is_non_null(self):
        original = self.get
        def restricted(env, endpoint, params=None):
            if endpoint == '/api/v3/executionRules':
                return {'symbolRules':[{'symbol':'BTCUSDT','rules':[{'ruleType':'PRICE_RANGE','askLimitMultUp':'1.05'}]}]}
            return original(env, endpoint, params)
        with patch.object(self.transport, 'get', side_effect=restricted):
            self.assertFalse(self.reader.validate(self.plan, NOW))
            self.reference = {'referencePrice':None}
            self.assertTrue(self.reader.validate(self.plan, NOW))

    def future_get(self, environment, endpoint, params=None):
        self.assertEqual(environment, 'FUTURES_LIVE')
        if endpoint.endswith('/time'):
            return {'serverTime':int(self.fixture.clock()*1000)}
        if endpoint.endswith('/exchangeInfo'):
            return {'exchangeFilters':[], 'symbols':[{'symbol':'BTCUSDT','status':'TRADING','quoteAsset':'USDT',
                'orderTypes':['MARKET','STOP_MARKET','TAKE_PROFIT_MARKET'], 'filters':[
                    *self.rows[:3], {'filterType':'MIN_NOTIONAL','notional':'50'},
                    {'filterType':'PERCENT_PRICE','multiplierDown':'0.97','multiplierUp':'1.03','multiplierDecimal':4},
                    {'filterType':'MAX_NUM_ORDERS','limit':200}, *getattr(self, 'future_extra', [])]}]}
        if endpoint.endswith('/depth'):
            return {'lastUpdateId':1,'bids':[['99.99','10']],'asks':[['100','10']]}
        if endpoint.endswith('/commissionRate'):
            return {'symbol':'BTCUSDT','makerCommissionRate':'0.0002','takerCommissionRate':'0.0004'}
        if endpoint.endswith('/symbolConfig'):
            return [{'symbol':'BTCUSDT','leverage':1,'marginType':'ISOLATED','maxNotionalValue':'100000',
                **getattr(self, 'future_config', {})}]
        if endpoint.endswith('/positionSide/dual'):
            return {'dualSidePosition':False}
        if endpoint.endswith('/openOrders') or endpoint.endswith('/openAlgoOrders') or endpoint.endswith('/positionRisk'):
            return []
        if endpoint.endswith('/premiumIndex'):
            return {'symbol':'BTCUSDT','markPrice':'100','indexPrice':'100','time':int(self.fixture.clock()*1000)}
        if endpoint.endswith('/leverageBracket'):
            return [{'symbol':'BTCUSDT','brackets':[{'initialLeverage':20,'notionalFloor':0,'notionalCap':100000}]}]
        raise AssertionError(endpoint)

    def test_futures_mark_brackets_and_counts_resolve_but_invalid_configuration_is_not_changed(self):
        transport = LiveReadOnlyTransport({'FUTURES_LIVE':pair()}, clock=self.fixture.clock)
        reader = LiveVenueReader(transport, retain=self.reader.retain, clock=self.fixture.clock)
        plan = self.fixture.prepare()
        with patch.object(transport,'get',side_effect=self.future_get):
            self.assertTrue(reader.validate(plan,NOW))
            self.future_config = {'marginType':'CROSSED','leverage':20}
            cut = reader.capture('FUTURES_LIVE','BTCUSDT')
            self.assertIn('EXISTING_ISOLATED_ONE_WAY_REQUIRED',cut['reasons'])
            self.assertFalse(reader.validate(plan,NOW))
            self.assertEqual(self.future_config,{'marginType':'CROSSED','leverage':20})

    def test_undocumented_position_risk_enum_is_named_and_never_assumed_permission(self):
        transport = LiveReadOnlyTransport({'FUTURES_LIVE':pair()}, clock=self.fixture.clock)
        reader = LiveVenueReader(transport, retain=self.reader.retain, clock=self.fixture.clock)
        self.future_extra = [{'filterType':'POSITION_RISK_CONTROL','positionControlSide':'NONE'}]
        with patch.object(transport,'get',side_effect=self.future_get):
            cut = reader.capture('FUTURES_LIVE','BTCUSDT')
            self.assertIn('POSITION_RISK_CONTROL_SEMANTICS_UNCONFIRMED',cut['reasons'])
            self.assertNotIn('UNKNOWN_ACTIVE_SYMBOL_FILTER',cut['reasons'])
            self.assertFalse(reader.validate(self.fixture.prepare(),NOW))

    def test_advertised_venue_tier_does_not_raise_approved_leverage(self):
        transport = LiveReadOnlyTransport({'FUTURES_LIVE':pair()},clock=self.fixture.clock)
        reader = LiveVenueReader(transport,retain=self.reader.retain,clock=self.fixture.clock)
        def tier(env,endpoint,params=None):
            if endpoint.endswith('/leverageBracket'):
                return [{'symbol':'BTCUSDT','brackets':[{'initialLeverage':150,'notionalFloor':0,'notionalCap':100000}]}]
            return self.future_get(env,endpoint,params)
        with patch.object(transport,'get',side_effect=tier):
            self.assertTrue(reader.validate(self.fixture.prepare(),NOW))
            self.future_config = {'leverage':3}
            self.assertFalse(reader.validate(self.fixture.prepare(),NOW))

    def reduction_position(self, *, scope=None, direction='LONG'):
        return ConfirmedPosition('SYNTHETIC-REDUCTION', scope or self.plan.proposal.scope,
            'BTCUSDT', direction, '1', '100', '1', '100', NOW, 'a'*64, True, 'ENTRY-OWNED')

    def reduction_intent(self, position, quantity='0.5'):
        fields = {'symbol':'BTCUSDT','side':'SELL' if position.direction == 'LONG' else 'BUY',
            'type':'MARKET','quantity':quantity,'newClientOrderId':'CLOSE-OWNED'}
        if position.scope.environment == 'FUTURES_LIVE':
            fields.update(positionSide='BOTH',reduceOnly='true')
        return LiveOrderIntent(position.scope.environment,'CLOSE','POST',
            '/api/v3/order' if position.scope.environment == 'SPOT_LIVE' else '/fapi/v1/order',
            tuple(sorted(fields.items())),'CLOSE-OWNED',self.plan.intent.policy_digest,int((NOW+30)*1000))

    def reduction_get(self, env, endpoint, params=None):
        if endpoint == '/api/v3/account':
            return {'balances':[{'asset':'BTC','free':getattr(self,'free_base','0.5'),
                'locked':getattr(self,'locked_base','0.5')}]}
        result = self.get(env,endpoint,params)
        if endpoint == '/api/v3/account/commission':
            result['discount'] = {'enabledForAccount':True,'enabledForSymbol':True,
                'discountAsset':getattr(self,'discount_asset','BNB'),'discount':'0.25'}
        return result

    def test_market_reduction_checks_actual_free_owned_inventory_and_base_fee_asset(self):
        position = self.reduction_position()
        intent = self.reduction_intent(position)
        with patch.object(self.transport,'get',side_effect=self.reduction_get):
            self.assertTrue(self.reader.validate_reduction(intent,position,NOW))
            self.discount_asset = 'BTC'
            self.assertFalse(self.reader.validate_reduction(intent,position,NOW))
            self.discount_asset = 'BNB'
            self.free_base,self.locked_base = '0.49','0.51'
            self.assertFalse(self.reader.validate_reduction(intent,position,NOW))
            self.free_base,self.locked_base = '1','0.5'
            self.assertFalse(self.reader.validate_reduction(intent,position,NOW))

    def test_reduction_never_rounds_up_residual_or_accepts_expired_or_unknown_fee_terms(self):
        position = self.reduction_position()
        with patch.object(self.transport,'get',side_effect=self.reduction_get):
            self.assertFalse(self.reader.validate_reduction(self.reduction_intent(position,'0.5001'),position,NOW))
            self.assertFalse(self.reader.validate_reduction(self.reduction_intent(position,'1.001'),position,NOW))
            self.assertFalse(self.reader.validate_reduction(self.reduction_intent(position,'0.01'),position,NOW))
            self.assertFalse(self.reader.validate_reduction(self.reduction_intent(position),replace(position,observed_at=NOW-31),NOW))
            self.assertFalse(self.reader.validate_reduction(replace(self.reduction_intent(position),expires_utc_ms=int(NOW*1000)),position,NOW))
        with patch.object(self.transport,'get',side_effect=self.get):
            self.assertFalse(self.reader.validate_reduction(self.reduction_intent(position),position,NOW))

    def test_futures_reduction_requires_exact_signed_position_without_new_entry(self):
        plan = self.fixture.prepare()
        position = self.reduction_position(scope=plan.proposal.scope)
        transport = LiveReadOnlyTransport({'FUTURES_LIVE':pair()},clock=self.fixture.clock)
        reader = LiveVenueReader(transport,retain=self.reader.retain,clock=self.fixture.clock)
        def future(env,endpoint,params=None):
            if endpoint.endswith('/positionRisk'):
                return [{'symbol':'BTCUSDT','positionSide':'BOTH','positionAmt':getattr(self,'signed_position','1')}]
            return self.future_get(env,endpoint,params)
        with patch.object(transport,'get',side_effect=future):
            self.assertTrue(reader.validate_reduction(self.reduction_intent(position),position,NOW))
            self.signed_position = '-1'
            self.assertFalse(reader.validate_reduction(self.reduction_intent(position),position,NOW))
            short = replace(position,direction='SHORT')
            self.assertTrue(reader.validate_reduction(self.reduction_intent(short),short,NOW))
            self.signed_position = '-0.9'
            self.assertFalse(reader.validate_reduction(self.reduction_intent(short),short,NOW))


if __name__ == '__main__':
    unittest.main()
