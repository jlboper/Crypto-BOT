"""Offline replay cannot replace sources or promote bounded source coverage."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.account_inventory import HOSTS
from trader.financial_capture import _load_cipher, _save_cipher
from trader.financial_evidence import AUTHORITY,digest
from trader.testnet_financial_replay import replay_retained_windows,verify_retained_packet
from tests.test_financial_evidence import fixture,iso


def cipher(value):return bytes(x^0xa5 for x in value)


class RetainedSourceReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.scope=self.root/'SPOT_TESTNET';self.scope.mkdir()
        (self.scope/'responses').mkdir()
        f=fixture()
        raw={'schema':1,'environment':'SPOT_TESTNET','host':HOSTS['SPOT_TESTNET'],
            'endpoint':'/api/v3/account','params':{},'started_ms':int(f[3].timestamp()*1000),
            'received_ms':int(f[3].timestamp()*1000),
            'response':{'uid':123,'balances':[{'asset':'USDT','free':'1000','locked':'0'}]}}
        self.raw_path=self.scope/'responses/000000000001.dpapi'
        _save_cipher(self.raw_path,raw,cipher)
        ref={'file':'responses/000000000001.dpapi','sha256':digest(raw),
             'encrypted_sha256':hashlib.sha256(self.raw_path.read_bytes()).hexdigest()}
        ledger={'at':iso(f[3]),'environment':'SPOT_TESTNET','positions':[],'trades':[],
                'native_protection':None,'scope':'LOCAL_LEDGER_ONLY','complete_account_certificate':False}
        self.packet={'schema':1,'environment':'SPOT_TESTNET','registration':f[0],
            'original':f[1],'baseline':{'refs':[ref],'ledger':deepcopy(ledger),'at':f[3].timestamp()},
            'closing_ledger':ledger,'source_refs':[ref],'sources':[raw],
            'symbol_universe':['BTCUSDT'],'source_scope':'BOUNDED_SYMBOLS','reason_codes':[],**AUTHORITY}
        self.path=self.scope/'windows'/digest(f[1])/'sources.dpapi'
        self.path.parent.mkdir(parents=True)
        _save_cipher(self.path,self.packet,cipher)

    def test_verified_replay_is_separate_encrypted_idempotent_and_offline(self):
        before={p:p.read_bytes() for p in self.scope.rglob('*.dpapi')}
        with patch('socket.socket.connect',side_effect=AssertionError('NO_NETWORK')):
            result=replay_retained_windows(self.scope,self.root/'output',protect=cipher,unprotect=cipher)
            again=replay_retained_windows(self.scope,self.root/'output',protect=cipher,unprotect=cipher)
        self.assertEqual(result,again)
        self.assertEqual(result['diagnostics_written'],1)
        self.assertEqual(result['network_calls'],0)
        self.assertFalse(result['financial_window_complete'])
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        retained=next((self.root/'output').glob('*.dpapi'))
        self.assertNotIn(b'normalized_fills',retained.read_bytes())
        self.assertFalse(_load_cipher(retained,cipher)['summary']['financial_window_complete'])

    def test_changed_original_or_copied_source_is_refused(self):
        changed=deepcopy(self.packet);changed['sources'][0]['response']['uid']=456
        _save_cipher(self.path,changed,cipher)
        with self.assertRaisesRegex(ValueError,'TESTNET_SOURCE_SCOPE_OR_CONTENT_CHANGED'):
            verify_retained_packet(self.path,unprotect=cipher)
        result=replay_retained_windows(self.scope,self.root/'output',protect=cipher,unprotect=cipher)
        self.assertEqual(result['windows_blocked'],1)
        self.assertEqual(result['diagnostics_written'],0)
        self.assertEqual(list((self.root/'output').glob('*.dpapi')),[])

    def test_source_output_overlap_and_unbounded_replay_are_refused(self):
        for output in (self.scope,self.scope/'nested',self.root):
            with self.assertRaisesRegex(ValueError,'SEPARATE_TESTNET_REPLAY_OUTPUT_REQUIRED'):
                replay_retained_windows(self.scope,output,protect=cipher,unprotect=cipher)
        with self.assertRaisesRegex(ValueError,'TESTNET_REPLAY_WINDOW_LIMIT_REQUIRED'):
            replay_retained_windows(self.scope,self.root/'output',max_windows=1001,protect=cipher,unprotect=cipher)


if __name__=='__main__':unittest.main()
