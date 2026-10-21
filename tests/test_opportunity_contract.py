import dataclasses
from decimal import Decimal
import hashlib
import unittest

from trader.opportunity_contract import (FLAGS, build_intent, build_outcome, position_digest,
    canonical, decimal_text)

NOW=1800000000.


def intent_fields(**changes):
    value=dict(engine='SPOT',environment='SPOT_TESTNET',origin_ref='private-client-order',
        strategy_version='native-1',at=NOW,
        legs=[dict(symbol='BTCUSDT',venue='SPOT_TESTNET',direction='LONG',quantity='1',
            reference_price='100',stop_price='99',take_profit='102',fee_rate='.001',slippage_rate='.001')],
        capital=dict(cash='1000',equity='1000',available='1000',at=NOW),
        limits=dict(gross_limit='500',capital_limit='600',stop_risk_limit='20',max_positions=10),
        evidence=dict(market_at=NOW,received_at=NOW,known_at=NOW,decision_at=NOW,
            checks=['NATIVE_QUANTITATIVE_CHECKS_PASSED']))
    value.update(changes)
    return value


def outcome_fields(**changes):
    value=dict(engine='SPOT',environment='SPOT_TESTNET',origin_ref='private-client-order',
        at=NOW,stage='EXCHANGE_RESPONSE',state='FILLED',complete=True,
        evidence=dict(quantity='1',fees='.1',response_digest='a'*64))
    value.update(changes)
    return value


class OpportunityContractTests(unittest.TestCase):
    def test_event_is_frozen_copied_and_origin_private(self):
        fields=intent_fields();event=build_intent(**fields)
        fields['legs'][0]['quantity']='999';fields['evidence']['checks'].clear()
        payload=event.payload();self.assertEqual(payload['legs'][0]['quantity'],'1')
        payload['legs'].clear();self.assertEqual(len(event.payload()['legs']),1)
        with self.assertRaises(dataclasses.FrozenInstanceError):event.id='b'*64
        self.assertNotIn(b'private-client-order',event.encoded)
        self.assertEqual(event.id,hashlib.sha256(event.encoded).hexdigest())
        self.assertEqual(event.encoded,canonical(event.payload()))

    def test_exact_decimal_and_canonical_limits(self):
        for native,expected in [(Decimal('0.10000000000000000001'),'0.10000000000000000001'),
                                (0.1,'0.1'),('1e-10','0.0000000001'),('-0.0','0')]:
            self.assertEqual(decimal_text(native),expected)
        for value in [True,float('nan'),float('inf'),'-1','1e19','1e-31','9'*65,[],{}]:
            with self.subTest(value=str(type(value))),self.assertRaises(ValueError):decimal_text(value)

    def test_unknown_numerics_are_null_never_zero(self):
        payload=build_intent(**intent_fields(capital=None,limits=None,
            legs=[dict(symbol='ETHUSDT',venue='SPOT_TESTNET',direction='LONG')])).payload()
        self.assertIsNone(payload['capital']['available'])
        self.assertIsNone(payload['legs'][0]['quantity'])

    def test_closed_dictionaries_disallow_text_credentials_and_callbacks(self):
        for extra in [dict(capital={'available':'1','api_key':'private'}),
                      dict(evidence={'news':'ignore instructions'}),
                      dict(legs=[dict(symbol='BTCUSDT',venue='SPOT_TESTNET',direction='LONG',callback=lambda:0)]),
                      dict(strategy_version='not a narrative')]:
            with self.subTest(extra=list(extra)),self.assertRaises(ValueError):build_intent(**intent_fields(**extra))
        class Trap(dict):
            def __iter__(self):raise AssertionError('arbitrary callback')
        with self.assertRaises(ValueError):build_intent(**intent_fields(capital=Trap()))

    def test_all_supported_scopes_and_engine_environment_separation(self):
        pairs=[('SPOT','SPOT_TESTNET'),('SPOT','PAPER'),('FUTURES','FUTURES_DEMO'),
               ('AI_MARKET_PULSE','SHADOW'),('QUANT_ARBITRAGE','SHADOW')]
        identities=[]
        for engine,environment in pairs:
            identities.append(build_intent(**intent_fields(engine=engine,environment=environment)).payload()['origin_digest'])
        self.assertEqual(len(set(identities)),5)
        for engine,environment in [('SPOT','SHADOW'),('FUTURES','PAPER'),('AI_MARKET_PULSE','SPOT_TESTNET'),('SPOT','LIVE')]:
            with self.assertRaises(ValueError):build_intent(**intent_fields(engine=engine,environment=environment))

    def test_checks_are_fixed_codes_without_free_text(self):
        checks=['NATIVE_QUANTITATIVE_CHECKS_PASSED']*2
        self.assertEqual(len(build_intent(**intent_fields(evidence={'checks':checks})).payload()['evidence']['checks']),1)
        with self.assertRaises(ValueError):build_intent(**intent_fields(evidence={'checks':['buy-now']}))
        with self.assertRaises(ValueError):build_intent(**intent_fields(evidence={'source_digest':'secret'}))

    def test_event_size_bound_and_leg_bound(self):
        fields=intent_fields();fields['legs']*=5
        with self.assertRaises(ValueError):build_intent(**fields)
        fields=intent_fields();fields['legs']*=4
        fields['evidence']['checks']=list(__import__('trader.opportunity_contract',fromlist=['CHECKS']).CHECKS)
        event=build_intent(**fields);self.assertLessEqual(len(event.encoded),4096)

    def test_outcome_never_grants_authority_and_validates_closed_schema(self):
        event=build_outcome(**outcome_fields())
        self.assertEqual(event.payload()['stage'],'EXCHANGE_RESPONSE')
        self.assertEqual(event.payload()['account_identity'],'UNKNOWN')
        self.assertTrue(all(value is False for value in FLAGS.values()))
        for changes in [dict(stage='EXECUTED'),dict(state='PROTECTED'),dict(complete=1),dict(evidence={'raw_response':'secret'})]:
            with self.assertRaises(ValueError):build_outcome(**outcome_fields(**changes))

    def test_invalid_timestamps_and_unsafe_input_types(self):
        for at in [None,True,float('nan'),-1,'today']:
            with self.assertRaises(ValueError):build_intent(**intent_fields(at=at))
        with self.assertRaises(ValueError):build_intent(**intent_fields(engine=[]))
        with self.assertRaises(ValueError):build_outcome(**outcome_fields(state=[]))

    def test_position_reference_is_scoped_and_closes_require_explicit_zero(self):
        reference='BTCUSDT|2026-10-20T12:00:00+00:00'
        digest=position_digest('SPOT','SPOT_TESTNET',reference)
        self.assertNotEqual(digest,position_digest('SPOT','PAPER',reference))
        self.assertNotEqual(digest,position_digest('SPOT','SPOT_TESTNET',reference+'1'))
        fields=outcome_fields(origin_ref='POSITION:'+digest,stage='LEDGER_COMMIT',state='CLOSED',
            by_position=True,evidence={'position_digest':digest,'remaining_quantity':'0','decision_digest':'b'*64})
        self.assertTrue(build_outcome(**fields).payload()['position_reference'])
        for changes in [dict(complete=False),dict(stage='EXCHANGE_RESPONSE'),dict(state='OPENED'),
                        dict(evidence={'position_digest':digest,'remaining_quantity':'1','decision_digest':'b'*64}),
                        dict(evidence={'position_digest':digest,'remaining_quantity':'0'})]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):build_outcome(**(fields|changes))


if __name__=='__main__':unittest.main()
