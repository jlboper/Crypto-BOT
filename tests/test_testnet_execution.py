import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trader.testnet_execution import execute, public_status, TestnetExecutionError, _signed
from trader.operational_controls import _model_file


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.info = {'symbol': 'BTCUSDT', 'filters': [
            {'filterType':'LOT_SIZE','minQty':'0.001','maxQty':'10','stepSize':'0.001'},
            {'filterType':'MIN_NOTIONAL','minNotional':'10','applyToMarket':True}]}
        self.config = SimpleNamespace(bot=SimpleNamespace(mode='paper',
            database_path=self.source/'data/trader.db'))

    def test_testnet_order_is_journaled_before_one_post_and_never_retried(self):
        calls=[]
        def request(method, endpoint, fields):
            calls.append((method,endpoint,fields))
            if endpoint == '/api/v3/account':
                return {'balances':[{'asset':'USDT','free':'1000'}]}
            if method == 'POST':
                rows=json.loads((self.source/'data/testnet-execution.json').read_text())['orders']
                self.assertEqual(rows[-1]['status'],'UNCERTAIN')
                self.assertEqual(fields['quoteOrderQty'],'25')
                raise TestnetExecutionError('Response uncertain')
            return {'symbol':'BTCUSDT','clientOrderId':fields['origClientOrderId'],
                    'side':'BUY','status':'FILLED','executedQty':'0.24','cummulativeQuoteQty':'24'}
        with patch('trader.config.load_config',return_value=self.config), \
             patch('trader.testnet_execution.BinanceClient') as client, \
             patch('trader.testnet_execution._signed',side_effect=request):
            client.return_value.testnet_symbol_info.return_value=self.info
            client.return_value.testnet_reference_price.return_value=100.
            with self.assertRaises(TestnetExecutionError):
                execute(self.source,'testnet_buy',{})
            with self.assertRaisesRegex(TestnetExecutionError,'Unresolved'):
                execute(self.source,'testnet_buy',{})
            self.assertEqual(sum(method=='POST' for method,_,_ in calls),1)
            result=execute(self.source,'testnet_reconcile',{})
            self.assertEqual(result['status'],'FILLED')
            self.assertEqual(public_status(self.source)['orders'][-1]['executed_qty'],'0.24')

    def test_model_file_preserves_existing_local_secrets(self):
        path=self.source/'.env.local'
        path.write_text('OPENAI_API_KEY=secret\nBINANCE_API_SECRET=private\nOPENAI_MODEL=gpt-5.6-luna\n')
        _model_file(self.source,'gpt-6-luna')
        lines=path.read_text().splitlines()
        self.assertEqual(lines.count('OPENAI_MODEL=gpt-6-luna'),1)
        self.assertIn('BINANCE_API_SECRET=private',lines)
        self.assertIn('OPENAI_API_KEY=secret',lines)

    def test_signed_transport_rejects_any_production_or_extra_route(self):
        with patch.dict('os.environ',{'BINANCE_API_KEY':'test','BINANCE_API_SECRET':'secret'}), \
             patch('urllib.request.build_opener') as opener:
            with self.assertRaises(TestnetExecutionError):
                _signed('POST','https://api.binance.com/api/v3/order',{})
            opener.assert_not_called()
            class Response:
                def __enter__(self):return self
                def __exit__(self,*_):return False
                def read(self,*_):return b'{"ok":true}'
            opener.return_value.open.return_value=Response()
            self.assertEqual(_signed('POST','/api/v3/order',{'symbol':'BTCUSDT'})['ok'],True)
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'https://testnet.binance.vision/api/v3/order')

    def test_only_testnet_position_can_be_closed_after_confirmed_fill(self):
        sent=[]
        def request(method, endpoint, fields):
            if endpoint == '/api/v3/account':
                return {'balances':[{'asset':'USDT','free':'1000'},{'asset':'BTC','free':'0.24'}]}
            self.assertEqual((method, endpoint),('POST','/api/v3/order'))
            sent.append(fields)
            return {'symbol':'BTCUSDT','clientOrderId':fields['newClientOrderId'],
                    'side':fields['side'],'status':'FILLED',
                    'executedQty':'0.24','cummulativeQuoteQty':'24'}
        with patch('trader.config.load_config',return_value=self.config), \
             patch('trader.testnet_execution.BinanceClient') as client, \
             patch('trader.testnet_execution._signed',side_effect=request):
            client.return_value.testnet_symbol_info.return_value=self.info
            client.return_value.testnet_reference_price.return_value=100.
            with self.assertRaisesRegex(TestnetExecutionError,'No reconciled'):
                execute(self.source,'testnet_close',{})
            self.assertEqual(execute(self.source,'testnet_buy',{})['status'],'FILLED')
            self.assertEqual(execute(self.source,'testnet_close',{})['status'],'FILLED')
            self.assertEqual(sent[0]['quoteOrderQty'],'25')
            self.assertEqual(sent[1]['quantity'],'0.24')
            with self.assertRaisesRegex(TestnetExecutionError,'per UTC day'):
                execute(self.source,'testnet_buy',{})


if __name__=='__main__':
    unittest.main()
