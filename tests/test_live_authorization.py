"""Synthetic protected approval fixtures, never an operating authority issuer."""
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import trader.live_authorization as auth
from trader.central_admission import Scope
from trader.live_authorization import AuthorizationError,LocalAuthorizationProvider,financial_fingerprint
from trader.live_execution_runtime import ConfirmedPosition
from trader.live_transport import LiveOrderIntent
from tests.test_central_admission import policy,NOW,U

SOURCE=Path(__file__).resolve().parents[1]


class FakeProtection:
    def protect(self,raw,purpose): return purpose.encode()+b"\0"+raw
    def unprotect(self,raw,purpose):
        prefix=purpose.encode()+b"\0"
        if not raw.startswith(prefix): raise ValueError()
        return raw[len(prefix):]


class LiveAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); (self.root/"trader").mkdir()
        names=set(auth._CODE)|{p.name for p in (SOURCE/"trader").glob("live_*.py")}
        for name in names: (self.root/"trader"/name).write_bytes((SOURCE/"trader"/name).read_bytes())
        # Isolated future adapter fixture only. The real engine has no marker.
        with (self.root/"trader/engine.py").open("a") as handle: handle.write("\nLIVE_EXECUTION_ADAPTER_PROTOCOL=1\n")
        (self.root/"config.toml").write_bytes((SOURCE/"config.toml").read_bytes())
        self.now=NOW
        self.provider=LocalAuthorizationProvider(self.root,protection=FakeProtection(),clock=lambda:self.now)
        self.scope=Scope("SYNTHETIC_SPOT_ACCOUNT","SPOT_LIVE","USDT")
        self.policy=replace(policy(),approval_reference="OWNER_REVIEW_1",approved_at=NOW-10,
            engine_limits=(("SPOT",900*U,900*U,30*U),))
        globals={key:getattr(self.policy,key) for key in auth._GLOBALS if key not in {"asset_limits","correlation_limits"}}
        globals.update(asset_limits=[list(x) for x in self.policy.asset_limits],correlation_limits=[list(x) for x in self.policy.correlation_limits])
        self.review={"schema":1,"approval_id":"OWNER_REVIEW_1","owner_confirmation":auth.OWNER_CONFIRMATION,
            "approved_at":NOW-20,"expires_at":NOW+3600,"active":True,
            "financial_fingerprint":financial_fingerprint(self.root),"required_observation_days":30,
            "hmac_key_hex":"a1"*32,"global_limits":globals,
            "wallets":[{"scope":asdict(self.scope),"policy":asdict(self.policy),"credential_fingerprint":"b"*64}]}
        report=self.root/"data/evidence/retained.json"; report.parent.mkdir(parents=True)
        report.write_text('{"synthetic_fixture":true}')
        receipt={"path":"data/evidence/retained.json","sha256":hashlib.sha256(report.read_bytes()).hexdigest(),"observed_at":NOW-2}
        self.ready={"schema":1,"approval_id":"OWNER_REVIEW_1","financial_fingerprint":self.review["financial_fingerprint"],
            "observed_at":NOW-1,"expires_at":NOW+300,"policy_fingerprints":{"SPOT_LIVE":self.policy.fingerprint},
            "credential_fingerprints":{"SPOT_LIVE":"b"*64},"qualified_days":{"SPOT_LIVE":30},
            "checks":{key:True for key in auth.READY_CHECKS},"evidence":{key:receipt for key in auth.READY_CHECKS}}

    def write_fixture(self):
        self.provider.approval_store.write(self.review,replace=True)
        self.provider.readiness_store.write(self.ready,replace=True)

    def intent(self,purpose="ENTRY"):
        fields={"symbol":"BTCUSDT","side":"BUY" if purpose=="ENTRY" else "SELL","type":"MARKET",
            "quantity":"0.001","newClientOrderId":"synthetic-client"}
        return LiveOrderIntent("SPOT_LIVE",purpose,"POST","/api/v3/order",tuple(fields.items()),
            "synthetic-client",self.policy.fingerprint,int((self.now+20)*1000))

    def test_absent_records_keys_or_generic_boolean_do_not_authorize(self):
        self.assertFalse(self.provider.authorized())
        self.assertFalse(self.provider.status()["owner_activation_authorized"])
        self.assertFalse((self.root/auth.APPROVAL_PATH).exists())
        self.provider.approval_store.write({"approved":True,"api_key":"not-authority"},replace=True)
        self.assertFalse(self.provider.authorized())
        with self.assertRaises(AuthorizationError): self.provider.capability(self.scope,self.policy.fingerprint,"a"*64,self.now)

    def test_exact_hmac_capability_binds_scope_policy_terms_approval_and_revocation(self):
        self.write_fixture(); self.assertTrue(self.provider.authorized())
        cap=self.provider.capability(self.scope,self.policy.fingerprint,"a"*64,self.now)
        bindings={"scope":self.scope,"policy_fingerprint":self.policy.fingerprint,"terms_fingerprint":"a"*64,"now":self.now}
        self.assertTrue(self.provider.verify(cap,**bindings))
        self.assertFalse(self.provider.verify(replace(cap,terms_fingerprint="c"*64),**bindings))
        self.assertFalse(self.provider.verify(replace(cap,proof="0"*64),**bindings))
        self.review["active"]=False; self.write_fixture()
        self.assertFalse(self.provider.verify(cap,**bindings))

    def test_readiness_requires_qualified_days_retained_evidence_and_each_check(self):
        self.write_fixture()
        self.ready["qualified_days"]["SPOT_LIVE"]=29; self.write_fixture()
        self.assertFalse(self.provider.authorized())
        self.ready["qualified_days"]["SPOT_LIVE"]=30
        self.ready["checks"]["cashflows_complete"]=False; self.write_fixture()
        self.assertFalse(self.provider.authorized())
        self.ready["checks"]["cashflows_complete"]=True; self.write_fixture()
        (self.root/"data/evidence/retained.json").write_text("changed")
        self.assertFalse(self.provider.authorized())

    def test_ui_version_comments_do_not_change_financial_semantics_but_execution_does(self):
        self.write_fixture(); before=financial_fingerprint(self.root)
        (self.root/"web").mkdir(); (self.root/"web/index.html").write_text("UI revision")
        (self.root/"pyproject.toml").write_text('[project]\nversion="9.9.9"')
        with (self.root/"trader/engine.py").open("a") as handle: handle.write("\n# cosmetic comment\n")
        self.assertEqual(before,financial_fingerprint(self.root))
        self.assertTrue(self.provider.authorized())
        with (self.root/"trader/engine.py").open("a") as handle: handle.write("\nCRITICAL_POLICY_CHANGE=1\n")
        self.assertFalse(self.provider.authorized())

    def test_runtime_marker_and_future_or_expired_readiness_fail_closed(self):
        self.write_fixture()
        engine=self.root/"trader/engine.py"
        engine.write_text(engine.read_text().replace("LIVE_EXECUTION_ADAPTER_PROTOCOL=1","LIVE_EXECUTION_ADAPTER_PROTOCOL=0"))
        self.assertFalse(self.provider.authorized())
        # Maintenance mode proof can remain inspectable without authorizing entry.
        self.assertTrue(self.provider.authorized(require_ready=False))

    def test_joint_wallet_caps_and_individual_keys_are_enforced_without_pooling(self):
        future=Scope("SYNTHETIC_FUTURES_ACCOUNT","FUTURES_LIVE","USDT")
        future_policy=replace(self.policy,engine_limits=(("FUTURES",900*U,900*U,30*U),))
        self.review["wallets"].append({"scope":asdict(future),"policy":asdict(future_policy),"credential_fingerprint":"c"*64})
        self.write_fixture()
        self.assertFalse(self.provider.authorized(require_ready=False))
        # Explicitly extend ONLY this synthetic test's portfolio envelope.
        for key in ("capital_budget_units","gross_limit_units","stop_risk_limit_units","daily_loss_limit_units",
                    "weekly_loss_limit_units","drawdown_limit_units","max_positions"):
            self.review["global_limits"][key]*=2
        for key in ("asset_limits","correlation_limits"):
            for row in self.review["global_limits"][key]: row[1]*=2; row[2]*=2
        self.write_fixture(); self.assertTrue(self.provider.authorized(require_ready=False))
        self.review["wallets"][1]["credential_fingerprint"]="b"*64; self.write_fixture()
        self.assertFalse(self.provider.authorized(require_ready=False))

    def test_entry_grant_binds_exact_claim_and_cannot_be_retargeted(self):
        self.write_fixture(); intent=self.intent()
        cap=self.provider.capability(self.scope,self.policy.fingerprint,"a"*64,self.now)
        grant=self.provider.grant(intent,claim_id="CLAIM_1",reservation_id="TICKET_1",terms_fingerprint="a"*64,capability=cap,now=self.now)
        claim={"scope":asdict(self.scope),"policy_fingerprint":self.policy.fingerprint,"terms_fingerprint":"a"*64,
            "execution_plan_fingerprint":intent.digest(),"ticket_id":"TICKET_1","claim_id":"CLAIM_1",
            "state":"SUBMITTING","transport_consumed":False}
        self.assertTrue(self.provider.verify_grant(grant,intent,claim=claim,now=self.now))
        self.assertFalse(self.provider.verify_grant(grant,intent,claim={**claim,"claim_id":"OTHER"},now=self.now))
        self.assertFalse(self.provider.verify_grant(grant,intent,claim={**claim,"transport_consumed":True},now=self.now))
        self.assertFalse(self.provider.verify_grant(replace(grant,reservation_id="OTHER"),intent,claim=claim,now=self.now))

    def test_protective_close_ignores_entry_readiness_but_cannot_increase_quantity(self):
        self.write_fixture(); intent=self.intent("CLOSE")
        position=ConfirmedPosition("TICKET_1",self.scope,"BTCUSDT","LONG","0.001","100000","0.001","100",
            self.now,"d"*64,True)
        self.review["active"]=False; self.review["expires_at"]=NOW-1
        self.provider.approval_store.write(self.review,replace=True)
        self.provider.readiness_store.path.unlink()
        grant=self.provider.protective_grant(intent,position,now=self.now)
        self.assertTrue(self.provider.verify_protective_grant(grant,intent,position,now=self.now))
        self.assertFalse(self.provider.authorized())
        oversized=replace(intent,fields=tuple((k,"0.002" if k=="quantity" else v) for k,v in intent.fields))
        with self.assertRaises(AuthorizationError): self.provider.protective_grant(oversized,position,now=self.now)


if __name__=="__main__": unittest.main()
