import unittest
from copy import deepcopy
from unittest.mock import patch
from trader.exchange import BinanceClient, ExchangeError
from trader.native_protection import SpotNativeProtection, projection
from trader.testnet_transport import TestnetExecutionError


INFO = {'symbol':'GNSUSDT','ocoAllowed':True,'orderTypes':['STOP_LOSS','TAKE_PROFIT'],
        'filters':[{'filterType':'PRICE_FILTER','minPrice':'0.001','maxPrice':'1000','tickSize':'0.001'},
                   {'filterType':'PERCENT_PRICE_BY_SIDE','avgPriceMins':5,'askMultiplierDown':'0.8',
                    'askMultiplierUp':'2','bidMultiplierDown':'0.5','bidMultiplierUp':'1.2'}]}


class PercentProtectionTests(unittest.TestCase):
    def test_real_gns_rejection_is_detected_before_any_order(self):
        with self.assertRaisesRegex(TestnetExecutionError,'outside percent price filter'):
            SpotNativeProtection.preflight(INFO,.5230868728958509,.915753526935571,references={5:'.662'})

    def test_rounded_sell_band_uses_ask_multipliers_and_preserves_levels(self):
        self.assertEqual(SpotNativeProtection.preflight(INFO,.5230868728958509,.915753526935571,
                         references={5:'.5885'}),('0.524','0.916'))

    def test_upper_band_and_general_percent_filter_are_also_enforced(self):
        info=deepcopy(INFO)
        info['filters'][1]={'filterType':'PERCENT_PRICE','avgPriceMins':5,'multiplierDown':'.8','multiplierUp':'1.2'}
        with self.assertRaisesRegex(TestnetExecutionError,'outside percent price filter'):
            SpotNativeProtection.preflight(info,.56,.916,references={5:'.5885'})

    def test_unknown_reference_cannot_pass(self):
        for refs in (None,{}, {5:'NaN'},{5:'0'}):
            with self.subTest(refs=refs),self.assertRaises(TestnetExecutionError):
                SpotNativeProtection.preflight(INFO,.56,.916,references=refs)

    def test_exchange_reference_overrides_vwap_without_changing_data_host(self):
        c=BinanceClient(); original=c.base_url
        def request(method,path,params):
            self.assertEqual(c.base_url,'https://testnet.binance.vision')
            self.assertEqual((method,path),('GET','/api/v3/referencePrice'))
            return {'symbol':'GNSUSDT','referencePrice':'.5885'}
        with patch.object(c,'_request',side_effect=request) as read:
            self.assertEqual(c.testnet_percent_price_references('GNSUSDT',INFO['filters'][1:]),{5:'.5885'})
        self.assertEqual(read.call_count,1);self.assertEqual(c.base_url,original)

    def test_null_reference_requires_exact_average_window(self):
        c=BinanceClient(); original=c.base_url
        with patch.object(c,'_request',side_effect=[{'symbol':'GNSUSDT','referencePrice':None},
                                                   {'mins':5,'price':'.5884'}]):
            self.assertEqual(c.testnet_percent_price_references('GNSUSDT',INFO['filters'][1:]),{5:'.5884'})
        with patch.object(c,'_request',side_effect=[{'symbol':'GNSUSDT','referencePrice':None},
                                                   {'mins':1,'price':'.5884'}]):
            with self.assertRaises(ExchangeError):c.testnet_percent_price_references('GNSUSDT',INFO['filters'][1:])
        self.assertEqual(c.base_url,original)

    def test_blocked_and_uncertain_quantities_are_not_reported_as_protected(self):
        for status in ('BLOCKED','UNCONFIRMED','INSTALLING','CANCELING'):
            view=projection({'GNSUSDT':{'status':status,'position':{'quantity':24.86},'quantity':'24.86'}})
            self.assertEqual(view['positions']['GNSUSDT']['unprotected_quantity'],24.86)
        view=projection({'GNSUSDT':{'status':'ARMED','position':{'quantity':24.86},'quantity':'24.86'}})
        self.assertEqual(view['positions']['GNSUSDT']['unprotected_quantity'],0)
