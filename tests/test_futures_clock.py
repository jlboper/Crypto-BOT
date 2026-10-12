import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from trader import futures_testnet_transport as transport


class FuturesClockTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(transport, '_clock_sample', None)
        clock.start()
        self.addCleanup(clock.stop)
        credentials = patch.dict('os.environ', {
            'BINANCE_FUTURES_TESTNET_API_KEY': 'synthetic-key',
            'BINANCE_FUTURES_TESTNET_API_SECRET': 'synthetic-secret',
        })
        credentials.start()
        self.addCleanup(credentials.stop)

    @staticmethod
    def error(code):
        return HTTPError('https://synthetic.invalid', 400, 'synthetic', {},
                         io.BytesIO(json.dumps({'code': code, 'msg': 'synthetic'}).encode()))

    def test_clock_uses_demo_time_and_monotonic_elapsed_despite_local_jump(self):
        with patch.object(transport, 'public_request', return_value={'serverTime': 100000}) as public, \
             patch.object(transport.time, 'monotonic', side_effect=[10, 10, 10.2, 12.2]), \
             patch.object(transport.time, 'time', side_effect=AssertionError('No local clock')):
            first = transport._request_timestamp()
            second = transport._request_timestamp()
        self.assertEqual(first, 100000)
        self.assertAlmostEqual(second, 102000, delta=1)
        public.assert_called_once_with('GET', '/fapi/v1/time', allow_fallback=False)

    def test_clock_refreshes_after_five_minutes(self):
        transport._clock_sample = (100000, 1)
        with patch.object(transport, 'public_request', return_value={'serverTime': 500000}) as public, \
             patch.object(transport.time, 'monotonic', side_effect=[302, 302, 302.1]):
            self.assertEqual(transport._request_timestamp(), 500000)
        self.assertEqual(public.call_count, 1)

    def test_invalid_or_slow_clock_blocks_signed_request_before_sending(self):
        for payload, elapsed in (({}, .1), ({'serverTime': True}, .1),
                                 ({'serverTime': 100000}, 2.1)):
            with self.subTest(payload=payload, elapsed=elapsed), \
                 patch.object(transport, '_clock_sample', None), \
                 patch.object(transport, 'public_request', return_value=payload), \
                 patch.object(transport.time, 'monotonic', side_effect=[1, 1, 1 + elapsed]), \
                 patch.object(transport, '_signed_opener') as signed:
                with self.assertRaises(transport.FuturesTestnetExecutionError):
                    transport.signed_request('GET', '/fapi/v3/account')
                signed.assert_not_called()

    def test_timestamp_rejection_resynchronizes_and_retries_get_once(self):
        opener = Mock()
        opener.open.side_effect = [self.error(-1021), io.BytesIO(b'{"canTrade":true}')]
        with patch.object(transport, 'public_request', side_effect=[{'serverTime': 100000}, {'serverTime': 200000}]) as public, \
             patch.object(transport.time, 'monotonic', return_value=1), \
             patch.object(transport, '_signed_opener', return_value=opener):
            self.assertEqual(transport.signed_request('GET', '/fapi/v3/account'), {'canTrade': True})
        self.assertEqual(public.call_count, 2)
        self.assertEqual(opener.open.call_count, 2)
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual([parse_qs(urlsplit(r.full_url).query)['timestamp'][0] for r in requests], ['100000', '200000'])
        self.assertTrue(all(urlsplit(r.full_url).hostname == 'testnet.binancefuture.com' for r in requests))

    def test_timestamp_retry_is_bounded_and_writes_are_never_retried(self):
        for method, endpoint, calls in (('GET', '/fapi/v3/account', 2),
                                        ('POST', '/fapi/v1/order', 1),
                                        ('DELETE', '/fapi/v1/algoOrder', 1)):
            opener = Mock()
            opener.open.side_effect = [self.error(-1021), self.error(-1021)]
            with self.subTest(method=method), patch.object(transport, '_clock_sample', None), \
                 patch.object(transport, 'public_request', return_value={'serverTime': 100000}), \
                 patch.object(transport.time, 'monotonic', return_value=1), \
                 patch.object(transport, '_signed_opener', return_value=opener):
                with self.assertRaises(transport.FuturesTestnetExecutionError) as raised:
                    transport.signed_request(method, endpoint)
            self.assertEqual(raised.exception.code, -1021)
            self.assertEqual(opener.open.call_count, calls)
            self.assertIsNone(transport._clock_sample)

    def test_non_timestamp_error_is_not_retried(self):
        opener = Mock()
        opener.open.side_effect = self.error(-1007)
        with patch.object(transport, '_request_timestamp', return_value=100000), \
             patch.object(transport, '_signed_opener', return_value=opener):
            with self.assertRaises(transport.FuturesTestnetExecutionError) as raised:
                transport.signed_request('GET', '/fapi/v3/account')
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(opener.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
