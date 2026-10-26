"""Synthetic local vault: no exchange, environment credentials or orders."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from trader.live_credentials import LiveCredentialVault, ProtectedStore, UserProtection, PURPOSES
from trader.live_transport import LiveCredentials, LiveError
from trader.local_protection import ProtectionError


class ProtectionFixture:
    def protect(self, raw, purpose):
        return purpose.encode()+b'|'+bytes(x ^ 71 for x in raw)
    def unprotect(self, raw, purpose):
        prefix=purpose.encode()+b'|'
        if not raw.startswith(prefix):raise LiveError('WRONG_PURPOSE')
        return bytes(x ^ 71 for x in raw[len(prefix):])


class VaultTests(unittest.TestCase):
    def test_roundtrip_retains_scopes_and_never_enables_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'credentials.dpapi';vault=LiveCredentialVault(path,protection=ProtectionFixture())
            pair=LiveCredentials('synthetic-live-key-1234','synthetic-live-secret-1234')
            vault.configure({'SPOT_LIVE':pair})
            self.assertEqual(vault.read(),{'SPOT_LIVE':pair})
            self.assertNotIn(pair.api_key,path.read_text());self.assertNotIn(pair.api_secret,path.read_text())
            self.assertEqual(vault.status(),{'state':'CONFIGURED_READ_ONLY','scopes':['SPOT_LIVE'],'orders_enabled':False})
            self.assertNotIn(pair.api_key,repr(pair))
            with self.assertRaises(LiveError):vault.configure({'SPOT_LIVE':pair})
            vault.configure({'SPOT_LIVE':pair,'FUTURES_LIVE':pair},replace=True)
            self.assertEqual(set(vault.read()),{'SPOT_LIVE','FUTURES_LIVE'})

    def test_corruption_wrong_purpose_and_enabled_flag_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'record';fixture=ProtectionFixture()
            store=ProtectedStore(path,PURPOSES[1],protection=fixture);store.write({'x':1})
            with self.assertRaises(LiveError):LiveCredentialVault(path,protection=fixture).read()
            store=ProtectedStore(path,PURPOSES[0],protection=fixture)
            store.write({'schema':1,'orders_enabled':True,'credentials':{}},replace=True)
            with self.assertRaises(LiveError):LiveCredentialVault(path,protection=fixture).read()
            path.write_bytes(b'not JSON')
            self.assertEqual(LiveCredentialVault(path,protection=fixture).status()['state'],'NOT_CONFIGURED_OR_UNAVAILABLE')

    def test_scope_and_control_character_injection_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=LiveCredentialVault(Path(folder)/'vault',protection=ProtectionFixture())
            pair=LiveCredentials('synthetic-key-123','synthetic-secret-123')
            for credentials in ({'TESTNET':pair},{'SPOT_LIVE':('key','secret')},{}):
                with self.assertRaises(LiveError):vault.configure(credentials)
            with self.assertRaises(LiveError):LiveCredentials('key\nheader','secret-123456')

    def test_oversized_and_duplicate_envelopes_never_decrypt(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'vault';vault=LiveCredentialVault(path,protection=ProtectionFixture())
            for raw in (b'x'*32769,b'{"schema":1,"schema":1}'):
                path.write_bytes(raw)
                with self.assertRaises(LiveError):vault.read()

    def test_configuration_never_accepts_secret_arguments_or_noninteractive_input(self):
        from scripts.configure_live_connection import main
        with patch('sys.stdin.isatty',return_value=False),patch('getpass.getpass') as prompt:
            self.assertEqual(main(['--scope','SPOT_LIVE']),2);prompt.assert_not_called()
        with self.assertRaises(SystemExit):main(['--api-key','must-not-enter-via-argv'])

    @unittest.skipUnless(os.name=='nt','Windows-user protection requires Windows')
    def test_native_windows_user_dpapi_roundtrip_and_purpose_isolation(self):
        protection=UserProtection();raw=b'synthetic-not-a-provider-secret-1234'
        encrypted=protection.protect(raw,PURPOSES[0])
        self.assertNotIn(raw,encrypted)
        self.assertEqual(protection.unprotect(encrypted,PURPOSES[0]),raw)
        with self.assertRaises(ProtectionError):protection.unprotect(encrypted,PURPOSES[1])


if __name__=='__main__':unittest.main()
