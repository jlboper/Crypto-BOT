"""Protected local owner approval and exact, short-lived LIVE capabilities.

No approval/configuration/activation writer exists here. Credentials never grant
authority. A separately reviewed owner workflow must provision BOTH purpose-bound
DPAPI records after explicit numerical limits, evidence review and activation.
Absent/invalid records fail closed. The shipped installation provisions neither.

Wallet ceilings are statically segregated and sum below the approved portfolio
ceilings; the authority does not pretend two exchange accounts share an atomic
transaction. No transfer, rebalance, risk increase or 30-day automatic activation.
Transport imports are lazy: the independent supervisor needs only this module,
central_admission, local_protection and the standard library.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, fields, replace
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
import tomllib

from .central_admission import AdmissionPolicy, OperatingCapability, Scope, MAX_UNITS
from .local_protection import ProtectedStore, PURPOSES

APPROVAL_PATH="data/live-preproduction/authorization.dpapi"
READINESS_PATH="data/live-preproduction/readiness.dpapi"
OWNER_CONFIRMATION="REVIEWED_NUMERIC_LIMITS_AND_EXPLICIT_LIVE_ACTIVATION"
READY_CHECKS=("account_identity","balances_reconciled","orders_reconciled","cashflows_complete",
    "permissions_least_privilege","withdrawals_disabled","native_protections","recovery_drills",
    "cost_feasibility","cohort_evidence","code_reviewed","operational_adapter_integrated")
_CODE=("engine.py","strategy.py","indicators.py","futures_forward.py","futures_strategy.py",
    "ai_advisor.py","risk_control.py","native_protection.py","central_admission.py","config.py","local_protection.py")
_HEX=re.compile(r"[a-f0-9]{64}\Z",re.ASCII)
_ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z",re.ASCII)
_GLOBALS=("capital_budget_units","gross_limit_units","stop_risk_limit_units",
    "per_trade_stop_risk_limit_units","daily_loss_limit_units","weekly_loss_limit_units",
    "drawdown_limit_units","max_positions","max_leverage_milli","asset_limits","correlation_limits")
_SEMANTIC_CACHE={}


class AuthorizationError(ValueError):
    """Closed code; never exposes protected content or provider responses."""


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)


def _hash(value): return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _at(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<253402300799:
        raise AuthorizationError("AUTHORIZATION_TIME_REQUIRED")
    return float(value)


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value): raise AuthorizationError("AUTHORIZATION_ID_REQUIRED")


def _hex(value):
    if type(value) is not str or not _HEX.fullmatch(value): raise AuthorizationError("AUTHORIZATION_DIGEST_REQUIRED")


def _keys(value,expected):
    if type(value) is not dict or set(value)!=set(expected): raise AuthorizationError("CLOSED_AUTHORIZATION_SCHEMA_REQUIRED")


def _money(value):
    if type(value) is not int or not 0<value<=MAX_UNITS: raise AuthorizationError("EXPLICIT_INTEGER_LIMIT_REQUIRED")


def _regular(root,path):
    root=Path(root).resolve()
    path=Path(path)
    if not path.resolve().is_relative_to(root) or path.resolve()==root:
        raise AuthorizationError("AUTHORIZATION_SOURCE_ESCAPED_ROOT")
    for part in (path,*path.parents):
        if part==root: break
        if part.is_symlink() or getattr(part,"is_junction",lambda:False)():
            raise AuthorizationError("LINKED_AUTHORIZATION_SOURCE")
    if not path.is_file() or path.stat().st_size>2_097_152:
        raise AuthorizationError("AUTHORIZATION_SOURCE_UNAVAILABLE")
    return path


def financial_fingerprint(source):
    """Financial executable AST/config only: UI, documentation/version excluded."""
    root=Path(source).resolve()
    names=set(_CODE)|{p.name for p in (root/"trader").glob("live_*.py")}
    if not {"live_authorization.py","live_execution_runtime.py","live_transport.py"}<=names:
        raise AuthorizationError("FINANCIAL_IMPLEMENTATION_INCOMPLETE")
    digests={}
    for name in sorted(names):
        # Re-read and hash exact source bytes on EVERY call. Cache only the
        # expensive AST normalization keyed by content, never authorization,
        # timestamps, policy, readiness or file metadata. Bound memory to hashes.
        raw=_regular(root,root/"trader"/name).read_bytes()
        raw_digest=hashlib.sha256(raw).hexdigest()
        semantic=_SEMANTIC_CACHE.get(raw_digest)
        if semantic is None:
            tree=ast.parse(raw.decode("utf-8-sig"))
            for node in ast.walk(tree):
                body=getattr(node,"body",None)
                if (isinstance(body,list) and body and isinstance(body[0],ast.Expr)
                        and isinstance(body[0].value,ast.Constant) and isinstance(body[0].value.value,str)):
                    del body[0]
            semantic=hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()
            if len(_SEMANTIC_CACHE)>=128: _SEMANTIC_CACHE.clear()
            _SEMANTIC_CACHE[raw_digest]=semantic
        digests[name]=semantic
    raw=tomllib.loads(_regular(root,root/"config.toml").read_text(encoding="utf-8-sig"))
    config={key:raw[key] for key in ("risk","strategy","ai","futures_testnet") if key in raw}
    if not {"risk","strategy","ai"}<=config.keys(): raise AuthorizationError("FINANCIAL_SETTINGS_INCOMPLETE")
    config["bot"]={key:raw["bot"][key] for key in ("cycle_seconds","timeframe","universe_size","protection_seconds") if key in raw["bot"]}
    # Bind the actual configured model override without loading/exporting any
    # credential. Environment is already the supervisor's trusted process input.
    model=os.getenv("OPENAI_MODEL")
    if model is None:
        for name in (".env.local",".env"):
            env_file=root/name
            if not env_file.is_file(): continue
            for line in _regular(root,env_file).read_text(encoding="utf-8-sig").splitlines():
                key,separator,value=line.partition("=")
                if separator and key.strip()=="OPENAI_MODEL":
                    model=value.strip().strip('"\''); break
            if model is not None: break
    if model is not None:
        if type(model) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}",model):
            raise AuthorizationError("ACTUAL_AI_MODEL_ID_REQUIRED")
        config["ai"]={**config["ai"],"model":model}
    return _hash({"protocol":"FINANCIAL_SEMANTICS_V1","source":digests,"configuration":config})


def _policy(value):
    _keys(value,{f.name for f in fields(AdmissionPolicy)})
    value=dict(value)
    for key in ("engine_limits","asset_limits","correlation_limits"):
        if type(value[key]) is not list: raise AuthorizationError("IMMUTABLE_REVIEW_LIMITS_REQUIRED")
        value[key]=tuple(tuple(row) for row in value[key])
    try: return AdmissionPolicy(**value)
    except (ValueError,TypeError): raise AuthorizationError("INVALID_REVIEWED_POLICY") from None


def _limits(rows,*,symbol=False):
    if type(rows) is not list or not 1<=len(rows)<=64: raise AuthorizationError("EXPLICIT_PORTFOLIO_LIMITS_REQUIRED")
    result={}
    for row in rows:
        if type(row) is not list or len(row)!=3: raise AuthorizationError("EXPLICIT_PORTFOLIO_LIMITS_REQUIRED")
        key,gross,risk=row
        if symbol:
            if type(key) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}USDT",key): raise AuthorizationError("ASSET_LIMIT_REQUIRED")
        else: _id(key)
        _money(gross); _money(risk)
        if key in result: raise AuthorizationError("DUPLICATE_PORTFOLIO_LIMIT")
        result[key]=(gross,risk)
    return result


class LocalAuthorizationProvider:
    """Loads reviewed authority; cannot create it from keys, flags or defaults."""
    def __init__(self,source,*,protection=None,clock=time.time):
        self.source=Path(source).resolve()
        self.clock=clock
        self.approval_store=ProtectedStore(self.source/APPROVAL_PATH,PURPOSES[1],protection=protection)
        self.readiness_store=ProtectedStore(self.source/READINESS_PATH,PURPOSES[2],protection=protection)

    def _review(self,now,*,protective=False):
        try:
            value=self.approval_store.read()
            _keys(value,("schema","approval_id","owner_confirmation","approved_at","expires_at","active",
                "financial_fingerprint","required_observation_days","hmac_key_hex","global_limits","wallets"))
            if type(value["schema"]) is not int or value["schema"]!=1 or value["owner_confirmation"]!=OWNER_CONFIRMATION:
                raise AuthorizationError("EXPLICIT_OWNER_REVIEW_REQUIRED")
            _id(value["approval_id"]); _at(value["approved_at"]); _at(value["expires_at"])
            _hex(value["financial_fingerprint"]); _hex(value["hmac_key_hex"])
            if (type(value["active"]) is not bool or value["expires_at"]<=value["approved_at"]
                    or value["approved_at"]>now or type(value["required_observation_days"]) is not int
                    or not 30<=value["required_observation_days"]<=365):
                raise AuthorizationError("EXPLICIT_OWNER_REVIEW_REQUIRED")
            if not protective and (value["active"] is not True or now>=value["expires_at"]):
                raise AuthorizationError("OWNER_ACTIVATION_ABSENT_OR_EXPIRED")
            global_limits=value["global_limits"]; _keys(global_limits,_GLOBALS)
            for key in _GLOBALS:
                if key not in {"asset_limits","correlation_limits"}: _money(global_limits[key])
            if not 1<=global_limits["max_positions"]<=100 or not 1000<=global_limits["max_leverage_milli"]<=125000:
                raise AuthorizationError("INVALID_GLOBAL_COUNTS_OR_LEVERAGE")
            if global_limits["per_trade_stop_risk_limit_units"]>global_limits["stop_risk_limit_units"]:
                raise AuthorizationError("PER_TRADE_CAP_EXCEEDS_GLOBAL_RISK")
            group_limits={"asset_limits":_limits(global_limits["asset_limits"],symbol=True),
                          "correlation_limits":_limits(global_limits["correlation_limits"])}
            if type(value["wallets"]) is not list or not 1<=len(value["wallets"])<=2:
                raise AuthorizationError("SEPARATE_LIVE_WALLETS_REQUIRED")
            wallets={}
            for row in value["wallets"]:
                _keys(row,("scope","policy","credential_fingerprint"))
                _keys(row["scope"],("account_id","environment","currency"))
                scope=Scope(**row["scope"]); policy=_policy(row["policy"])
                _hex(row["credential_fingerprint"])
                expected="SPOT" if scope.environment=="SPOT_LIVE" else "FUTURES"
                if (scope.environment not in {"SPOT_LIVE","FUTURES_LIVE"} or scope.environment in wallets
                        or policy.approval_reference!=value["approval_id"]
                        or policy.approved_at<value["approved_at"] or policy.approved_at>now
                        or {x[0] for x in policy.engine_limits}!={expected}):
                    raise AuthorizationError("REVIEWED_WALLET_SCOPE_OR_POLICY_MISMATCH")
                wallets[scope.environment]=(scope,policy,row["credential_fingerprint"])
            if len({x[2] for x in wallets.values()})!=len(wallets):
                raise AuthorizationError("DEDICATED_SEPARATE_LIVE_KEYS_REQUIRED")
            # No dynamic capital pooling: the maximum permitted simultaneous
            # state in separate wallets remains inside every global ceiling.
            summed=("capital_budget_units","gross_limit_units","stop_risk_limit_units",
                    "daily_loss_limit_units","weekly_loss_limit_units","drawdown_limit_units","max_positions")
            for key in summed:
                if sum(getattr(row[1],key) for row in wallets.values())>global_limits[key]:
                    raise AuthorizationError("SEGREGATED_WALLET_LIMITS_EXCEED_PORTFOLIO")
            for _,policy,_ in wallets.values():
                if (policy.max_leverage_milli>global_limits["max_leverage_milli"]
                        or policy.per_trade_stop_risk_limit_units>global_limits["per_trade_stop_risk_limit_units"]):
                    raise AuthorizationError("WALLET_CAN_INCREASE_GLOBAL_POLICY")
            for kind,limits in group_limits.items():
                sums={}
                for _,policy,_ in wallets.values():
                    for key,gross,risk in getattr(policy,kind):
                        sums[key]=(sums.get(key,(0,0))[0]+gross,sums.get(key,(0,0))[1]+risk)
                for key,(gross,risk) in sums.items():
                    if key not in limits or gross>limits[key][0] or risk>limits[key][1]:
                        raise AuthorizationError("WALLET_GROUP_LIMITS_EXCEED_PORTFOLIO")
            return value,wallets
        except AuthorizationError: raise
        except Exception: raise AuthorizationError("PROTECTED_OWNER_REVIEW_UNAVAILABLE") from None

    def _ready(self,review,wallets,now):
        try:
            adapter=ast.parse(_regular(self.source,self.source/"trader/engine.py").read_text(encoding="utf-8-sig"))
            marker=any(isinstance(node,ast.Assign) and type(getattr(node.value,"value",None)) is int
                and node.value.value==1 and any(isinstance(target,ast.Name) and target.id=="LIVE_EXECUTION_ADAPTER_PROTOCOL"
                    for target in node.targets) for node in adapter.body)
            if not marker: raise AuthorizationError("LIVE_RUNTIME_ADAPTER_NOT_COMMISSIONED")
            value=self.readiness_store.read()
            _keys(value,("schema","approval_id","financial_fingerprint","observed_at","expires_at",
                "policy_fingerprints","credential_fingerprints","qualified_days","checks","evidence"))
            if (type(value["schema"]) is not int or value["schema"]!=1
                    or value["approval_id"]!=review["approval_id"]
                    or value["financial_fingerprint"]!=review["financial_fingerprint"]
                    or value["financial_fingerprint"]!=financial_fingerprint(self.source)
                    or not _at(value["observed_at"])<=now<_at(value["expires_at"])
                    or value["expires_at"]-value["observed_at"]>86400):
                raise AuthorizationError("READINESS_ABSENT_STALE_OR_SEMANTICS_CHANGED")
            for key in ("policy_fingerprints","credential_fingerprints","qualified_days"):
                _keys(value[key],wallets)
            for environment,(_,policy,fingerprint) in wallets.items():
                days=value["qualified_days"][environment]
                if (value["policy_fingerprints"][environment]!=policy.fingerprint
                        or value["credential_fingerprints"][environment]!=fingerprint
                        or type(days) is not int or days<review["required_observation_days"]):
                    raise AuthorizationError("WALLET_READINESS_EVIDENCE_INCOMPLETE")
            _keys(value["checks"],READY_CHECKS); _keys(value["evidence"],READY_CHECKS)
            if any(value["checks"][key] is not True for key in READY_CHECKS):
                raise AuthorizationError("READINESS_CHECK_NOT_PASSED")
            for key in READY_CHECKS:
                receipt=value["evidence"][key]; _keys(receipt,("path","sha256","observed_at"))
                _hex(receipt["sha256"])
                if (type(receipt["path"]) is not str or not receipt["path"].startswith("data/")
                        or ".." in Path(receipt["path"]).parts
                        or not _at(receipt["observed_at"])<=value["observed_at"]):
                    raise AuthorizationError("RETAINED_READINESS_RECEIPT_REQUIRED")
                path=_regular(self.source,self.source/receipt["path"])
                if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt["sha256"]:
                    raise AuthorizationError("RETAINED_READINESS_RECEIPT_CHANGED")
            return value
        except AuthorizationError: raise
        except Exception: raise AuthorizationError("PROTECTED_READINESS_UNAVAILABLE") from None

    def _entry_context(self,now):
        now=_at(now); review,wallets=self._review(now)
        ready=self._ready(review,wallets,now)
        return review,wallets,ready

    def authorized(self,*,now=None,require_ready=True):
        try:
            stamp=_at(self.clock() if now is None else now)
            review,wallets=self._review(stamp)
            if require_ready: self._ready(review,wallets,stamp)
            return True
        except Exception: return False

    def policies(self,*,now=None):
        _,wallets,_=self._entry_context(self.clock() if now is None else now)
        return tuple(wallets[key] for key in sorted(wallets))

    @staticmethod
    def _sign(review,kind,payload):
        return hmac.new(bytes.fromhex(review["hmac_key_hex"]),_json({"kind":kind,"payload":payload}).encode("ascii"),hashlib.sha256).hexdigest()

    def capability(self,scope,policy_fingerprint,terms_fingerprint,now):
        review,wallets,ready=self._entry_context(now)
        row=wallets.get(scope.environment) if isinstance(scope,Scope) else None
        _hex(terms_fingerprint)
        if row is None or scope!=row[0] or policy_fingerprint!=row[1].fingerprint:
            raise AuthorizationError("EXACT_REVIEWED_WALLET_POLICY_REQUIRED")
        cap=OperatingCapability(scope,policy_fingerprint,terms_fingerprint,review["approval_id"],
            float(now),min(float(now)+30,review["expires_at"],ready["expires_at"]),"PENDING")
        payload=asdict(cap); payload.pop("proof")
        return replace(cap,proof=self._sign(review,"CAPABILITY",payload))

    def verify_capability(self,capability,*,scope,policy_fingerprint,terms_fingerprint,now):
        try:
            review,wallets,_=self._entry_context(now)
            row=wallets.get(scope.environment)
            if (type(capability) is not OperatingCapability or row is None or row[0]!=scope
                    or row[1].fingerprint!=policy_fingerprint or capability.scope!=scope
                    or capability.policy_fingerprint!=policy_fingerprint or capability.terms_fingerprint!=terms_fingerprint
                    or capability.approval_id!=review["approval_id"] or not capability.issued_at<=now<capability.expires_at
                    or capability.expires_at-capability.issued_at>30): return False
            payload=asdict(capability); payload.pop("proof")
            return hmac.compare_digest(capability.proof,self._sign(review,"CAPABILITY",payload))
        except Exception: return False

    def verify(self,capability,*,scope,policy_fingerprint,terms_fingerprint,now):
        return self.verify_capability(capability,scope=scope,policy_fingerprint=policy_fingerprint,
                                     terms_fingerprint=terms_fingerprint,now=now)

    def grant(self,intent,*,claim_id,reservation_id,terms_fingerprint,capability,now):
        from .live_transport import ExecutionGrant,LiveOrderIntent
        if type(intent) is not LiveOrderIntent or intent.purpose!="ENTRY":
            raise AuthorizationError("EXACT_ENTRY_INTENT_REQUIRED")
        review,wallets,_=self._entry_context(now); row=wallets.get(intent.scope)
        _id(claim_id); _id(reservation_id)
        if row is None or not self.verify_capability(capability,scope=row[0],policy_fingerprint=intent.policy_digest,
                terms_fingerprint=terms_fingerprint,now=now):
            raise AuthorizationError("VALID_EXACT_ENTRY_CAPABILITY_REQUIRED")
        if not int(now*1000)<intent.expires_utc_ms<=int(capability.expires_at*1000):
            raise AuthorizationError("ENTRY_GRANT_EXPIRY_INVALID")
        grant=ExecutionGrant(intent.digest(),secrets.token_hex(24),reservation_id,review["approval_id"],
            intent.policy_digest,row[2],intent.expires_utc_ms,"PENDING")
        payload={**asdict(grant),"claim_id":claim_id,"terms_fingerprint":terms_fingerprint}; payload.pop("proof")
        return replace(grant,proof=self._sign(review,"ENTRY_GRANT",payload))

    def verify_grant(self,grant,intent,*,claim,now):
        try:
            from .live_transport import ExecutionGrant,LiveOrderIntent
            review,wallets,_=self._entry_context(now); row=wallets.get(intent.scope)
            if (type(grant) is not ExecutionGrant or type(intent) is not LiveOrderIntent or intent.purpose!="ENTRY"
                    or row is None or grant.authorization_id!=review["approval_id"]
                    or grant.intent_digest!=intent.digest() or grant.policy_digest!=row[1].fingerprint
                    or intent.policy_digest!=row[1].fingerprint or grant.account_fingerprint!=row[2]
                    or grant.expires_utc_ms!=intent.expires_utc_ms or not int(now*1000)<grant.expires_utc_ms<=int(now*1000)+30000
                    or claim.get("scope")!=asdict(row[0]) or claim.get("state")!="SUBMITTING"
                    or claim.get("transport_consumed") is not False
                    or claim.get("execution_plan_fingerprint")!=intent.digest()
                    or claim.get("policy_fingerprint")!=grant.policy_digest or claim.get("ticket_id")!=grant.reservation_id): return False
            payload={**asdict(grant),"claim_id":claim["claim_id"],"terms_fingerprint":claim["terms_fingerprint"]}; payload.pop("proof")
            return hmac.compare_digest(grant.proof,self._sign(review,"ENTRY_GRANT",payload))
        except Exception: return False

    def _protective_context(self,intent,position,now):
        from .live_transport import LiveOrderIntent
        review,wallets=self._review(_at(now),protective=True)
        row=wallets.get(getattr(intent,"scope",None))
        if (type(intent) is not LiveOrderIntent or intent.purpose not in {"PROTECT","CLOSE","CANCEL"} or row is None
                or position.scope!=row[0] or intent.policy_digest!=row[1].fingerprint
                or not int(now*1000)<intent.expires_utc_ms<=int(now*1000)+30000
                or not 0<=now-position.observed_at<=row[1].max_data_age_seconds):
            raise AuthorizationError("FRESH_OWNED_PROTECTIVE_POSITION_REQUIRED")
        fields=dict(intent.fields)
        try:
            held=Decimal(position.quantity)
            if intent.purpose=="CANCEL":
                if (not held.is_finite() or held!=0
                        or "symbol" in fields and fields["symbol"]!=position.symbol): raise ValueError()
                return review,row
            quantity=Decimal(fields["quantity"])
            if (not quantity.is_finite() or not held.is_finite() or not 0<quantity<=held
                    or fields.get("symbol")!=position.symbol
                    or fields.get("side")!=("SELL" if position.direction=="LONG" else "BUY")):
                raise ValueError()
        except (ValueError,KeyError,InvalidOperation): raise AuthorizationError("PROTECTIVE_CANNOT_INCREASE_POSITION") from None
        return review,row

    def protective_grant(self,intent,position,*,now):
        from .live_transport import ExecutionGrant
        review,row=self._protective_context(intent,position,now)
        grant=ExecutionGrant(intent.digest(),secrets.token_hex(24),position.ticket_id,review["approval_id"],
            intent.policy_digest,row[2],intent.expires_utc_ms,"PENDING")
        payload={**asdict(grant),"position_fingerprint":position.fingerprint}; payload.pop("proof")
        return replace(grant,proof=self._sign(review,"PROTECTIVE_GRANT",payload))

    def verify_protective_grant(self,grant,intent,position,*,now):
        try:
            from .live_transport import ExecutionGrant
            review,row=self._protective_context(intent,position,now)
            if (type(grant) is not ExecutionGrant or grant.intent_digest!=intent.digest()
                    or grant.reservation_id!=position.ticket_id or grant.authorization_id!=review["approval_id"]
                    or grant.policy_digest!=row[1].fingerprint or grant.account_fingerprint!=row[2]
                    or grant.expires_utc_ms!=intent.expires_utc_ms): return False
            payload={**asdict(grant),"position_fingerprint":position.fingerprint}; payload.pop("proof")
            return hmac.compare_digest(grant.proof,self._sign(review,"PROTECTIVE_GRANT",payload))
        except Exception: return False

    def status(self):
        return {"owner_activation_authorized":self.authorized(),"credentials_grant_authority":False,
                "automatic_thirty_day_activation":False,"approval_writer_available":False}


def operating_mode_authorized(source,*,now=None,require_ready=True):
    return LocalAuthorizationProvider(source).authorized(now=now,require_ready=require_ready)
