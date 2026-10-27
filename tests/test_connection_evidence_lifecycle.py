"""Synthetic key changes and dated evidence; no credentials or network."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveCredentials, LiveError
from trader.preproduction_status import read_preproduction_status, valid_connection
from tests.test_live_credentials_hardening import SyntheticProtection

START = 1793102400.0


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec='milliseconds').replace('+00:00','Z')


def verified():
    return {'schema':1, 'state':'READ_ONLY_VERIFIED', 'at':stamp(START),
        'scopes':[{'environment':scope,'identity':'REPORTED','permissions':'VERIFIED','at':stamp(START)}
                  for scope in ('SPOT_LIVE','FUTURES_LIVE')]}


class ConnectionEvidenceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'data'; self.folder=self.data/'live-preproduction'
        self.folder.mkdir(parents=True)
        self.cache=self.folder/'connection-status.json'; self.path=self.folder/'credentials.dpapi'
        self.spot=LiveCredentials('A'*64,'B'*64); self.future=LiveCredentials('C'*64,'D'*64)
        self.vault=LiveCredentialVault(self.path,protection=SyntheticProtection(),connection_cache_path=self.cache)
        self.vault.configure({'SPOT_LIVE':self.spot,'FUTURES_LIVE':self.future})
        self.cache.write_text(json.dumps(verified()))

    def test_owner_replacement_invalidates_old_identity_before_new_key_commit(self):
        replacement=LiveCredentials('E'*64,'F'*64)
        self.vault.configure_scope('FUTURES_LIVE',replacement,replace=True)
        self.assertEqual(self.vault.read(),{'SPOT_LIVE':self.spot,'FUTURES_LIVE':replacement})
        cache=json.loads(self.cache.read_text())
        self.assertTrue(valid_connection(cache,at=stamp(START+1)))
        self.assertEqual(cache['state'],'CONFIGURED_UNVERIFIED')
        self.assertIsNone(cache['at'])
        self.assertTrue(all(x['identity']=='UNKNOWN' and x['permissions']=='UNKNOWN' and x['at'] is None for x in cache['scopes']))
        self.assertNotIn(replacement.api_key,self.cache.read_text())

    def test_refused_scope_replacement_keeps_existing_cut_and_keys(self):
        keys=self.path.read_bytes(); cache=self.cache.read_bytes()
        with self.assertRaisesRegex(LiveError,'EXPLICIT_CREDENTIAL_REPLACEMENT_REQUIRED'):
            self.vault.configure_scope('FUTURES_LIVE',LiveCredentials('E'*64,'F'*64))
        self.assertEqual(self.path.read_bytes(),keys); self.assertEqual(self.cache.read_bytes(),cache)

    def test_bulk_replacement_also_invalidates_cache_and_refusal_preserves_it(self):
        before=self.cache.read_bytes()
        with self.assertRaises(LiveError):
            self.vault.configure({'SPOT_LIVE':self.spot})
        self.assertEqual(before,self.cache.read_bytes())
        self.vault.configure({'SPOT_LIVE':self.spot,'FUTURES_LIVE':self.future},replace=True)
        self.assertEqual(json.loads(self.cache.read_text())['state'],'CONFIGURED_UNVERIFIED')

    def test_failed_invalidation_prevents_key_write(self):
        keys=self.path.read_bytes()
        with patch('trader.live_credentials.os.replace',side_effect=PermissionError('synthetic')):
            with self.assertRaisesRegex(LiveError,'CONNECTION_EVIDENCE_INVALIDATION_REQUIRED'):
                self.vault.configure_scope('FUTURES_LIVE',LiveCredentials('E'*64,'F'*64),replace=True)
        self.assertEqual(self.path.read_bytes(),keys)
        self.assertEqual(list(self.folder.glob('.connection-invalid-*')),[])

    def test_hardlinked_or_foreign_cache_cannot_be_replaced(self):
        keys=self.path.read_bytes(); linked=self.folder/'retained.json'; os.link(self.cache,linked)
        with self.assertRaisesRegex(LiveError,'CONNECTION_CACHE_PATH_BLOCKED'):
            self.vault.configure_scope('FUTURES_LIVE',LiveCredentials('E'*64,'F'*64),replace=True)
        self.assertEqual(self.path.read_bytes(),keys); self.assertEqual(linked.read_bytes(),self.cache.read_bytes())
        other=Path(self.temp.name)/'connection-status.json'
        vault=LiveCredentialVault(self.path,protection=SyntheticProtection(),connection_cache_path=other)
        with self.assertRaisesRegex(LiveError,'CONNECTION_CACHE_PATH_BLOCKED'):
            vault.configure_scope('FUTURES_LIVE',LiveCredentials('E'*64,'F'*64),replace=True)
        self.assertFalse(other.exists()); self.assertEqual(self.path.read_bytes(),keys)

    def test_dated_cut_expires_without_mutating_or_rejuvenating_evidence(self):
        before=self.cache.read_bytes()
        fresh=read_preproduction_status(self.data,'0.10.56',now=START+899)
        self.assertEqual(fresh['connection']['state'],'READ_ONLY_VERIFIED')
        stale=read_preproduction_status(self.data,'0.10.56',now=START+901)
        self.assertEqual(stale['connection']['state'],'CONFIGURED_UNVERIFIED')
        self.assertEqual(stale['connection']['at'],stamp(START))
        self.assertTrue(all(x['permissions']=='UNKNOWN' for x in stale['connection']['scopes']))
        self.assertIn('READ_ONLY_CONNECTION_UNVERIFIED',stale['blockers'])
        self.assertFalse(stale['execution_enabled']); self.assertEqual(before,self.cache.read_bytes())

    def test_a_fresh_global_timestamp_cannot_hide_an_old_scope_cut(self):
        cache=verified();cache['at']=stamp(START+600);cache['scopes'][1]['at']=stamp(START+600)
        self.cache.write_text(json.dumps(cache))
        value=read_preproduction_status(self.data,'0.10.56',now=START+901)
        self.assertEqual(value['connection']['state'],'CONFIGURED_UNVERIFIED')
        self.assertEqual(value['connection']['scopes'][0]['at'],stamp(START))

    def test_verified_label_requires_verified_rights_from_both_scopes(self):
        for index in (0,1):
            cache=verified();cache['scopes'][index]['permissions']='UNKNOWN'
            self.assertFalse(valid_connection(cache,at=stamp(START+1)))
            self.cache.write_text(json.dumps(cache))
            value=read_preproduction_status(self.data,'0.10.56',now=START+1)
            self.assertEqual(value['connection']['state'],'UNAVAILABLE')
            self.assertIn('READ_ONLY_CONNECTION_UNVERIFIED',value['blockers'])


if __name__=='__main__': unittest.main()
