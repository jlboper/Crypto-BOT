"""Synthetic collateral/dividend source and separate GET capability regression."""
from copy import deepcopy
from contextlib import redirect_stderr,redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs

from trader.financial_capture import (SupplementalHistoryCapture,normalize_supplemental_history_row,
    COLLATERAL_HISTORY,DIVIDEND_HISTORY)
from trader.live_transport import LiveReadOnlyTransport,LiveError,LiveHTTPError
from tests.test_financial_capture import NOW,START,END,cipher,pair


def collateral(identity=1,stamp=START+1,**changes):
    return {'amount':'2.5','asset':'USDT','productId':'USDT001','productName':'USDT',
        'createTime':stamp,'type':'REPAY','orderId':identity,**changes}


def dividend(identity=1,stamp=START+1,**changes):
    return {'id':identity,'amount':'0.25','asset':'LDUSDT','divTime':stamp,
        'enInfo':'Synthetic distribution','tranId':100+identity,'direction':1,**changes}


class SupplementalCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.transport=LiveReadOnlyTransport({'SPOT_LIVE':pair()},clock=lambda:NOW)

    def test_capability_is_signed_get_on_fixed_spot_host(self):
        requests=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,size):return b'{"rows":[],"total":0}'
        class Opener:
            def open(self,request,timeout):requests.append(request);return Response()
        with patch.object(LiveReadOnlyTransport,'_clock',return_value=int(NOW*1000)), \
                patch.object(LiveReadOnlyTransport,'_opener',return_value=Opener()):
            self.transport.get_supplemental_account_history(COLLATERAL_HISTORY,
                {'startTime':START,'endTime':END,'current':1,'size':100})
            self.transport.get_supplemental_account_history(DIVIDEND_HISTORY,
                {'startTime':START,'endTime':END,'limit':500,'asset':'LDUSDT'})
        self.assertEqual(len(requests),2)
        for request in requests:
            parsed=urlparse(request.full_url)
            self.assertEqual(parsed.hostname,'api.binance.com')
            self.assertEqual(request.get_method(),'GET')
            self.assertIn('signature',parse_qs(parsed.query))

    def test_generic_earn_and_write_families_cannot_inherit_capability(self):
        fields={'startTime':START,'endTime':END,'limit':500}
        with patch.object(LiveReadOnlyTransport,'_opener') as opener:
            for endpoint in (COLLATERAL_HISTORY,DIVIDEND_HISTORY):
                with self.assertRaises(LiveError):self.transport.get('SPOT_LIVE',endpoint,{})
                with self.assertRaises(LiveError):self.transport.get_simple_earn(endpoint,{})
            for method,scope,extra in (('POST','SPOT_LIVE',{}),('GET','FUTURES_LIVE',{}),
                    ('GET','SPOT_LIVE',{'_key_metadata':True}),('GET','SPOT_LIVE',{'_simple_earn':True})):
                with self.assertRaises(LiveError):
                    self.transport._request(scope,method,DIVIDEND_HISTORY,fields,_supplemental_history=True,**extra)
            opener.assert_not_called()

    def test_closed_parameters_prevent_arbitrary_urls_types_and_time_windows(self):
        valid={'startTime':START,'endTime':END,'current':1,'size':100}
        invalid=[{**valid,'size':True},{**valid,'size':101},{**valid,'current':0},
            {**valid,'asset':'USDT'},{**valid,'productId':'../USDT'},
            {**valid,'endTime':int(NOW*1000)+1},{**valid,'startTime':END-31*86400000},
            {**valid,'signature':'fake'},{**valid,'recvWindow':60000}]
        with patch.object(LiveReadOnlyTransport,'_opener') as opener:
            for fields in invalid:
                with self.subTest(fields=fields),self.assertRaises(LiveError):
                    self.transport.get_supplemental_account_history(COLLATERAL_HISTORY,fields)
            with self.assertRaises(LiveError):
                self.transport.get_supplemental_account_history('https://example.invalid',valid)
            with self.assertRaises(LiveError):
                self.transport.get_supplemental_account_history(DIVIDEND_HISTORY,
                    {'startTime':START,'endTime':END,'limit':501})
            opener.assert_not_called()


class SupplementalCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'supplemental'
        self.transport=LiveReadOnlyTransport({'SPOT_LIVE':pair()},clock=lambda:NOW)

    def capture(self,**changes):
        return SupplementalHistoryCapture(self.transport,self.directory,start_utc_ms=START,end_utc_ms=END,
            clock=lambda:NOW,protect=cipher,unprotect=cipher,**changes)

    def test_confirmed_empty_sources_are_retained_and_only_exhaust_their_own_scope(self):
        def get(endpoint,fields):return {'rows':[],'total':'0' if endpoint==COLLATERAL_HISTORY else 0}
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=get):
            result=self.capture().run()
        self.assertEqual(result['state'],'SUPPLEMENTAL_SOURCES_CAPTURED')
        self.assertEqual(result['sources_exhausted'],2)
        self.assertEqual(result['rows_by_source'],{'assetDividend':0,'collateralRecord':0})
        self.assertTrue(result['raw_encrypted_retention'])
        for flag in ('ledger_reconciled','account_history_complete','financial_window_complete','ready_for_live','execution_enabled'):
            self.assertFalse(result[flag])
        self.assertEqual(len(self.capture().retained()['originals']),2)

    def test_raw_is_encrypted_before_envelope_validation_and_missing_rows_are_not_zero(self):
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',return_value={'total':'0'}):
            result=self.capture(endpoints=(COLLATERAL_HISTORY,)).run()
        self.assertEqual(result['sources_exhausted'],0)
        self.assertIn('SUPPLEMENTAL_ENVELOPE_INVALID',result['reason_codes'])
        self.assertEqual(len(self.capture(endpoints=(COLLATERAL_HISTORY,)).retained()['originals']),1)
        self.assertNotIn('"originals"',(self.directory/'supplemental-sources.dpapi').read_text())

    def test_collateral_page_resume_uses_total_string_and_preserves_original_ids(self):
        def get(endpoint,fields):return {'rows':[collateral(fields['current'])],'total':'2'}
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=get) as get_call:
            result=self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1).run(max_calls=1)
            self.assertEqual(result['sources_exhausted'],0)
            result=self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1).run(max_calls=1)
            self.assertEqual(result['sources_exhausted'],1)
            self.assertEqual(get_call.call_args.args[1]['current'],2)
        state=self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1).retained()
        self.assertEqual(len(state['originals']),2)
        self.assertEqual(len(state['streams'][COLLATERAL_HISTORY]['records']),2)

    def test_changed_or_duplicate_collateral_row_never_completes_page(self):
        responses=[{'rows':[collateral()],'total':'2'},{'rows':[collateral(amount='9')],'total':'2'}]
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=responses):
            self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1).run(max_calls=1)
            result=self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1).run(max_calls=1)
        self.assertEqual(result['sources_exhausted'],0)
        self.assertIn('SUPPLEMENTAL_DUPLICATE_OR_CHANGED_ROW',result['reason_codes'])
        self.assertEqual(len(self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1).retained()['originals']),2)

    def test_dividend_full_page_is_split_by_disjoint_time_intervals_without_offset(self):
        rows=[dividend(i,START+i*10) for i in range(1,4)]
        requests=[]
        def get(endpoint,fields):
            requests.append(deepcopy(fields))
            chosen=[row for row in rows if fields['startTime']<=row['divTime']<=fields['endTime']]
            return {'rows':chosen[:fields['limit']],'total':len(chosen)}
        def make():return SupplementalHistoryCapture(self.transport,self.directory,start_utc_ms=START,end_utc_ms=START+40,
            endpoints=(DIVIDEND_HISTORY,),dividend_limit=2,clock=lambda:NOW,protect=cipher,unprotect=cipher)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=get):
            first=make().run(max_calls=1)
            self.assertEqual(first['sources_exhausted'],0)
            self.assertEqual(first['rows_by_source']['assetDividend'],0)
            for _ in range(5):
                result=make().run(max_calls=4)
                if result['sources_exhausted']:break
        self.assertEqual(result['sources_exhausted'],1)
        self.assertEqual(result['rows_by_source']['assetDividend'],3)
        self.assertTrue(all(not set(fields)&{'current','offset','fromId'} for fields in requests))
        state=make().retained()['streams'][DIVIDEND_HISTORY]
        leaves=[node for node in state['segments'] if not node['children']]
        ordered=sorted(leaves,key=lambda row:row['start'])
        self.assertTrue(all(left['end']+1==right['start'] for left,right in zip(ordered,ordered[1:])))

    def test_wrong_envelope_total_type_or_false_empty_is_not_exhaustion(self):
        for endpoint,total in ((COLLATERAL_HISTORY,1),(DIVIDEND_HISTORY,'0'),(DIVIDEND_HISTORY,1)):
            with self.subTest(endpoint=endpoint,total=total),TemporaryDirectory() as folder:
                capture=SupplementalHistoryCapture(self.transport,folder,start_utc_ms=START,end_utc_ms=END,
                    endpoints=(endpoint,),clock=lambda:NOW,protect=cipher,unprotect=cipher)
                with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',return_value={'rows':[],'total':total}):
                    result=capture.run()
                self.assertEqual(result['sources_exhausted'],0)

    def test_observed_collateral_integer_zero_is_only_valid_with_empty_rows(self):
        capture=self.capture(endpoints=(COLLATERAL_HISTORY,))
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',return_value={'rows':[],'total':0}):
            result=capture.run()
        self.assertEqual(result['sources_exhausted'],1)
        self.assertEqual(result['rows_by_source'],{'collateralRecord':0})
        self.assertTrue(result['raw_encrypted_retention'])
        self.assertFalse(result['ledger_reconciled'])
        for raw in ({'rows':[],'total':False},{'rows':[],'total':True},
                {'rows':[],'total':1},{'rows':[collateral()],'total':0}):
            with self.subTest(raw=raw),self.assertRaises(LiveError):
                SupplementalHistoryCapture._total(COLLATERAL_HISTORY,raw)

    def test_saturated_single_millisecond_never_claims_dividend_exhaustion(self):
        stamp=START+1
        rows=[dividend(1,stamp),dividend(2,stamp)]
        def get(endpoint,fields):
            chosen=[row for row in rows if fields['startTime']<=row['divTime']<=fields['endTime']]
            return {'rows':chosen[:1],'total':len(chosen)}
        capture=SupplementalHistoryCapture(self.transport,self.directory,start_utc_ms=START,end_utc_ms=START+2,
            endpoints=(DIVIDEND_HISTORY,),dividend_limit=1,clock=lambda:NOW,protect=cipher,unprotect=cipher)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=get):
            for _ in range(3):result=capture.run()
        self.assertEqual(result['sources_exhausted'],0)
        self.assertIn('SUPPLEMENTAL_DENSE_TIMESTAMP_WINDOW',result['reason_codes'])
        self.assertTrue(result['raw_encrypted_retention'])

    def test_dividend_split_children_must_explain_parent_total(self):
        responses=[{'rows':[dividend(1,START)],'total':2},
            {'rows':[],'total':0},{'rows':[],'total':0}]
        capture=self.capture(endpoints=(DIVIDEND_HISTORY,),dividend_limit=1)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=responses):
            result=capture.run(max_calls=3)
        self.assertEqual(result['sources_exhausted'],0)
        self.assertIn('SUPPLEMENTAL_SPLIT_TOTAL_CONTRADICTION',result['reason_codes'])
        self.assertEqual(len(capture.retained()['originals']),3)

    def test_collateral_total_cannot_change_across_resumed_pages(self):
        responses=[{'rows':[collateral(1)],'total':'2'},{'rows':[collateral(2)],'total':'3'}]
        capture=self.capture(endpoints=(COLLATERAL_HISTORY,),page_size=1)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=responses):
            capture.run(max_calls=1)
            result=capture.run(max_calls=1)
        self.assertEqual(result['sources_exhausted'],0)
        self.assertIn('SUPPLEMENTAL_TOTAL_CHANGED',result['reason_codes'])

    def test_dividend_children_cannot_replace_parent_observed_identity_or_amount(self):
        for changed in ('identity','amount'):
            with self.subTest(changed=changed),TemporaryDirectory() as folder:
                left,right=dividend(1,START),dividend(2,END)
                changed_left=dividend(3,START) if changed=='identity' else dividend(1,START,amount='9')
                responses=[{'rows':[left,right],'total':2},
                    {'rows':[changed_left],'total':1},{'rows':[right],'total':1}]
                capture=SupplementalHistoryCapture(self.transport,folder,start_utc_ms=START,end_utc_ms=END,
                    endpoints=(DIVIDEND_HISTORY,),dividend_limit=2,clock=lambda:NOW,protect=cipher,unprotect=cipher)
                with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=responses):
                    result=capture.run(max_calls=3)
                self.assertEqual(result['sources_exhausted'],0)
                self.assertIn('SUPPLEMENTAL_SPLIT_OBSERVATION_CHANGED',result['reason_codes'])
                self.assertEqual(len(capture.retained()['originals']),3)

    def test_successful_retry_replaces_stale_numeric_provider_error(self):
        error=LiveHTTPError('LIVE_HTTP_UNAVAILABLE',http_status=401,provider_code=-2015)
        capture=self.capture(endpoints=(DIVIDEND_HISTORY,),dividend_limit=1)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=error):
            self.assertEqual(len(capture.run()['provider_errors']),1)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',
                return_value={'rows':[dividend()],'total':1}):
            result=capture.run(max_calls=1)
        self.assertEqual(result['provider_errors'],[])
        self.assertEqual(result['sources_exhausted'],0)

    def test_normalization_preserves_ld_units_and_debit_direction_without_sign_inference(self):
        row=normalize_supplemental_history_row(DIVIDEND_HISTORY,dividend(direction=-1),start_utc_ms=START,end_utc_ms=END)
        self.assertEqual((row['asset'],row['amount'],row['direction']),('LDUSDT','0.25',-1))
        for bad in (dividend(direction=True),dividend(direction=0),dividend(amount='NaN')):
            with self.assertRaises(LiveError):normalize_supplemental_history_row(DIVIDEND_HISTORY,bad,start_utc_ms=START,end_utc_ms=END)

    def test_rate_limit_stops_all_sources_and_retains_numeric_error_without_permission_claim(self):
        error=LiveHTTPError('LIVE_RATE_LIMITED',http_status=429,provider_code=-1003)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=error) as get:
            result=self.capture().run()
            self.assertEqual(result['state'],'SUPPLEMENTAL_RATE_LIMITED')
            self.assertEqual(get.call_count,1)
            self.assertEqual(self.capture().run()['calls_this_run'],0)
        self.assertNotIn('permission_required',result)

    def test_ambiguous_2015_is_numeric_evidence_and_not_a_known_missing_permission(self):
        error=LiveHTTPError('LIVE_HTTP_UNAVAILABLE',http_status=401,provider_code=-2015)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',side_effect=error):
            result=self.capture(endpoints=(COLLATERAL_HISTORY,)).run()
        self.assertEqual(result['provider_errors'],[{'source':'collateralRecord','http_status':401,'provider_code':-2015}])
        self.assertNotIn('permission_required',result)
        self.assertFalse(result['financial_authorization'])

    def test_existing_key_scope_and_window_cannot_be_replaced_on_resume(self):
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history',return_value={'rows':[],'total':'0'}):
            self.capture(endpoints=(COLLATERAL_HISTORY,)).run()
        changed=LiveReadOnlyTransport({'SPOT_LIVE':pair('c')},clock=lambda:NOW)
        with patch.object(LiveReadOnlyTransport,'get_supplemental_account_history') as get,self.assertRaises(LiveError):
            SupplementalHistoryCapture(changed,self.directory,start_utc_ms=START,end_utc_ms=END,
                endpoints=(COLLATERAL_HISTORY,),clock=lambda:NOW,protect=cipher,unprotect=cipher).run()
        get.assert_not_called()

    def test_cli_reuses_only_existing_spot_scope_and_prints_no_private_rows(self):
        from scripts import capture_supplemental_history as cli
        result={'state':'SUPPLEMENTAL_SOURCES_CAPTURED','execution_enabled':False}
        output=io.StringIO()
        with patch.object(cli.LiveCredentialVault,'read',return_value={'SPOT_LIVE':pair(),'FUTURES_LIVE':pair('c')}), \
                patch.object(cli,'SupplementalHistoryCapture') as capture,redirect_stdout(output):
            capture.return_value.run.return_value=result
            code=cli.main(['--ack-read-only','--vault',str(self.directory/'existing.dpapi'),'--output-dir',str(self.directory/'capture'),
                '--start-utc-ms',str(START),'--end-utc-ms',str(END)])
        self.assertEqual(code,0)
        self.assertEqual(set(capture.call_args.args[0]._credentials),{'SPOT_LIVE'})
        self.assertEqual(json.loads(output.getvalue()),result)
        self.assertNotIn(pair().api_key,output.getvalue())

    def test_cli_invalid_arguments_never_echo_an_accidentally_pasted_value(self):
        from scripts import capture_supplemental_history as cli
        output=io.StringIO()
        with redirect_stderr(output),self.assertRaises(SystemExit):cli.main(['--unexpected','SYNTHETIC_SECRET_DO_NOT_ECHO'])
        self.assertEqual(output.getvalue(),'SUPPLEMENTAL_CAPTURE_ARGUMENTS_INVALID\n')


if __name__=='__main__':unittest.main()
