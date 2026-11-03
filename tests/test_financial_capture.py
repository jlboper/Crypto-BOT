"""Synthetic encrypted capture, source pagination, accounting and recovery."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from trader.financial_capture import (DAY, FinancialCapture, FinancialCaptureService,
    FinancialHistoryCapture, DailySnapshotCapture, normalize_daily_snapshots,
    reconcile_sources, reconcile_daily_pairs, EarnSourceCapture)
from trader.live_transport import (LiveReadOnlyTransport, LiveCredentials, LiveError, LiveHTTPError,
    SPOT_TRANSFER_TYPES, KEY_SNAPSHOT_ENDPOINT)

NOW = 1800000000.0
END = int(NOW*1000)-1000
START = END-1000


def cipher(raw):
    return bytes(x ^ 0xA5 for x in raw)


def pair(key='a'):
    return LiveCredentials(key*64, 'b'*64)


def trade(identity=1, stamp=START+100, **changes):
    return {'id': identity, 'orderId': 8, 'symbol': 'BTCUSDT', 'time': stamp,
            'qty': '0.01', 'quoteQty': '10', 'commission': '0.001',
            'commissionAsset': 'USDT', 'isBuyer': True, **changes}


def stream(scope, kind, rows=(), done=True, params=None):
    return {'scope': scope, 'kind': kind, 'records': {str(i): r for i, r in enumerate(rows)},
            'done': done, 'params': params or {}, 'coverage_start_ms': START, 'coverage_end_ms': END}


def spot(usdt, btc='0'):
    return {'balances': [{'asset': 'USDT', 'free': usdt, 'locked': '0'},
                         {'asset': 'BTC', 'free': btc, 'locked': '0'}]}


def fut(usdt):
    return {'assets': [{'asset': 'USDT', 'walletBalance': usdt}]}


def spot_streams(fills=()):
    return [stream('SPOT_LIVE', 'trades', fills, params={'symbol': 'BTCUSDT'}),
            stream('SPOT_LIVE', 'deposits'), stream('SPOT_LIVE', 'withdrawals')] + [
            stream('SPOT_LIVE', 'transfers', params={'type': kind}) for kind in sorted(SPOT_TRANSFER_TYPES)]


class FinancialCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'capture'
        self.transport = LiveReadOnlyTransport({'SPOT_LIVE': pair()}, clock=lambda: NOW)

    def job(self, **changes):
        return FinancialCapture(self.transport, self.directory, symbols=['BTCUSDT'],
            start_utc_ms=START, end_utc_ms=END, clock=lambda: NOW,
            protect=cipher, unprotect=cipher, **changes)

    def get(self, scope, endpoint, params=None):
        if endpoint.endswith('/myTrades'):
            return [trade()]
        if endpoint.endswith('/asset/transfer'):
            return {'total': 0}
        if endpoint.endswith('/account'):
            return spot('100')
        return []

    def test_cooperative_stop_retains_first_response_and_does_not_start_next_get(self):
        stopped=[False]
        def get(scope,endpoint,params):
            stopped[0]=True
            return self.get(scope,endpoint,params)
        with patch.object(LiveReadOnlyTransport,'get',side_effect=get) as call:
            result=self.job().run(max_calls=20,should_stop=lambda:stopped[0])
            self.assertEqual(call.call_count,1)
        self.assertEqual(result['state'],'CAPTURE_PENDING')
        self.assertEqual(len(self.job().retained()['originals']),1)
        with patch.object(LiveReadOnlyTransport,'get',side_effect=self.get):
            self.assertEqual(self.job().run(max_calls=40)['state'],'CAPTURED_BOUNDED_WINDOW')

    def test_restart_idempotent_and_no_plaintext_sources(self):
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get) as get:
            self.assertEqual(self.job().run(max_calls=1)['streams_exhausted'], 1)
            second = self.job().run(max_calls=40)
            self.assertEqual(second['state'], 'CAPTURED_BOUNDED_WINDOW')
            calls = get.call_count
            again = self.job().run(max_calls=40)
            self.assertEqual(again['calls_this_run'], 0)
            self.assertEqual(get.call_count, calls)
            self.assertEqual(again['retained_records'], 1)
        raw = (self.directory/'capture.dpapi').read_bytes()
        for private in (b'quoteQty', b'BTCUSDT', b'balances'):
            self.assertNotIn(private, raw)
        self.assertFalse(again['financial_window_complete'])
        self.assertFalse(again['execution_enabled'])

    def test_full_time_pages_split_without_skipping(self):
        rows = [trade(1, START+10), trade(2, START+20), trade(3, START+900)]
        def get(scope, endpoint, params=None):
            if endpoint.endswith('/myTrades'):
                return [r for r in rows if params['startTime'] <= r['time'] <= params['endTime']][:2]
            return self.get(scope, endpoint, params)
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get):
            result = self.job(page_size=2).run(max_calls=60)
        self.assertEqual(result['state'], 'CAPTURED_BOUNDED_WINDOW')
        self.assertEqual(result['retained_records'], 3)

    def test_saturated_millisecond_stays_unknown(self):
        rows = [trade(i, START+10) for i in range(3)]
        def get(scope, endpoint, params=None):
            if endpoint.endswith('/myTrades'):
                return [r for r in rows if params['startTime'] <= r['time'] <= params['endTime']][:2]
            return self.get(scope, endpoint, params)
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get):
            result = self.job(page_size=2).run(max_calls=60)
        self.assertEqual(result['state'], 'CAPTURE_PENDING')
        self.assertIn('CAPTURE_TIMESTAMP_SATURATED', result['reason_codes'])

    def test_bad_first_symbol_does_not_starve_later_sources_across_ticks(self):
        def get(scope, endpoint, params=None):
            if endpoint.endswith('/myTrades'):
                raise LiveError('LIVE_PROVIDER_REJECTED')
            return self.get(scope, endpoint, params)
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get):
            for _ in range(8):
                result = self.job().run(max_calls=2)
        state = self.job().retained()
        self.assertFalse(state['streams'][0]['done'])
        self.assertTrue(all(s['done'] for s in state['streams'][1:]))
        self.assertEqual(result['state'], 'CAPTURE_PENDING')

    def test_malformed_response_retained_before_parser_and_cursor(self):
        def get(scope, endpoint, params=None):
            return [trade(qty='bad')] if endpoint.endswith('/myTrades') else self.get(scope, endpoint, params)
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get):
            result = self.job().run(max_calls=40)
        self.assertIn('INVALID_CAPTURE_AMOUNT', result['reason_codes'])
        state = self.job().retained()
        self.assertEqual(state['streams'][0]['pending'], [[START, END-1]])
        self.assertEqual(state['streams'][0]['records'], {})
        self.assertGreater(len(state['originals']), 1)

    def test_transfer_contradiction_never_partially_commits_records(self):
        def get(scope, endpoint, params=None):
            if endpoint.endswith('/asset/transfer') and params['type'] == 'MAIN_UMFUTURE':
                return {'total': 0, 'rows': [{'asset': 'USDT', 'amount': '1', 'type': 'MAIN_UMFUTURE',
                    'status': 'CONFIRMED', 'tranId': 1, 'timestamp': START+100}]}
            return self.get(scope, endpoint, params)
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get):
            result = self.job().run(max_calls=40)
        self.assertIn('CAPTURE_TRANSFER_TOTAL_CONTRADICTION', result['reason_codes'])
        failed = next(s for s in self.job().retained()['streams'] if s['params'].get('type') == 'MAIN_UMFUTURE')
        self.assertEqual(failed['records'], {})
        self.assertEqual(failed['cursor'], 1)
        self.assertIsNone(failed['total'])

    def test_key_replacement_cannot_rebind_checkpoint(self):
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get):
            self.job().run(max_calls=1)
        self.transport._credentials['SPOT_LIVE'] = pair('c')
        with self.assertRaisesRegex(LiveError, 'CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED'):
            self.job().run(max_calls=1)

    def test_current_snapshot_keeps_actual_receipt_timestamp(self):
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get):
            self.job().run(max_calls=40)
        cut = self.job().retained()['snapshots']['SPOT_LIVE']
        self.assertEqual(cut['received'], int(NOW*1000))
        self.assertNotEqual(cut['received'], END)

    def test_global_rate_limit_stops_all_other_gets_and_retains_closed_failure(self):
        for status in (418,429):
            with self.subTest(status=status), TemporaryDirectory() as directory:
                job = FinancialCapture(self.transport, directory, symbols=['BTCUSDT'], start_utc_ms=START,
                    end_utc_ms=END, clock=lambda:NOW, protect=cipher, unprotect=cipher)
                with patch.object(LiveReadOnlyTransport,'get',side_effect=LiveHTTPError(
                        'LIVE_RATE_LIMITED',http_status=status,provider_code=-1003)) as get:
                    first = job.run(max_calls=40)
                    self.assertEqual(first['state'],'CAPTURE_RATE_LIMITED')
                    self.assertEqual(get.call_count,1)
                    self.assertEqual(job.run(max_calls=40)['calls_this_run'],0)
                    self.assertEqual(get.call_count,1)
                state = job.retained()
                self.assertEqual(state['originals'][0]['failure']['http_status'],status)
                self.assertEqual(state['streams'][0]['records'],{})
                self.assertEqual(state['streams'][0]['pending'],[[START,END-1]])
                self.assertFalse(first['raw_encrypted_retention'])


class FinancialSourceReconciliationTests(unittest.TestCase):
    def test_account_cjk_assets_are_preserved_exactly_without_expanding_symbols(self):
        first = spot('100')
        first['balances'].append({'asset':'牛来','free':'2','locked':'0'})
        result = reconcile_sources('SPOT_LIVE', first, deepcopy(first), spot_streams())
        self.assertEqual(result['asset_differences']['牛来'], '0')
        for asset in ('牛来\n', '../USDT', 'usdt', 'ＵＳＤＴ', 'USDT\u200b'):
            with self.subTest(asset=asset):
                bad=deepcopy(first)
                bad['balances'][-1]['asset']=asset
                with self.assertRaisesRegex(LiveError, 'UNRECOGNIZED_CAPTURE_ASSET'):
                    reconcile_sources('SPOT_LIVE', bad, deepcopy(bad), spot_streams())

    def test_spot_base_fee_and_quote_spend_exact(self):
        result = reconcile_sources('SPOT_LIVE', spot('100'), spot('90', '0.009'),
            spot_streams([trade(commissionAsset='BTC', commission='0.001')]))
        self.assertEqual(result['state'], 'MATCHED_SUPPLIED_CUTS')
        self.assertEqual(result['fees_by_asset'], {'BTC': '0.001'})
        self.assertFalse(result['ledger_reconciled'])

    def test_missing_stream_or_opening_cut_never_matches(self):
        self.assertEqual(reconcile_sources('SPOT_LIVE', spot('100'), spot('100'), [])['state'], 'UNKNOWN')
        self.assertEqual(reconcile_sources('SPOT_LIVE', None, spot('100'), [])['state'], 'UNKNOWN')

    def test_futures_commission_funding_and_transfer_counted_once(self):
        fill = trade(realizedPnl='2', marginAsset='USDT')
        income = [
            {'incomeType': 'COMMISSION', 'tranId': 1, 'symbol': 'BTCUSDT', 'tradeId': '1', 'asset': 'USDT', 'income': '-0.001'},
            {'incomeType': 'REALIZED_PNL', 'tranId': 2, 'symbol': 'BTCUSDT', 'tradeId': '1', 'asset': 'USDT', 'income': '2'},
            {'incomeType': 'FUNDING_FEE', 'tranId': 3, 'symbol': 'BTCUSDT', 'tradeId': '', 'asset': 'USDT', 'income': '-0.1'},
            {'incomeType': 'TRANSFER', 'tranId': 4, 'symbol': '', 'tradeId': '', 'asset': 'USDT', 'income': '10'}]
        rows = [stream('FUTURES_LIVE', 'trades', [fill], params={'symbol': 'BTCUSDT'}), stream('FUTURES_LIVE', 'income', income)]
        result = reconcile_sources('FUTURES_LIVE', fut('100'), fut('111.899'), rows)
        self.assertEqual(result['state'], 'MATCHED_SUPPLIED_CUTS')
        self.assertEqual(result['funding_by_asset'], {'USDT': '-0.1'})
        income[0]['tradeId'] = 'different'
        self.assertIn('TRADE_COMMISSION_INCOME_MISMATCH', reconcile_sources('FUTURES_LIVE', fut('100'), fut('111.899'), rows)['reason_codes'])

    def test_main_funding_transfers_and_other_wallet_deposits_segregated(self):
        rows = spot_streams()
        next(s for s in rows if s['params'].get('type') == 'MAIN_FUNDING')['records'] = {
            '1': {'type': 'MAIN_FUNDING', 'asset': 'USDT', 'amount': '3', 'status': 'CONFIRMED'}}
        next(s for s in rows if s['kind'] == 'deposits')['records'] = {
            '1': {'coin': 'USDT', 'amount': '50', 'status': 1, 'walletType': 1}}
        result = reconcile_sources('SPOT_LIVE', spot('100'), spot('97'), rows)
        self.assertEqual(result['state'], 'MATCHED_SUPPLIED_CUTS')
        self.assertEqual(result['transfers_by_asset'], {'USDT': '-3'})

    def test_withdrawal_fee_semantics_unknown_not_certified(self):
        rows = spot_streams()
        next(s for s in rows if s['kind'] == 'withdrawals')['records'] = {
            '1': {'coin': 'USDT', 'amount': '2', 'transactionFee': '0.1', 'status': 6, 'walletType': 0}}
        result = reconcile_sources('SPOT_LIVE', spot('100'), spot('97.9'), rows)
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertIn('WITHDRAWAL_DEBIT_SEMANTICS_UNKNOWN', result['reason_codes'])

    def test_daily_pair_rejects_missing_day_coverage_and_boundary_activity(self):
        snapshots = normalize_daily_snapshots('SPOT_LIVE', {'code': 200, 'snapshotVos': [
            {'type': 'spot', 'updateTime': START, 'data': spot('100')},
            {'type': 'spot', 'updateTime': END, 'data': spot('100')}]}, start_utc_ms=START, end_utc_ms=END)
        rows = spot_streams()
        self.assertTrue(reconcile_daily_pairs('SPOT_LIVE', snapshots, rows)[0]['reconciled'])
        rows[0]['coverage_end_ms'] = END-1
        self.assertIn('DAILY_PAIR_SOURCE_WINDOW_GAP', reconcile_daily_pairs('SPOT_LIVE', snapshots, rows)[0]['reason_codes'])
        rows[0]['coverage_end_ms'] = END
        rows[0]['records'] = {'1': trade(stamp=START)}
        result = reconcile_daily_pairs('SPOT_LIVE', snapshots, rows)[0]
        self.assertFalse(result['reconciled'])
        self.assertIn('DAILY_SNAPSHOT_BOUNDARY_EVENT_UNCERTAIN', result['reason_codes'])


class EarnSourceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transport = LiveReadOnlyTransport({'SPOT_LIVE':pair()}, clock=lambda:NOW)

    def job(self, **options):
        return EarnSourceCapture(self.transport,self.temp.name,start_utc_ms=START,end_utc_ms=END,
            clock=lambda:NOW,protect=cipher,unprotect=cipher,**options)

    def response(self, endpoint, params):
        common={'asset':'USDT','productId':'USDT001'}
        if endpoint.endswith('/position'):
            row={**common,'totalAmount':'5'}
        elif endpoint.endswith('/rewardsRecord'):
            row={**common,'time':START+2,'type':'REALTIME','rewards':'0.01'}
        else:
            row={**common,'time':START+2,'amount':'1','status':'SUCCESS',
                 'purchaseId':'8','redeemId':'9'}
        return {'rows':[row],'total':1}

    def test_restart_retains_raw_earn_sources_without_relabelling_them_as_cash(self):
        with patch.object(LiveReadOnlyTransport,'get_simple_earn',side_effect=self.response) as get:
            first=self.job().run(max_calls=1)
            self.assertEqual(first['streams_exhausted'],1)
            final=self.job().run(max_calls=4)
            self.assertEqual(final['state'],'EARN_SOURCES_CAPTURED')
            self.assertEqual(get.call_count,4)
            self.assertEqual(self.job().run()['calls_this_run'],0)
        self.assertFalse(final['ledger_reconciled'])
        self.assertFalse(final['financial_window_complete'])
        self.assertIn('EARN_TO_WRAPPER_IDENTITY_NOT_CERTIFIED',final['reason_codes'])
        self.assertEqual(sum(len(s['records']) for s in self.job().retained()['streams'].values()),4)
        self.assertNotIn(b'USDT',Path(self.temp.name,'earn-sources.dpapi').read_bytes())

    def test_changed_page_total_keeps_original_reply_and_uncommitted_page(self):
        def get(endpoint,params):
            if not endpoint.endswith('/redemptionRecord'):
                return {'rows':[],'total':0}
            row={**self.response(endpoint,params)['rows'][0],'redeemId':str(params['current'])}
            return {'rows':[row],'total':2 if params['current']==1 else 3}
        with patch.object(LiveReadOnlyTransport,'get_simple_earn',side_effect=get):
            self.job(page_size=1).run(max_calls=1)
            report=self.job(page_size=1).run(max_calls=1)
        stream=next(s for e,s in self.job(page_size=1).retained()['streams'].items() if e.endswith('/redemptionRecord'))
        self.assertEqual(stream['page'],2)
        self.assertEqual(len(stream['records']),1)
        self.assertIn('EARN_TOTAL_CHANGED',report['reason_codes'])
        self.assertEqual(len(self.job(page_size=1).retained()['originals']),2)

    def test_rate_limit_is_global_and_key_replacement_cannot_rebind_sources(self):
        error=LiveHTTPError('LIVE_RATE_LIMITED',http_status=429,provider_code=-1003)
        with patch.object(LiveReadOnlyTransport,'get_simple_earn',side_effect=error) as get:
            self.assertEqual(self.job().run()['state'],'EARN_RATE_LIMITED')
            self.assertEqual(self.job().run()['calls_this_run'],0)
            get.assert_called_once()
        self.transport._credentials['SPOT_LIVE']=pair('c')
        with self.assertRaisesRegex(LiveError,'CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED'):
            self.job().run()


class DailySnapshotTests(unittest.TestCase):
    def test_earn_sources_are_separate_get_only_and_reject_mutation_parameters(self):
        transport = LiveReadOnlyTransport({'SPOT_LIVE': pair()}, clock=lambda: NOW)
        endpoint = '/sapi/v1/simple-earn/flexible/history/rewardsRecord'
        fields = {'startTime': START, 'endTime': END, 'current': 1, 'size': 100, 'type': 'ALL'}
        with patch.object(LiveReadOnlyTransport, '_request', return_value={}) as send:
            transport.get_simple_earn(endpoint, fields)
        send.assert_called_once_with('SPOT_LIVE', 'GET', endpoint, fields, _simple_earn=True)
        for scope, method, ep, params in [
                ('SPOT_LIVE', 'POST', endpoint, fields),
                ('FUTURES_LIVE', 'GET', endpoint, fields),
                ('SPOT_LIVE', 'GET', '/sapi/v1/simple-earn/flexible/subscribe', fields),
                ('SPOT_LIVE', 'GET', endpoint, {**fields, 'amount': '1'}),
                ('SPOT_LIVE', 'GET', endpoint, {**fields, 'size': 101}),
                ('SPOT_LIVE', 'GET', endpoint, {**fields, 'type': 'OTHER'}),
                ('SPOT_LIVE', 'GET', endpoint, {**fields, 'current': 0})]:
            with self.subTest(scope=scope, method=method, ep=ep, params=params):
                with self.assertRaises(LiveError):
                    transport._request(scope, method, ep, params, _simple_earn=True)
        with self.assertRaisesRegex(LiveError, 'LIVE_GET_ENDPOINT_BLOCKED'):
            transport.get('SPOT_LIVE', endpoint, fields)

    def test_earn_capability_signs_only_get_on_fixed_spot_host(self):
        transport = LiveReadOnlyTransport({'SPOT_LIVE': pair()}, clock=lambda: NOW)
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return b'{"rows":[],"total":0}'
        class Opener:
            def open(self, request, timeout):
                self.request = request
                return Response()
        opener = Opener()
        with patch.object(LiveReadOnlyTransport, '_clock', return_value=int(NOW*1000)), patch.object(LiveReadOnlyTransport, '_opener', return_value=opener):
            transport.get_simple_earn('/sapi/v1/simple-earn/flexible/position', {'current':1,'size':100})
        parsed = urlparse(opener.request.full_url)
        self.assertEqual(parsed.hostname, 'api.binance.com')
        self.assertEqual(opener.request.get_method(), 'GET')
        self.assertEqual(parse_qs(parsed.query)['size'], ['100'])
        self.assertIn('signature', parse_qs(parsed.query))

    def test_snapshots_are_retained_once_per_scope_and_parser_preserves_original_time(self):
        with TemporaryDirectory() as temp:
            transport = LiveReadOnlyTransport({'SPOT_LIVE': pair()}, clock=lambda: NOW)
            make = lambda: DailySnapshotCapture(transport, temp, start_utc_ms=START, end_utc_ms=END,
                clock=lambda: NOW, protect=cipher, unprotect=cipher)
            response = {'code': 200, 'msg': '', 'snapshotVos': [
                {'type': 'spot', 'updateTime': START+5, 'data': spot('100')},
                {'type': 'spot', 'updateTime': END-5, 'data': spot('90')}]}
            with patch.object(LiveReadOnlyTransport, 'get_account_snapshots', return_value=response) as get:
                first = make().run()
                self.assertEqual(first['documented_ip_weight_this_run'], 2400)
                self.assertEqual(make().run()['snapshot_calls_this_run'], 0)
                self.assertEqual(get.call_count, 1)
            retained = make().retained()['snapshots']['SPOT_LIVE']
            self.assertEqual([r['at_ms'] for r in retained], [START+5, END-5])

    def test_snapshot_metadata_does_not_relax_generic_metadata_or_host(self):
        transport = LiveReadOnlyTransport({'FUTURES_LIVE': pair()}, clock=lambda: NOW)
        response = io.BytesIO(b'{"code":200,"snapshotVos":[]}')
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return response.read(n)
        class Opener:
            request = None
            def open(self, request, timeout):
                self.request = request
                return Response()
        opener = Opener()
        with patch.object(LiveReadOnlyTransport, '_clock', return_value=int(NOW*1000)), patch.object(LiveReadOnlyTransport, '_opener', return_value=opener):
            transport.get_account_snapshots('FUTURES_LIVE', start_utc_ms=START, end_utc_ms=END)
        parsed = urlparse(opener.request.full_url)
        self.assertEqual(parsed.hostname, 'api.binance.com')
        self.assertEqual(parsed.path, KEY_SNAPSHOT_ENDPOINT)
        self.assertEqual(parse_qs(parsed.query)['type'], ['FUTURES'])
        with self.assertRaisesRegex(LiveError, 'LIVE_KEY_METADATA_GET_BLOCKED'):
            transport.get_key_metadata('FUTURES_LIVE', KEY_SNAPSHOT_ENDPOINT)
        with self.assertRaisesRegex(LiveError, 'LIVE_SNAPSHOT_PARAMETERS_BLOCKED'):
            transport._request('FUTURES_LIVE', 'GET', KEY_SNAPSHOT_ENDPOINT,
                {'type': 'SPOT', 'startTime': START, 'endTime': END, 'limit': 30}, _key_metadata=True)


class ProspectiveCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'service'
        self.now, self.account_calls = [NOW], 0

    def service(self, credentials=None):
        return FinancialCaptureService(lambda: credentials or {'SPOT_LIVE': pair()}, self.directory,
            symbols=['BTCUSDT'], clock=lambda: self.now[0], protect=cipher, unprotect=cipher, interval_seconds=300)

    def get(self, scope, endpoint, params=None):
        if endpoint.endswith('/account'):
            self.account_calls += 1
            return spot('100') if self.account_calls == 1 else spot('89.999', '0.01')
        if endpoint.endswith('/myTrades'):
            return [trade(stamp=int(NOW*1000)+200000)]
        if endpoint.endswith('/asset/transfer'):
            return {'total': 0}
        return []

    def test_periodic_pipeline_normalizes_reconciles_without_manual_packet(self):
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get) as get:
            self.assertEqual(self.service().tick(max_calls=40)['state'], 'OPENING_CUTS_RETAINED')
            calls = get.call_count
            self.assertEqual(self.service().tick(max_calls=40)['state'], 'WAITING_NEXT_CAPTURE')
            self.assertEqual(get.call_count, calls)
            self.now[0] += 400
            result = self.service().tick(max_calls=40)
        self.assertEqual(result['state'], 'PROSPECTIVE_WINDOW_RECONCILED')
        self.assertEqual(result['completed_windows'], 1)
        self.assertTrue(result['last_reconciliation']['SPOT_LIVE']['matched_supplied_cuts'])
        self.assertFalse(result['ledger_reconciled'])
        self.assertNotIn('89.999', json.dumps(result))

    def test_closing_cut_is_not_replaced_when_history_resumes(self):
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get):
            self.service().tick(max_calls=1)
            self.now[0] += 400
            self.assertEqual(self.service().tick(max_calls=1)['state'], 'HISTORY_CAPTURE_PENDING')
            self.assertEqual(self.account_calls, 2)
            result = self.service().tick(max_calls=40)
            self.assertEqual(result['completed_windows'], 1)
            self.assertEqual(self.account_calls, 2)

    def test_replacement_key_blocks_without_resetting_baseline(self):
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get):
            self.service().tick(max_calls=40)
        self.now[0] += 400
        with patch.object(LiveReadOnlyTransport, 'get') as get:
            result = self.service({'SPOT_LIVE': pair('c')}).tick(max_calls=40)
        self.assertEqual(result['state'], 'CAPTURE_BLOCKED')
        self.assertIn('CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED', result['reason_codes'])
        get.assert_not_called()

    def test_restart_after_last_part_commit_finishes_same_retained_window(self):
        service = self.service()
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=self.get):
            service.tick(max_calls=40)
            self.now[0] += 400
            with patch.object(FinancialCaptureService, '_finish', side_effect=OSError('synthetic crash')):
                self.assertEqual(service.tick(max_calls=40)['state'], 'CAPTURE_BLOCKED')
            result = self.service().tick(max_calls=40)
        self.assertEqual(result['completed_windows'], 1)
        self.assertEqual(self.account_calls, 2)

    def test_unmatched_closed_window_remains_visible_after_restart(self):
        def get(scope, endpoint, params=None):
            if endpoint.endswith('/myTrades'):
                return []  # Account movement is not explained by supplied facts.
            return self.get(scope, endpoint, params)
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get):
            self.service().tick(max_calls=40)
            self.now[0] += 400
            result = self.service().tick(max_calls=40)
        self.assertEqual(result['unmatched_closed_windows'], 1)
        self.assertEqual(result['last_reconciliation']['SPOT_LIVE']['state'], 'DIFFERENCE')
        self.assertEqual(self.service().tick(max_calls=40)['unmatched_closed_windows'], 1)


class FinancialHistoryDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def transport(self):
        return LiveReadOnlyTransport({'SPOT_LIVE': pair()}, max_calls=80, clock=lambda: NOW)

    def driver(self, transport):
        return FinancialHistoryCapture(transport, self.root, symbols=['BTCUSDT'],
            start_utc_ms=END-2*DAY, end_utc_ms=END, clock=lambda: NOW, protect=cipher, unprotect=cipher)

    def test_history_resumes_fixed_two_day_window_and_reconciles_original_cuts(self):
        transport = self.transport()
        def get(scope, endpoint, params=None):
            transport.calls += 1
            return {'total': 0} if endpoint.endswith('/asset/transfer') else []
        snapshots = {'code': 200, 'snapshotVos': [
            {'type': 'spot', 'updateTime': END-2*DAY+1, 'data': spot('100')},
            {'type': 'spot', 'updateTime': END-1, 'data': spot('100')}]}
        with patch.object(LiveReadOnlyTransport, 'get', side_effect=get), patch.object(
                LiveReadOnlyTransport, 'get_account_snapshots', return_value=snapshots) as daily:
            first = self.driver(transport).run(max_calls=20, daily_snapshot_scopes=1)
            self.assertEqual(first['state'], 'HISTORY_CAPTURE_PENDING')
            self.assertEqual(first['completed_day_parts'], 1)
            transport = self.transport()
            result = self.driver(transport).run(max_calls=40, daily_snapshot_scopes=1)
            self.assertEqual(daily.call_count, 1)
            calls = transport.calls
            again = self.driver(transport).run(max_calls=40)
            self.assertEqual(transport.calls, calls)
        self.assertEqual(result['state'], 'BOUNDED_HISTORY_CAPTURED')
        self.assertEqual(result['completed_day_parts'], 2)
        self.assertEqual(result['reconciliation']['SPOT_LIVE']['cut_pairs_matched'], 1)
        self.assertFalse(result['account_history_complete'])
        self.assertEqual(again['calls_this_run'], 0)

    def test_failed_daily_response_retains_original_and_qualifies_no_cut(self):
        transport = self.transport()
        daily = DailySnapshotCapture(transport, self.root/'daily', start_utc_ms=START, end_utc_ms=END,
            clock=lambda: NOW, protect=cipher, unprotect=cipher)
        malformed = {'code': 200, 'snapshotVos': [{'type': 'futures', 'updateTime': START+1, 'data': fut('100')}]}
        with patch.object(LiveReadOnlyTransport, 'get_account_snapshots', return_value=malformed):
            result = daily.run()
        self.assertEqual(result['state'], 'DAILY_SNAPSHOTS_PENDING')
        state = daily.retained()
        self.assertEqual(len(state['originals']), 1)
        self.assertEqual(state['snapshots'], {})

    def test_cli_uses_existing_vault_and_prints_no_private_rows(self):
        from scripts.capture_financial_history import main
        import time
        actual_end = int(time.time()*1000)-1000
        output = io.StringIO()
        report = {'state': 'HISTORY_CAPTURE_PENDING', 'execution_enabled': False}
        with patch('scripts.capture_financial_history.LiveCredentialVault.read', return_value={'SPOT_LIVE': pair()}), patch(
                'scripts.capture_financial_history.FinancialHistoryCapture.run', return_value=report) as run, redirect_stdout(output):
            result = main(['--ack-read-only', '--vault', str(self.root/'existing.dpapi'), '--output-dir', str(self.root/'capture'),
                '--start-utc-ms', str(actual_end-1000), '--end-utc-ms', str(actual_end), '--scope', 'SPOT_LIVE'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), report)
        self.assertEqual(run.call_args.kwargs['daily_snapshot_scopes'], 0)
        self.assertNotIn('a'*64, output.getvalue())


if __name__ == '__main__':
    unittest.main()
