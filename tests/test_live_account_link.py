"""Synthetic account-link evidence. Never reads operating credentials or APIs."""
import base64
import copy
from contextlib import contextmanager
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.parse

from trader.live_transport import (LiveCredentials, LiveError, LiveReadOnlyTransport,
    KEY_METADATA_HOST, HOSTS)
from trader.live_account import (LiveAccountAudit, EncryptedAuditStore, AUTHORITY,
    PERMISSION_FIELDS, KEY_RIGHT_FIELDS, connection_status_from_audit, publish_connection_status)
from trader.preproduction_status import valid_connection

NOW = 1_700_000_000_000
UID = 9_223_372_036_850_000_001


def credentials(suffix):
    return LiveCredentials("SyntheticKeyForOrigin"+suffix, "SyntheticSecretForOrigin"+suffix)


class Response:
    status = 200

    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.raw[:limit]


class Opener:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def open(self, request, timeout):
        self.requests.append(request)
        return Response(self.responses.pop(0))


class GlobalMetadataTransportTests(unittest.TestCase):
    def transport(self, **kwargs):
        return LiveReadOnlyTransport({"SPOT_LIVE":credentials("Spot"), "FUTURES_LIVE":credentials("Futures")},
                                     clock=lambda:NOW/1000, monotonic=lambda:10, **kwargs)

    def test_global_metadata_preserves_future_key_origin_and_correct_clock_host(self):
        transport = self.transport()
        opener = Opener([{"serverTime":NOW}, {"uid":UID}, {}])
        with patch.object(transport, "_opener", return_value=opener):
            transport.get_key_metadata("FUTURES_LIVE", "/api/v3/account")
            transport.get_key_metadata("FUTURES_LIVE", "/sapi/v1/account/apiRestrictions")
        self.assertEqual(len(opener.requests), 3)
        self.assertTrue(all(req.full_url.startswith(KEY_METADATA_HOST+"/") for req in opener.requests))
        request = opener.requests[1]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("X-mbx-apikey"), credentials("Futures").api_key)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        signature = query.pop("signature")[0]
        unsigned = urllib.parse.urlencode(sorted((key, value[0]) for key, value in query.items()))
        expected = hmac.new(credentials("Futures").api_secret.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(HOSTS["FUTURES_LIVE"], "https://fapi.binance.com")
        self.assertEqual(transport.calls, 3)

    def test_product_and_global_clocks_are_separate(self):
        transport = self.transport()
        opener = Opener([{"serverTime":NOW}, {}, {"serverTime":NOW}, {}])
        with patch.object(transport, "_opener", return_value=opener):
            transport.get("FUTURES_LIVE", "/fapi/v3/account")
            transport.get_key_metadata("FUTURES_LIVE", "/api/v3/account")
        times = [req.full_url for req in opener.requests if req.full_url.endswith("/time")]
        self.assertEqual(times, ["https://fapi.binance.com/fapi/v1/time", "https://api.binance.com/api/v3/time"])

    def test_no_key_substitution_and_no_product_whitelist_expansion(self):
        transport = LiveReadOnlyTransport({"SPOT_LIVE":credentials("Spot")})
        with patch.object(transport, "_opener") as opener:
            with self.assertRaises(LiveError):
                transport.get_key_metadata("FUTURES_LIVE", "/api/v3/account")
            for scope, path in (("SPOT_TESTNET", "/api/v3/account"), ("SPOT_LIVE", "https://evil.invalid"),
                                ("SPOT_LIVE", "/sapi/v1/capital/withdraw/apply")):
                with self.assertRaises(LiveError):
                    transport.get_key_metadata(scope, path)
            with self.assertRaises(LiveError):
                self.transport().get("FUTURES_LIVE", "/sapi/v1/account/apiRestrictions")
        opener.assert_not_called()

    def test_global_family_never_authorizes_writes_or_input_parameters(self):
        transport = self.transport()
        with patch.object(transport, "_opener") as opener:
            for method in ("POST", "DELETE", "PUT", "HEAD"):
                with self.assertRaisesRegex(LiveError, "METADATA_GET_BLOCKED"):
                    transport._request("FUTURES_LIVE", method, "/api/v3/account", {}, _key_metadata=True)
            for fields in ({"base_url":"https://evil.invalid"}, {"symbol":"BTCUSDT"}):
                with self.assertRaises(LiveError):
                    transport._request("FUTURES_LIVE", "GET", "/api/v3/account", fields, _key_metadata=True)
            with self.assertRaises(LiveError):
                transport._request("FUTURES_LIVE", "GET", "/api/v3/account", {}, _key_metadata=1)
        opener.assert_not_called()
        self.assertEqual(transport.calls, 0)

    def test_global_requests_share_budget_and_timeout_clock_gate(self):
        transport = self.transport(max_calls=2)
        opener = Opener([{"serverTime":NOW}, {}])
        with patch.object(transport, "_opener", return_value=opener):
            transport.get_key_metadata("FUTURES_LIVE", "/api/v3/account")
            with self.assertRaises(LiveError):
                transport.get_key_metadata("FUTURES_LIVE", "/sapi/v1/account/apiRestrictions")
        self.assertEqual(transport.calls, 2)
        self.assertEqual(len(opener.requests), 2)
        transport = self.transport()
        opener = Opener([{"serverTime":NOW}])
        with patch.object(transport, "_opener", return_value=opener), \
                patch.object(transport, "monotonic", side_effect=[10, 13]):
            with self.assertRaisesRegex(LiveError, "CLOCK_UNVERIFIED"):
                transport.get_key_metadata("FUTURES_LIVE", "/api/v3/account")
        self.assertEqual(len(opener.requests), 1)


class AccountLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.index = 0

    @staticmethod
    def identity(uid=UID):
        return {"uid":uid, "accountType":"SPOT", "canTrade":True, "balances":[]}

    @staticmethod
    def permissions():
        return {key:key=="enableReading" for key in KEY_RIGHT_FIELDS} | {"enableFixReadOnly":True,"createTime":NOW-1000}

    def run_audit(self, *, uids=None, permission_patch=None, permission_drop=(), missing=(), identity_patch=None, native_uid=UID):
        self.index += 1
        store = EncryptedAuditStore(self.folder/str(self.index), protect=lambda raw:b"SYNTHETIC-CIPHER:"+base64.b64encode(raw))
        transport = LiveReadOnlyTransport({"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Futures")})
        calls = []
        def normal(scope, endpoint, params=None):
            if endpoint=="/api/v3/account":return self.identity(native_uid)
            if endpoint=="/fapi/v3/account":return {"assets":[],"positions":[],"totalWalletBalance":"0",
                "availableBalance":"0","totalUnrealizedProfit":"0","totalMarginBalance":"0"}
            if endpoint=="/sapi/v1/account/apiRestrictions":return {key:key=="enableReading" for key in PERMISSION_FIELDS}
            if endpoint=="/fapi/v1/accountConfig":return {"dualSidePosition":False,"multiAssetsMargin":False,"canTrade":True}
            if endpoint=="/sapi/v1/asset/transfer":return {"total":0}
            if endpoint.endswith("exchangeInfo"):return {"symbols":[]}
            if endpoint.endswith(("commission", "commissionRate", "price")):return {}
            return []
        def global_metadata(scope, endpoint):
            calls.append((scope,endpoint))
            if (scope,endpoint) in missing:raise LiveError("LIVE_HTTP_UNAVAILABLE")
            if endpoint=="/api/v3/account":
                value=self.identity((uids or {}).get(scope,UID))
                if identity_patch:value.update(identity_patch)
                return value
            value=self.permissions()
            if permission_patch:value.update(permission_patch)
            for key in permission_drop:value.pop(key,None)
            return value
        transport.get=normal
        transport.get_key_metadata=global_metadata
        audit=LiveAccountAudit(transport,symbols=["BTCUSDT"],start_utc_ms=NOW-1000,end_utc_ms=NOW,
            raw_store=store,clock=lambda:NOW/1000,verify_account_link=True)
        return audit.run(),calls,store

    def test_same_uid_link_is_observed_without_disclosing_uid_or_merging_money(self):
        report,calls,store=self.run_audit()
        link=report["account_link"]
        self.assertEqual(link["status"],"SAME_ACCOUNT_OBSERVED")
        self.assertIs(link["same_account_observed"],True)
        self.assertEqual(calls,[(scope,path) for scope in ("SPOT_LIVE","FUTURES_LIVE")
            for path in ("/api/v3/account","/sapi/v1/account/apiRestrictions")])
        self.assertNotIn(str(UID),json.dumps(report))
        self.assertNotIn(str(UID),(store.directory/"audit.json").read_text())
        self.assertFalse(link["wallets_merged"])
        self.assertFalse(link["human_ownership_certified"])
        self.assertFalse(any(report["authority"].values()))
        self.assertFalse(report["wallets"]["FUTURES_LIVE"]["account"]["identity_reported"])
        self.assertEqual(report["wallets"]["FUTURES_LIVE"]["permissions"]["status"],"UNKNOWN")
        dto=connection_status_from_audit(report,now=NOW/1000)
        self.assertEqual(dto["state"],"READ_ONLY_VERIFIED")
        self.assertTrue(valid_connection(dto,at=report["finished_utc"]))
        self.assertTrue(all(row["permissions"]=="VERIFIED" for row in dto["scopes"]))
        self.assertFalse(report["account_history_complete"])

    def test_different_uids_do_not_link_or_share_wallets(self):
        report,_,_=self.run_audit(uids={"FUTURES_LIVE":UID-1})
        self.assertEqual(report["account_link"]["status"],"DIFFERENT_ACCOUNTS")
        self.assertIs(report["account_link"]["same_account_observed"],False)
        self.assertEqual(connection_status_from_audit(report,now=NOW/1000)["state"],"CONFIGURED_UNVERIFIED")
        self.assertFalse(report["wallets_merged"])

    def test_native_spot_uid_contradiction_is_unknown(self):
        report,_,_=self.run_audit(native_uid=UID-1)
        self.assertEqual(report["account_link"]["status"],"UNKNOWN")
        self.assertIn("LIVE_KEY_IDENTITY_CONTRADICTION",report["errors"])

    def test_missing_or_malformed_uid_is_unknown_never_zero(self):
        for uid in (0,-1,True,str(UID),2**63,None):
            with self.subTest(kind=type(uid).__name__):
                report,_,_=self.run_audit(uids={"FUTURES_LIVE":uid})
                self.assertEqual(report["account_link"]["status"],"UNKNOWN")
                self.assertFalse(report["account_link"]["scopes"][1]["identity_reported"])

    def test_error_shaped_global_identity_is_not_a_uid_observation(self):
        for extra in ({"code":-2015},{"msg":"not an account"},{"accountType":"OTHER"},{"balances":None}):
            with self.subTest(extra=tuple(extra)):
                report,_,_=self.run_audit(identity_patch=extra)
                self.assertEqual(report["account_link"]["status"],"UNKNOWN")

    def test_read_only_key_rights_do_not_certify_product_or_owner(self):
        report,_,_=self.run_audit()
        rights=report["account_link"]["scopes"][1]["global_key_permissions"]
        self.assertTrue(rights["read_only_verified"])
        self.assertTrue(rights["configured_markets_read_only_verified"])
        self.assertFalse(rights["product_permissions_certified"])
        for flag in ("enableReading","enableWithdrawals","enableFutures","enableInternalTransfer","enableFixApiTrade"):
            value=False if flag=="enableReading" else True
            changed,_,_=self.run_audit(permission_patch={flag:value})
            dto=connection_status_from_audit(changed,now=NOW/1000)
            self.assertEqual(dto["state"],"CONFIGURED_UNVERIFIED")
            self.assertTrue(all(row["permissions"]=="UNKNOWN" for row in dto["scopes"]))

    def test_missing_other_product_flags_are_explicit_and_not_false(self):
        report,_,_=self.run_audit(permission_patch={"enableVanillaOptions":None,"enableFixApiTrade":None})
        # A malformed, present FIX permission cannot be accepted as absent.
        self.assertEqual(connection_status_from_audit(report,now=NOW/1000)["state"],"CONFIGURED_UNVERIFIED")

    def test_absent_other_product_rights_do_not_invent_false_or_extend_scope(self):
        report,_,_=self.run_audit(permission_drop=("enableVanillaOptions","enableFixApiTrade","enableFixReadOnly"))
        rights=report["account_link"]["scopes"][1]["global_key_permissions"]
        self.assertEqual(rights["status"],"PARTIAL")
        self.assertFalse(rights["read_only_verified"])
        self.assertTrue(rights["configured_markets_read_only_verified"])
        self.assertTrue(rights["other_product_rights_unknown"])
        self.assertIsNone(rights["flags"]["enableVanillaOptions"])
        self.assertIsNone(rights["flags"]["enableFixApiTrade"])
        self.assertEqual(rights["reason"],"CONFIGURED_MARKETS_READ_ONLY_OTHER_RIGHTS_UNKNOWN")
        self.assertFalse(rights["product_permissions_certified"])
        dto=connection_status_from_audit(report,now=NOW/1000)
        self.assertEqual(dto["state"],"READ_ONLY_VERIFIED")
        self.assertEqual([row["environment"] for row in dto["scopes"]],["SPOT_LIVE","FUTURES_LIVE"])

    def test_missing_configured_scope_rights_remain_unknown(self):
        for flag in ("enableReading","enableSpotAndMarginTrading","enableFutures","enableWithdrawals","permitsUniversalTransfer"):
            report,_,_=self.run_audit(permission_drop=(flag,))
            rights=report["account_link"]["scopes"][0]["global_key_permissions"]
            self.assertIsNone(rights["flags"][flag])
            self.assertFalse(rights["configured_markets_read_only_verified"])
            self.assertEqual(connection_status_from_audit(report,now=NOW/1000)["state"],"CONFIGURED_UNVERIFIED")

    def test_present_malformed_metadata_is_not_treated_as_absent(self):
        for field in ("enableFixReadOnly","enableFixApiTrade","enableVanillaOptions","createTime"):
            with self.subTest(field=field):
                report,_,_=self.run_audit(permission_patch={field:"malformed"})
                rights=report["account_link"]["scopes"][0]["global_key_permissions"]
                self.assertTrue(rights["invalid_fields_present"])
                self.assertFalse(rights["configured_markets_read_only_verified"])
                self.assertEqual(connection_status_from_audit(report,now=NOW/1000)["state"],"CONFIGURED_UNVERIFIED")

    def test_unknown_capability_blocks_read_only_claim(self):
        report,_,_=self.run_audit(permission_patch={"enableUnknownProduct":True})
        rights=report["account_link"]["scopes"][0]["global_key_permissions"]
        self.assertTrue(rights["unexpected_fields_present"])
        self.assertEqual(rights["reason"],"UNRECOGNIZED_KEY_METADATA")
        self.assertEqual(connection_status_from_audit(report,now=NOW/1000)["state"],"CONFIGURED_UNVERIFIED")

    def test_global_failure_remains_unknown_without_fallback(self):
        report,calls,_=self.run_audit(missing={("FUTURES_LIVE","/api/v3/account")})
        self.assertEqual(len(calls),4)
        self.assertEqual(report["account_link"]["status"],"UNKNOWN")
        self.assertEqual(report["status"],"PARTIAL")
        dto=connection_status_from_audit(report,now=NOW/1000)
        self.assertEqual(dto["scopes"][1]["identity"],"UNKNOWN")

    def test_link_requires_two_distinct_origins_and_encrypted_retention(self):
        for pairs,store in (({"SPOT_LIVE":credentials("Spot")},None),
                ({"SPOT_LIVE":credentials("Same"),"FUTURES_LIVE":credentials("Same")},None),
                ({"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Future")},None)):
            transport=LiveReadOnlyTransport(pairs)
            with self.assertRaises(LiveError):
                LiveAccountAudit(transport,symbols=["BTCUSDT"],start_utc_ms=NOW-1000,end_utc_ms=NOW,
                    clock=lambda:NOW/1000,verify_account_link=True,raw_store=store)
            self.assertEqual(transport.calls,0)

    def test_cache_rejects_stale_future_unretained_or_authority_evidence(self):
        report,_,_=self.run_audit()
        for change in ({"raw_encrypted_retention":False},{"wallets_merged":True},
                       {"authority":AUTHORITY|{"execution_enabled":True}},
                       {"account_link":report["account_link"]|{"same_account_observed":1}}):
            with self.subTest(change=tuple(change)):
                with self.assertRaises(LiveError):connection_status_from_audit(report|change,now=NOW/1000)
        for current in (NOW/1000+301,NOW/1000-1):
            with self.assertRaises(LiveError):connection_status_from_audit(report,now=current)
        changed=copy.deepcopy(report)
        changed["account_link"]["scopes"][0]["evidence_refs"]["identity"]="a"*64
        with self.assertRaises(LiveError):connection_status_from_audit(changed,now=NOW/1000)

    def test_cache_requires_fresh_native_account_evidence_as_well_as_global_metadata(self):
        report,_,_=self.run_audit()
        for mutation in ("missing","stale","unretained","bad_wallet"):
            candidate=copy.deepcopy(report)
            native=next(item for item in candidate["observations"] if item["scope"]=="FUTURES_LIVE" and item["name"]=="account")
            if mutation=="missing":candidate["observations"].remove(native)
            elif mutation=="stale":native["received_utc"]="2023-11-14T22:08:20.000Z"
            elif mutation=="unretained":native["raw"]=None
            else:candidate["wallets"]["FUTURES_LIVE"]=None
            with self.subTest(mutation=mutation),self.assertRaises(LiveError):
                connection_status_from_audit(candidate,now=NOW/1000)
        for clock in (True,False,float("nan"),float("inf"),"invalid"):
            with self.subTest(clock=clock),self.assertRaises(LiveError):
                connection_status_from_audit(report,now=clock)

    def test_observation_cache_is_bounded_atomic_and_does_not_write_authority(self):
        report,_,_=self.run_audit()
        target=self.folder/"local-data"
        dto=publish_connection_status(report,target,now=NOW/1000)
        path=target/"live-preproduction/connection-status.json"
        self.assertEqual(json.loads(path.read_text()),dto)
        self.assertLess(path.stat().st_size,8000)
        self.assertFalse((target/"live-preproduction/authorization.dpapi").exists())
        self.assertFalse((target/"live-preproduction/readiness.dpapi").exists())
        current=dto|{"at":"2023-11-14T22:13:21.000Z"}
        path.write_text(json.dumps(current))
        with self.assertRaisesRegex(LiveError,"OLDER_THAN_CURRENT"):
            publish_connection_status(report,target,now=NOW/1000)
        self.assertEqual(json.loads(path.read_text()),current)

    def test_busy_cache_writer_preserves_existing_value_and_lock_releases_on_exit(self):
        report,_,_=self.run_audit()
        data=self.folder/"busy-data";folder=data/"live-preproduction";folder.mkdir(parents=True)
        lock=folder/"connection-status.json.lock";ready=self.folder/"ready";release=self.folder/"release"
        script='''import os,sys,time
from pathlib import Path
h=open(sys.argv[1],'a+b');h.seek(0)
if os.name=='nt':
 import msvcrt
 msvcrt.locking(h.fileno(),msvcrt.LK_NBLCK,1)
else:
 import fcntl
 fcntl.flock(h.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
Path(sys.argv[2]).write_text('ready')
until=time.monotonic()+15
while not Path(sys.argv[3]).exists() and time.monotonic()<until:time.sleep(.025)
h.close()
'''
        child=subprocess.Popen([sys.executable,"-I","-B","-c",script,str(lock),str(ready),str(release)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            deadline=time.monotonic()+10
            while not ready.exists() and time.monotonic()<deadline and child.poll() is None:time.sleep(.025)
            self.assertTrue(ready.exists(),"Synthetic lock fixture must own its empty file")
            with self.assertRaisesRegex(LiveError,"STATUS_BUSY"):
                publish_connection_status(report,data,now=NOW/1000)
            self.assertFalse((folder/"connection-status.json").exists())
            self.assertEqual(lock.stat().st_size,0)
        finally:
            release.write_text('done')
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        dto=publish_connection_status(report,data,now=NOW/1000)
        self.assertEqual(dto["state"],"READ_ONLY_VERIFIED")

    def test_linked_cache_lock_is_rejected_without_touching_other_file(self):
        report,_,_=self.run_audit()
        data=self.folder/"linked-data";folder=data/"live-preproduction";folder.mkdir(parents=True)
        other=self.folder/"unrelated";other.write_bytes(b'0')
        os.link(other,folder/"connection-status.json.lock")
        with self.assertRaisesRegex(LiveError,"LINK_BLOCKED"):
            publish_connection_status(report,data,now=NOW/1000)
        self.assertEqual(other.read_bytes(),b'0')
        self.assertFalse((folder/"connection-status.json").exists())


class AccountLinkCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/"scripts/audit_live_account.py"
        spec=importlib.util.spec_from_file_location("isolated_account_link_cli",path)
        cls.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_link_guard_is_before_artifacts_and_provider_calls(self):
        cases=[(["--verify-account-link","--scope","SPOT_LIVE"],{"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Future")}),
               (["--publish-connection-status"],{}),
               (["--verify-account-link","--publish-connection-status"],{"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Future")}),
               (["--verify-account-link"],{"SPOT_LIVE":credentials("Spot")}),
               (["--verify-account-link"],{"SPOT_LIVE":credentials("Same"),"FUTURES_LIVE":credentials("Same")})]
        import contextlib
        for extra,pairs in cases:
            captured=io.StringIO()
            with patch.object(self.module,"os",SimpleNamespace(name="nt",environ={})), \
                    patch.object(self.module,"credentials_from_environment",return_value=pairs), \
                    patch.object(self.module,"EncryptedAuditStore") as store, \
                    patch.object(self.module,"LiveReadOnlyTransport") as network, \
                    patch.object(self.module,"publish_connection_status") as writer, \
                    contextlib.redirect_stdout(captured):
                result=self.module.main(["--ack-read-only","--output-dir","unused-synthetic",*extra])
            self.assertEqual(result,2)
            store.assert_not_called();network.assert_not_called();writer.assert_not_called()
            self.assertFalse(json.loads(captured.getvalue())["execution_enabled"])


    def test_link_observation_and_cache_publication_require_separate_explicit_options(self):
        import contextlib
        pairs={"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Futures")}
        report={"status":"SCOPED_OBSERVATION","wallets":{scope:{} for scope in pairs},"calls":4,
                "account_link":{"status":"SAME_ACCOUNT_OBSERVED"}}
        for publish in (False,True):
            captured=io.StringIO()
            vault=FakeVault([pairs,pairs])
            with patch.object(self.module,"os",SimpleNamespace(name="nt",environ={})), \
                    patch.object(self.module,"credentials_from_environment",return_value=pairs), \
                    patch("trader.live_credentials.LiveCredentialVault",return_value=vault), \
                    patch.object(self.module,"audit_directory",return_value=Path("synthetic-audit")), \
                    patch.object(self.module,"EncryptedAuditStore"), \
                    patch.object(self.module,"LiveReadOnlyTransport") as transport, \
                    patch.object(self.module,"LiveAccountAudit") as audit, \
                    patch.object(self.module,"publish_connection_status",return_value={"state":"READ_ONLY_VERIFIED"}) as writer, \
                    contextlib.redirect_stdout(captured):
                audit.return_value.run.return_value=report
                extra=["--publish-connection-status","--vault","synthetic-vault.dpapi"] if publish else []
                result=self.module.main(["--ack-read-only","--output-dir","unused-synthetic","--verify-account-link",*extra])
                self.assertEqual(result,0)
                self.assertIs(audit.call_args.kwargs["verify_account_link"],True)
                self.assertEqual(transport.call_args.args[0],pairs)
                if publish:
                    writer.assert_called_once_with(report,self.module.ROOT/"data")
                    self.assertEqual(vault.events,["read","lock","locked-read","unlock"])
                else:writer.assert_not_called()
            output=json.loads(captured.getvalue())
            self.assertEqual(output["account_link_status"],"SAME_ACCOUNT_OBSERVED")
            self.assertEqual("connection_status" in output,publish)
            self.assertFalse(output["execution_enabled"])
            self.assertFalse(output["financial_authorization"])
            self.assertNotIn(str(UID),captured.getvalue())

    def test_changed_key_or_secret_of_either_scope_blocks_old_audit_publication(self):
        import contextlib
        original={"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Futures")}
        report={"status":"SCOPED_OBSERVATION","wallets":{scope:{} for scope in original},"calls":4,
                "account_link":{"status":"SAME_ACCOUNT_OBSERVED"}}
        cases=[]
        for scope in original:
            for attribute in ("api_key","api_secret"):
                pair=original[scope]
                changed=LiveCredentials(pair.api_key+"Changed" if attribute=="api_key" else pair.api_key,
                                        pair.api_secret+"Changed" if attribute=="api_secret" else pair.api_secret)
                cases.append(original|{scope:changed})
        cases.append({"SPOT_LIVE":original["SPOT_LIVE"]})
        for current in cases:
            captured=io.StringIO();vault=FakeVault([original,current])
            with patch.object(self.module,"os",SimpleNamespace(name="nt",environ={})), \
                    patch("trader.live_credentials.LiveCredentialVault",return_value=vault), \
                    patch.object(self.module,"audit_directory",return_value=Path("synthetic-audit")), \
                    patch.object(self.module,"EncryptedAuditStore"), \
                    patch.object(self.module,"LiveReadOnlyTransport"), \
                    patch.object(self.module,"LiveAccountAudit") as audit, \
                    patch.object(self.module,"publish_connection_status") as writer, \
                    contextlib.redirect_stdout(captured):
                audit.return_value.run.return_value=report
                result=self.module.main(["--ack-read-only","--output-dir","unused-synthetic",
                    "--verify-account-link","--publish-connection-status","--vault","synthetic-vault.dpapi"])
            self.assertEqual(result,2);writer.assert_not_called()
            self.assertEqual(json.loads(captured.getvalue())["code"],"LIVE_CREDENTIALS_CHANGED_DURING_AUDIT")
            self.assertEqual(vault.events,["read","lock","locked-read","unlock"])
            for pair in (*original.values(),*current.values()):
                self.assertNotIn(pair.api_key,captured.getvalue());self.assertNotIn(pair.api_secret,captured.getvalue())

    def test_cache_writer_is_entered_only_while_vault_lock_is_held(self):
        import contextlib
        pairs={"SPOT_LIVE":credentials("Spot"),"FUTURES_LIVE":credentials("Futures")}
        report={"status":"SCOPED_OBSERVATION","wallets":{scope:{} for scope in pairs},"calls":4,
                "account_link":{"status":"SAME_ACCOUNT_OBSERVED"}}
        vault=FakeVault([pairs,pairs])
        def writer(*args):
            self.assertTrue(vault.locked)
            vault.events.append("cache-lock-after-vault")
            return {"state":"READ_ONLY_VERIFIED"}
        with patch.object(self.module,"os",SimpleNamespace(name="nt",environ={})), \
                patch("trader.live_credentials.LiveCredentialVault",return_value=vault), \
                patch.object(self.module,"audit_directory",return_value=Path("synthetic-audit")), \
                patch.object(self.module,"EncryptedAuditStore"), \
                patch.object(self.module,"LiveReadOnlyTransport"), \
                patch.object(self.module,"LiveAccountAudit") as audit, \
                patch.object(self.module,"publish_connection_status",side_effect=writer), \
                contextlib.redirect_stdout(io.StringIO()):
            audit.return_value.run.return_value=report
            result=self.module.main(["--ack-read-only","--output-dir","unused-synthetic",
                "--verify-account-link","--publish-connection-status","--vault","synthetic-vault.dpapi"])
        self.assertEqual(result,0)
        self.assertEqual(vault.events,["read","lock","locked-read","cache-lock-after-vault","unlock"])


class FakeVault:
    """Synthetic local race scheduling; no filesystem or credentials are read."""
    def __init__(self,snapshots):
        self.snapshots=list(snapshots);self.locked=False;self.events=[]

    def read(self):
        self.events.append("locked-read" if self.locked else "read")
        return dict(self.snapshots.pop(0))

    @contextmanager
    def _write_lock(self):
        self.locked=True;self.events.append("lock")
        try:yield
        finally:self.locked=False;self.events.append("unlock")


if __name__=="__main__":
    unittest.main()
