"""Segregated production REST capabilities. Nothing in the bot selects these.

Read capability is GET-only. The prepared write capability requires an external,
durable admission authority and an exact, single-use grant for every request.
There is no CLI, configuration switch, environment lookup, transfer, withdrawal,
leverage setter or automatic retry here. Python objects are not a security
boundary against modified application code; the signed application and admission
authority remain the trust boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Protocol
import urllib.error
import urllib.parse
import urllib.request

from trader.account_inventory import _json, InventoryError

HOSTS = {"SPOT_LIVE": "https://api.binance.com", "FUTURES_LIVE": "https://fapi.binance.com"}
# Explicit API-key metadata lives on the wallet/Spot API host for either key
# origin. This is a separate GET family, never a credentials fallback or wallet.
KEY_METADATA_HOST = "https://api.binance.com"
KEY_METADATA_PUBLIC = frozenset({"/api/v3/time"})
KEY_METADATA_SIGNED = frozenset({"/api/v3/account", "/sapi/v1/account/apiRestrictions"})
KEY_SNAPSHOT_ENDPOINT = "/sapi/v1/accountSnapshot"
# Separate read capability for explaining retained Earn balances. Never trading,
# redemption, subscription or automatic-subscribe authority.
SIMPLE_EARN_READ = frozenset({
    "/sapi/v1/simple-earn/flexible/position",
    "/sapi/v1/simple-earn/flexible/history/subscriptionRecord",
    "/sapi/v1/simple-earn/flexible/history/redemptionRecord",
    "/sapi/v1/simple-earn/flexible/history/rewardsRecord",
})
SUPPLEMENTAL_ACCOUNT_HISTORY_READ = frozenset({
    "/sapi/v1/simple-earn/flexible/history/collateralRecord",
    "/sapi/v1/asset/assetDividend",
})
# All documented universal-transfer directions touching the Spot MAIN wallet.
# This is a GET-parameter allowlist, never transfer/write authority.
SPOT_TRANSFER_TYPES = frozenset({
    "MAIN_UMFUTURE", "UMFUTURE_MAIN", "MAIN_CMFUTURE", "CMFUTURE_MAIN",
    "MAIN_MARGIN", "MARGIN_MAIN", "MAIN_FUNDING", "FUNDING_MAIN",
    "MAIN_OPTION", "OPTION_MAIN", "MAIN_PORTFOLIO_MARGIN", "PORTFOLIO_MARGIN_MAIN",
})
SYMBOL = re.compile(r"[A-Z0-9]{2,24}USDT\Z", re.ASCII)
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,36}\Z", re.ASCII)
AUTH_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
HEX = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
MAX_RESPONSE = 2_097_152
MAX_ERROR_RESPONSE = 4096
PUBLIC = {
    "SPOT_LIVE": {"/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/price", "/sapi/v1/system/status",
                  "/api/v3/depth", "/api/v3/avgPrice", "/api/v3/referencePrice", "/api/v3/executionRules"},
    "FUTURES_LIVE": {"/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v2/ticker/price", "/fapi/v1/premiumIndex",
                     "/fapi/v1/depth"},
}
SIGNED = {
    "SPOT_LIVE": {"/api/v3/account", "/api/v3/openOrders", "/api/v3/openOrderList", "/api/v3/myTrades",
                  "/api/v3/allOrders", "/api/v3/order", "/api/v3/orderList", "/api/v3/account/commission",
                  "/sapi/v1/account/apiRestrictions", "/sapi/v1/account/apiTradingStatus",
                  "/sapi/v1/capital/deposit/hisrec", "/sapi/v1/capital/withdraw/history", "/sapi/v1/asset/transfer"},
    "FUTURES_LIVE": {"/fapi/v3/account", "/fapi/v3/balance", "/fapi/v3/positionRisk", "/fapi/v1/accountConfig",
                     "/fapi/v1/symbolConfig", "/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders",
                     "/fapi/v1/order", "/fapi/v1/algoOrder", "/fapi/v1/allOrders", "/fapi/v1/allAlgoOrders",
                     "/fapi/v1/userTrades", "/fapi/v1/income", "/fapi/v1/commissionRate", "/fapi/v1/leverageBracket",
                     "/fapi/v1/positionSide/dual"},
}
WRITE = {
    "SPOT_LIVE": {("POST", "/api/v3/order"), ("POST", "/api/v3/orderList/oco"),
                  ("DELETE", "/api/v3/order"), ("DELETE", "/api/v3/orderList")},
    "FUTURES_LIVE": {("POST", "/fapi/v1/order"), ("POST", "/fapi/v1/algoOrder"),
                     ("DELETE", "/fapi/v1/order"), ("DELETE", "/fapi/v1/algoOrder")},
}


class LiveError(ValueError):
    """Closed code only. Never include provider text, URLs or credentials."""


class LiveHTTPError(LiveError):
    """Closed error plus bounded numerical facts, never the provider message."""
    def __init__(self, code, *, http_status=None, provider_code=None):
        if code not in {"LIVE_HTTP_UNAVAILABLE", "LIVE_RATE_LIMITED", "LIVE_PROVIDER_REJECTED"}:
            code = "LIVE_HTTP_UNAVAILABLE"
        super().__init__(code)
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        self.provider_code = provider_code if type(provider_code) is int and -(2**31) <= provider_code < 0 else None

    def diagnostics(self):
        out = {}
        if type(self.http_status) is int and 100 <= self.http_status <= 599:
            out["http_status"] = self.http_status
        if type(self.provider_code) is int and -(2**31) <= self.provider_code < 0:
            out["provider_code"] = self.provider_code
        return out


@dataclass(frozen=True, repr=False)
class LiveCredentials:
    api_key: str
    api_secret: str

    def __post_init__(self):
        for value in (self.api_key, self.api_secret):
            if type(value) is not str or not 8 <= len(value) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise LiveError("LIVE_CREDENTIALS_UNAVAILABLE")

    def __repr__(self):
        return "LiveCredentials(<redacted>)"

    def fingerprint(self):
        return hashlib.sha256(self.api_key.encode("ascii")).hexdigest()


def _identifier(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise LiveError("INVALID_LIVE_IDENTIFIER")
    return value


def _number(value):
    if type(value) is not str or len(value) > 40 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value, re.ASCII):
        raise LiveError("INVALID_LIVE_NUMBER")
    try:
        number = Decimal(value)
        if not number.is_finite() or not 0 < number < Decimal("1e15") or number.as_tuple().exponent < -18:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise LiveError("INVALID_LIVE_NUMBER") from None
    return number


def _read_params(params):
    allowed = {"symbol", "startTime", "endTime", "limit", "fromId", "orderId", "origClientOrderId",
               "orderListId", "origClientOrderId", "algoId", "clientAlgoId", "incomeType", "page",
               "offset", "type", "current", "size", "status"}
    if type(params) is not dict or set(params) - allowed:
        raise LiveError("LIVE_READ_PARAMETERS_BLOCKED")
    for key, value in params.items():
        if key == "symbol":
            if type(value) is not str or not SYMBOL.fullmatch(value):
                raise LiveError("INVALID_LIVE_SYMBOL")
        elif key in {"origClientOrderId", "clientAlgoId"}:
            _identifier(value)
        elif key == "incomeType":
            if value not in {"FUNDING_FEE", "COMMISSION", "TRANSFER", "REALIZED_PNL"}:
                raise LiveError("LIVE_READ_PARAMETERS_BLOCKED")
        elif key == "type":
            if value not in SPOT_TRANSFER_TYPES:
                raise LiveError("LIVE_READ_PARAMETERS_BLOCKED")
        elif type(value) is not int or not 0 <= value <= 253402300799000:
            raise LiveError("LIVE_READ_PARAMETERS_BLOCKED")
        elif key in {"limit", "size"} and not 1 <= value <= 1000:
            raise LiveError("LIVE_READ_PARAMETERS_BLOCKED")


def _simple_earn_params(endpoint, params, now_ms):
    history = endpoint != "/sapi/v1/simple-earn/flexible/position"
    required = {"current", "size"} | ({"startTime", "endTime"} if history else set())
    if endpoint.endswith("/rewardsRecord"):
        required.add("type")
    if (endpoint not in SIMPLE_EARN_READ or type(params) is not dict
            or not required <= set(params) or set(params)-required-{"asset"}
            or any(type(params[k]) is not int for k in ("current", "size"))
            or not 1 <= params["current"] <= 10000 or not 1 <= params["size"] <= 100):
        raise LiveError("LIVE_EARN_PARAMETERS_BLOCKED")
    if "asset" in params and (type(params["asset"]) is not str
            or not re.fullmatch(r"[A-Z0-9]{1,24}", params["asset"], re.ASCII)):
        raise LiveError("LIVE_EARN_PARAMETERS_BLOCKED")
    if history and (any(type(params[k]) is not int for k in ("startTime", "endTime"))
            or not 0 < params["startTime"] < params["endTime"] <= now_ms
            or params["endTime"]-params["startTime"] > 30*86400000):
        raise LiveError("LIVE_EARN_PARAMETERS_BLOCKED")
    if endpoint.endswith("/rewardsRecord") and params["type"] not in {"BONUS", "REALTIME", "REWARDS", "ALL"}:
        raise LiveError("LIVE_EARN_PARAMETERS_BLOCKED")


def _supplemental_history_params(endpoint, params, now_ms):
    """Separate signed Spot GETs; no generic endpoint or parameter widening."""
    collateral = endpoint == "/sapi/v1/simple-earn/flexible/history/collateralRecord"
    required = {"startTime", "endTime"} | ({"current", "size"} if collateral else {"limit"})
    optional = {"productId"} if collateral else {"asset"}
    if (endpoint not in SUPPLEMENTAL_ACCOUNT_HISTORY_READ or type(params) is not dict
            or not required <= set(params) or set(params)-required-optional
            or any(type(params[key]) is not int for key in ("startTime", "endTime"))
            or not 0 < params["startTime"] <= params["endTime"] <= now_ms
            or params["endTime"]-params["startTime"] > 30*86400000):
        raise LiveError("LIVE_SUPPLEMENTAL_PARAMETERS_BLOCKED")
    if collateral:
        if (any(type(params[key]) is not int for key in ("current", "size"))
                or not 1 <= params["current"] <= 10000 or not 1 <= params["size"] <= 100
                or "productId" in params and (type(params["productId"]) is not str
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", params["productId"], re.ASCII))):
            raise LiveError("LIVE_SUPPLEMENTAL_PARAMETERS_BLOCKED")
    elif (type(params["limit"]) is not int or not 1 <= params["limit"] <= 500
            or "asset" in params and (type(params["asset"]) is not str
                or not re.fullmatch(r"[A-Z0-9]{1,24}", params["asset"], re.ASCII))):
        raise LiveError("LIVE_SUPPLEMENTAL_PARAMETERS_BLOCKED")


class LiveReadOnlyTransport:
    """Explicit credentials, fixed HTTPS hosts, no proxy/redirect/retry."""

    def __init__(self, credentials, *, max_calls=80, clock=time.time, monotonic=time.monotonic):
        if type(credentials) is not dict or not credentials or set(credentials) - set(HOSTS):
            raise LiveError("LIVE_SCOPE_REQUIRED")
        if any(type(pair) is not LiveCredentials for pair in credentials.values()):
            raise LiveError("EXPLICIT_LIVE_CREDENTIALS_REQUIRED")
        if type(max_calls) is not int or not 1 <= max_calls <= 200:
            raise LiveError("LIVE_CALL_BUDGET_REQUIRED")
        self._credentials = dict(credentials)
        self.max_calls, self.calls, self.clock, self.monotonic = max_calls, 0, clock, monotonic
        self._samples = {}

    @staticmethod
    def _opener():
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),
            type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *args: None})())

    def _clock(self, scope, *, key_metadata=False):
        cache_key = ("KEY_METADATA", scope) if key_metadata else scope
        sample = self._samples.get(cache_key)
        if sample is not None and 0 <= self.monotonic() - sample[1] <= 30:
            return sample[0] + int((self.monotonic() - sample[1]) * 1000)
        began = self.monotonic()
        value = (self.get_key_metadata(scope, "/api/v3/time") if key_metadata else
                 self.get(scope, "/api/v3/time" if scope == "SPOT_LIVE" else "/fapi/v1/time"))
        received = self.monotonic()
        stamp = value.get("serverTime") if type(value) is dict else None
        if type(stamp) is not int or not 0 < stamp < 253402300799000 or not 0 <= received - began <= 2:
            raise LiveError("LIVE_CLOCK_UNVERIFIED")
        self._samples[cache_key] = (stamp, received)
        return stamp

    def _request(self, scope, method, endpoint, params, *, _write_capability=None, _key_metadata=False, _simple_earn=False, _supplemental_history=False):
        if scope not in HOSTS:
            raise LiveError("LIVE_SCOPE_REQUIRED")
        if type(_key_metadata) is not bool:
            raise LiveError("LIVE_KEY_METADATA_GET_BLOCKED")
        if type(_simple_earn) is not bool or _simple_earn and _key_metadata:
            raise LiveError("LIVE_EARN_GET_BLOCKED")
        if (type(_supplemental_history) is not bool
                or _supplemental_history and (_key_metadata or _simple_earn)):
            raise LiveError("LIVE_SUPPLEMENTAL_GET_BLOCKED")
        if _supplemental_history:
            if method != "GET" or scope != "SPOT_LIVE" or endpoint not in SUPPLEMENTAL_ACCOUNT_HISTORY_READ:
                raise LiveError("LIVE_SUPPLEMENTAL_GET_BLOCKED")
            _supplemental_history_params(endpoint, params, int(self.clock()*1000))
            public, host = PUBLIC[scope], HOSTS[scope]
        elif _simple_earn:
            if method != "GET" or scope != "SPOT_LIVE" or endpoint not in SIMPLE_EARN_READ:
                raise LiveError("LIVE_EARN_GET_BLOCKED")
            _simple_earn_params(endpoint, params, int(self.clock()*1000))
            public, host = PUBLIC[scope], HOSTS[scope]
        elif _key_metadata:
            if method != "GET" or endpoint not in KEY_METADATA_PUBLIC | KEY_METADATA_SIGNED | {KEY_SNAPSHOT_ENDPOINT}:
                raise LiveError("LIVE_KEY_METADATA_GET_BLOCKED")
            if endpoint == KEY_SNAPSHOT_ENDPOINT:
                if (type(params) is not dict or set(params) != {"type", "startTime", "endTime", "limit"}
                        or params["type"] != ("SPOT" if scope == "SPOT_LIVE" else "FUTURES")
                        or any(type(params[k]) is not int for k in ("startTime", "endTime", "limit"))
                        or not 0 < params["startTime"] < params["endTime"] <= int(self.clock()*1000)
                        or params["endTime"] - params["startTime"] >= 30*86400000
                        or not 7 <= params["limit"] <= 30):
                    raise LiveError("LIVE_SNAPSHOT_PARAMETERS_BLOCKED")
            elif params:
                raise LiveError("LIVE_KEY_METADATA_GET_BLOCKED")
            public, host = KEY_METADATA_PUBLIC, KEY_METADATA_HOST
        elif method == "GET":
            if endpoint not in PUBLIC[scope] | SIGNED[scope]:
                raise LiveError("LIVE_GET_ENDPOINT_BLOCKED")
        elif (type(_write_capability) is not _ConsumedGrant
              or type(self) is not LiveOrderTransport
              or _write_capability.request != (scope, method, endpoint, tuple(sorted(params.items())))
              or int(self.clock() * 1000) >= _write_capability.expires_utc_ms
              or (method, endpoint) not in WRITE[scope]):
            raise LiveError("LIVE_EXECUTION_LOCKED")
        if not _key_metadata and not _simple_earn and not _supplemental_history:
            public, host = PUBLIC[scope], HOSTS[scope]
        if scope not in self._credentials or self.calls >= self.max_calls:
            raise LiveError("LIVE_CREDENTIALS_OR_BUDGET_UNAVAILABLE")
        headers = {"User-Agent": "CryptoAITrader/SegregatedLiveReadOnly"}
        fields = dict(params)
        if endpoint not in public:
            fields.update(timestamp=self._clock(scope, key_metadata=_key_metadata), recvWindow=5000)
            pair = self._credentials[scope]
            query = urllib.parse.urlencode(sorted(fields.items()))
            fields["signature"] = hmac.new(pair.api_secret.encode("ascii"), query.encode("ascii"), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = pair.api_key
        signature = fields.pop("signature", None)
        query = urllib.parse.urlencode(sorted(fields.items()))
        if signature:
            query += "&signature=" + signature
        body = None
        url = host + endpoint
        if method == "POST":
            body = query.encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif query:
            url += "?" + query
        if self.calls >= self.max_calls:
            raise LiveError("LIVE_CALL_BUDGET_EXHAUSTED")
        self.calls += 1
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener().open(request, timeout=8) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise LiveError("LIVE_RESPONSE_SIZE_LIMIT")
                try:
                    value = _json(raw)
                except InventoryError:
                    raise LiveError("LIVE_INVALID_RESPONSE") from None
                if type(value) is dict and type(value.get("code")) is int and value["code"] < 0:
                    raise LiveHTTPError("LIVE_PROVIDER_REJECTED", http_status=getattr(response, "status", None),
                                        provider_code=value["code"])
                return value
        except urllib.error.HTTPError as error:
            status, provider_code = error.code, None
            try:
                raw = error.read(MAX_ERROR_RESPONSE + 1)
                if len(raw) <= MAX_ERROR_RESPONSE:
                    value = _json(raw)
                    if type(value) is dict and type(value.get("code")) is int:
                        provider_code = value["code"]
            except (OSError, ValueError, InventoryError):
                pass
            finally:
                error.close()
            raise LiveHTTPError("LIVE_RATE_LIMITED" if status in {418, 429} else "LIVE_HTTP_UNAVAILABLE",
                                http_status=status, provider_code=provider_code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise LiveError("LIVE_NETWORK_UNAVAILABLE") from None

    def get(self, scope, endpoint, fields=None):
        if scope not in HOSTS or endpoint not in PUBLIC[scope] | SIGNED[scope]:
            raise LiveError("LIVE_GET_ENDPOINT_BLOCKED")
        params = {} if fields is None else fields
        _read_params(params)
        return self._request(scope, "GET", endpoint, params)

    def get_key_metadata(self, origin_scope, endpoint):
        """Explicit global metadata using this origin's own dedicated key.

        The fixed endpoints can report UID/key rights, not grant product access.
        No user fields, arbitrary host, write method or alternative key is used.
        """
        if origin_scope not in HOSTS or endpoint not in KEY_METADATA_PUBLIC | KEY_METADATA_SIGNED:
            raise LiveError("LIVE_KEY_METADATA_GET_BLOCKED")
        return self._request(origin_scope, "GET", endpoint, {}, _key_metadata=True)

    def get_account_snapshots(self, origin_scope, *, start_utc_ms, end_utc_ms):
        """Explicit high-weight GET using this key's origin on the wallet host.

        This is deliberately separate from ordinary metadata and background
        capture. It never substitutes a key or accepts an arbitrary endpoint.
        The caller retains originals and budgets the documented 2400 IP weight.
        """
        if origin_scope not in HOSTS:
            raise LiveError("LIVE_SCOPE_REQUIRED")
        return self._request(origin_scope, "GET", KEY_SNAPSHOT_ENDPOINT,
            {"type": "SPOT" if origin_scope == "SPOT_LIVE" else "FUTURES",
             "startTime": start_utc_ms, "endTime": end_utc_ms, "limit": 30},
            _key_metadata=True)

    def get_simple_earn(self, endpoint, fields):
        """Explicit Spot-key GET-only Earn source, segregated from generic GET.

        Fixed endpoints and bounded fields cannot subscribe, redeem, transfer,
        change auto-subscribe or use the Futures key as a fallback.
        """
        return self._request("SPOT_LIVE", "GET", endpoint, fields, _simple_earn=True)

    def get_supplemental_account_history(self, endpoint, fields):
        """Only collateral/dividend originals on this configured Spot origin."""
        return self._request("SPOT_LIVE", "GET", endpoint, fields, _supplemental_history=True)


@dataclass(frozen=True)
class LiveOrderIntent:
    scope: str
    purpose: str
    method: str
    endpoint: str
    fields: tuple[tuple[str, str], ...]
    client_id: str
    policy_digest: str
    expires_utc_ms: int
    risk_terms: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if self.scope not in WRITE or (self.method, self.endpoint) not in WRITE[self.scope]:
            raise LiveError("LIVE_WRITE_ENDPOINT_BLOCKED")
        if self.purpose not in {"ENTRY", "PROTECT", "CLOSE", "CANCEL"}:
            raise LiveError("LIVE_PURPOSE_REQUIRED")
        _identifier(self.client_id)
        if type(self.policy_digest) is not str or not HEX.fullmatch(self.policy_digest):
            raise LiveError("LIVE_POLICY_REQUIRED")
        if type(self.expires_utc_ms) is not int or self.expires_utc_ms <= 0:
            raise LiveError("LIVE_EXPIRY_REQUIRED")
        if type(self.fields) is not tuple or any(type(p) is not tuple or len(p) != 2 or any(type(x) is not str for x in p) for p in self.fields):
            raise LiveError("IMMUTABLE_LIVE_FIELDS_REQUIRED")
        fields = dict(self.fields)
        if len(fields) != len(self.fields) or len(fields) > 18:
            raise LiveError("DUPLICATE_LIVE_FIELDS")
        self._validate(fields)
        if type(self.risk_terms) is not tuple or any(type(p) is not tuple or len(p) != 2 or any(type(x) is not str for x in p) for p in self.risk_terms):
            raise LiveError("IMMUTABLE_LIVE_RISK_TERMS_REQUIRED")
        if self.risk_terms:
            terms = dict(self.risk_terms)
            required = {"quantity", "reference_price", "stop_price", "reference_utc_ms"}
            if len(terms) != len(self.risk_terms) or set(terms) not in (required, required | {"protection_plan_fingerprint"}):
                raise LiveError("EXACT_LIVE_RISK_TERMS_REQUIRED")
            for key in ("quantity", "reference_price", "stop_price"):
                _number(terms[key])
            if not re.fullmatch(r"[0-9]{1,15}", terms["reference_utc_ms"], re.ASCII):
                raise LiveError("LIVE_RISK_TIMESTAMP_REQUIRED")
            if "protection_plan_fingerprint" in terms and not HEX.fullmatch(terms["protection_plan_fingerprint"]):
                raise LiveError("LIVE_PROTECTION_PLAN_SHA256_REQUIRED")

    def _validate(self, p):
        if self.method == "DELETE":
            if self.purpose != "CANCEL":
                raise LiveError("LIVE_CANCEL_PURPOSE_REQUIRED")
            key = "origClientOrderId" if self.endpoint.endswith("/order") or self.endpoint.endswith("/orderList") else "clientAlgoId"
            expected = {key} if self.endpoint == "/fapi/v1/algoOrder" else {"symbol", key}
            if set(p) != expected or p[key] != self.client_id:
                raise LiveError("LIVE_CANCEL_EXACT_TARGET_REQUIRED")
            if "symbol" in expected and not SYMBOL.fullmatch(p.get("symbol", "")):
                raise LiveError("INVALID_LIVE_SYMBOL")
            return
        if not SYMBOL.fullmatch(p.get("symbol", "")):
            raise LiveError("INVALID_LIVE_SYMBOL")
        if p.get("side") not in {"BUY", "SELL"}:
            raise LiveError("LIVE_SIDE_REQUIRED")
        _number(p.get("quantity"))
        if self.scope == "SPOT_LIVE":
            if self.endpoint.endswith("/oco"):
                required = {"symbol", "side", "quantity", "listClientOrderId", "aboveClientOrderId", "belowClientOrderId",
                            "aboveType", "abovePrice", "belowType", "belowStopPrice", "belowPrice", "belowTimeInForce"}
                if set(p) != required or self.purpose != "PROTECT" or p["side"] != "SELL" or p["listClientOrderId"] != self.client_id:
                    raise LiveError("LIVE_SPOT_PROTECTION_REQUIRED")
                if p["aboveType"] != "LIMIT_MAKER" or p["belowType"] != "STOP_LOSS_LIMIT" or p["belowTimeInForce"] != "GTC":
                    raise LiveError("LIVE_SPOT_PROTECTION_REQUIRED")
                if not _number(p["abovePrice"]) > _number(p["belowStopPrice"]) >= _number(p["belowPrice"]):
                    raise LiveError("LIVE_SPOT_PROTECTION_PRICES")
                _identifier(p["aboveClientOrderId"])
                _identifier(p["belowClientOrderId"])
                if len({p["aboveClientOrderId"], p["belowClientOrderId"], self.client_id}) != 3:
                    raise LiveError("LIVE_PROTECTION_IDS_DISTINCT")
                return
            if self.purpose not in {"ENTRY", "CLOSE"} or (self.purpose == "ENTRY") != (p["side"] == "BUY"):
                raise LiveError("LIVE_SPOT_DIRECTION_REQUIRED")
            base = {"symbol", "side", "type", "quantity", "newClientOrderId"}
        else:
            if p.get("positionSide") != "BOTH" or p.get("reduceOnly") not in {"true", "false"}:
                raise LiveError("LIVE_ONE_WAY_REDUCE_ONLY_REQUIRED")
            if self.endpoint.endswith("/algoOrder"):
                required = {"symbol", "side", "type", "quantity", "clientAlgoId", "algoType", "triggerPrice",
                            "workingType", "priceProtect", "positionSide", "reduceOnly"}
                if set(p) != required or self.purpose != "PROTECT" or p["clientAlgoId"] != self.client_id:
                    raise LiveError("LIVE_FUTURES_PROTECTION_REQUIRED")
                if p["type"] not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"} or p["algoType"] != "CONDITIONAL" or p["reduceOnly"] != "true" or p["workingType"] != "MARK_PRICE" or p["priceProtect"] != "TRUE":
                    raise LiveError("LIVE_FUTURES_PROTECTION_REQUIRED")
                _number(p["triggerPrice"])
                return
            if self.purpose not in {"ENTRY", "CLOSE"} or (p["reduceOnly"] == "false") != (self.purpose == "ENTRY"):
                raise LiveError("LIVE_REDUCE_ONLY_REQUIRED")
            base = {"symbol", "side", "type", "quantity", "newClientOrderId", "positionSide", "reduceOnly"}
        if p.get("newClientOrderId") != self.client_id or p.get("type") not in {"MARKET", "LIMIT"}:
            raise LiveError("LIVE_ORDER_KIND_REQUIRED")
        expected = base | ({"price", "timeInForce"} if p["type"] == "LIMIT" else set())
        if set(p) != expected:
            raise LiveError("LIVE_ORDER_FIELDS_BLOCKED")
        if p["type"] == "LIMIT" and (p["timeInForce"] != "GTC" or not _number(p["price"])):
            raise LiveError("LIVE_LIMIT_REQUIRED")

    def digest(self):
        value = {"scope": self.scope, "purpose": self.purpose, "method": self.method, "endpoint": self.endpoint,
                 "fields": sorted(self.fields), "client_id": self.client_id, "policy_digest": self.policy_digest,
                 "expires_utc_ms": self.expires_utc_ms, "risk_terms": sorted(self.risk_terms)}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class ExecutionGrant:
    intent_digest: str
    nonce: str
    reservation_id: str
    authorization_id: str
    policy_digest: str
    account_fingerprint: str
    expires_utc_ms: int
    proof: str


class GrantAuthority(Protocol):
    def consume(self, grant: ExecutionGrant, intent: LiveOrderIntent, *, now_utc_ms: int) -> bool:
        """Atomically validate admission, reserve, consume once and persist proof."""


@dataclass(frozen=True)
class _ConsumedGrant:
    request: tuple
    expires_utc_ms: int


class LiveSubmissionJournal:
    """Durable transport fence; uncertain submissions are never retried or freed."""

    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.suffix != ".sqlite3" or not self.path.name.startswith("LIVE_SUBMISSION_"):
            raise LiveError("SEGREGATED_LIVE_JOURNAL_REQUIRED")
        if self.path.is_symlink() or any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)() for parent in self.path.parents):
            raise LiveError("LINKED_LIVE_JOURNAL_BLOCKED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables != {"live_journal_meta", "live_submissions"}:
                raise LiveError("UNRECOGNIZED_LIVE_JOURNAL")
            if tables:
                if db.execute("SELECT version FROM live_journal_meta").fetchall() != [(1,)]:
                    raise LiveError("UNRECOGNIZED_LIVE_JOURNAL")
            else:
                db.execute("CREATE TABLE live_journal_meta (version INTEGER NOT NULL CHECK(version=1))")
                db.execute("INSERT INTO live_journal_meta VALUES (1)")
            db.execute("CREATE TABLE IF NOT EXISTS live_submissions (nonce TEXT PRIMARY KEY, scope TEXT NOT NULL, account TEXT NOT NULL, client_id TEXT NOT NULL, method TEXT NOT NULL, endpoint TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, evidence_digest TEXT, UNIQUE(scope, account, method, endpoint, client_id))")
            # Existing version-one dispatch fences remain fences. Missing terms
            # in an old receipt are never reconstructed from today's quantities.
            columns = {row[1] for row in db.execute("PRAGMA table_info(live_submissions)")}
            for column in ("intent_json", "reservation_id", "execution_json"):
                if column not in columns:
                    db.execute("ALTER TABLE live_submissions ADD COLUMN " + column + " TEXT")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def claim(self, grant, intent):
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO live_submissions (nonce,scope,account,client_id,method,endpoint,digest,state,evidence_digest,intent_json,reservation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (grant.nonce, intent.scope,
                    grant.account_fingerprint, intent.client_id, intent.method, intent.endpoint, intent.digest(), "UNKNOWN", None,
                    json.dumps(asdict(intent), sort_keys=True, separators=(",", ":"), allow_nan=False), grant.reservation_id))
        except sqlite3.IntegrityError:
            raise LiveError("LIVE_ALREADY_CLAIMED_RECONCILE_ONLY") from None

    def record(self, nonce, state, digest):
        if state not in {"ACK_REQUIRES_RECONCILIATION", "UNKNOWN"} or not HEX.fullmatch(digest):
            raise LiveError("LIVE_JOURNAL_INVALID_RESULT")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM live_submissions WHERE nonce=?", (nonce,)).fetchone()
            if row is None or row[0] != "UNKNOWN":
                raise LiveError("LIVE_JOURNAL_STATE_CONFLICT")
            db.execute("UPDATE live_submissions SET state=?, evidence_digest=? WHERE nonce=?", (state, digest, nonce))

    def receipt(self, scope, account_fingerprint, method, endpoint, client_id):
        """Read a dispatch receipt after restart; never renew permission."""
        with self._db() as db:
            row = db.execute("SELECT digest,state FROM live_submissions WHERE scope=? AND account=? AND method=? AND endpoint=? AND client_id=?",
                (scope, account_fingerprint, method, endpoint, client_id)).fetchone()
            return None if row is None else {"intent_digest": row[0], "state": row[1], "resend_permitted": False}

    @staticmethod
    def _retained_intent(value, digest):
        try:
            if type(value) is not str or len(value) > 16_384:
                raise ValueError()
            data = json.loads(value)
            data["fields"] = tuple(tuple(pair) for pair in data["fields"])
            data["risk_terms"] = tuple(tuple(pair) for pair in data["risk_terms"])
            intent = LiveOrderIntent(**data)
            if intent.digest() != digest:
                raise ValueError()
            return intent
        except (TypeError, ValueError, KeyError):
            raise LiveError("EXACT_RETAINED_LIVE_INTENT_UNAVAILABLE") from None

    def owned_intents(self, scope, account, reservation_id, purpose):
        """Original immutable requests only; expiry is not renewed for GET."""
        if purpose not in {"ENTRY", "PROTECT", "CLOSE", "CANCEL"}:
            raise LiveError("LIVE_PURPOSE_REQUIRED")
        with self._db() as db:
            rows = db.execute("SELECT intent_json,digest,scope,method,endpoint,client_id FROM live_submissions WHERE scope=? AND account=? AND reservation_id=? ORDER BY rowid",
                (scope, account, reservation_id)).fetchall()
        intents = []
        for value, digest, recorded_scope, method, endpoint, client in rows:
            intent = self._retained_intent(value, digest)
            if (intent.scope, intent.method, intent.endpoint, intent.client_id) != (recorded_scope, method, endpoint, client):
                raise LiveError("RETAINED_LIVE_INTENT_BINDING_MISMATCH")
            intents.append(intent)
        return tuple(intent for intent in intents if intent.purpose == purpose)

    def record_execution(self, intent, account, reservation_id, observation):
        """Retain original exact-order GET/trades before using a reduction.

        This is evidence storage, never a permission, retry or financial PnL.
        Repeated observations do not duplicate fees. Previous observations stay
        retained so a later partial execution cannot erase an earlier fill.
        """
        if type(intent) is not LiveOrderIntent or type(observation) is not dict:
            raise LiveError("OWNED_EXECUTION_OBSERVATION_REQUIRED")
        encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded) > MAX_RESPONSE * 2:
            raise LiveError("OWNED_EXECUTION_OBSERVATION_TOO_LARGE")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT digest,reservation_id,execution_json FROM live_submissions WHERE scope=? AND account=? AND method=? AND endpoint=? AND client_id=?",
                (intent.scope, account, intent.method, intent.endpoint, intent.client_id)).fetchone()
            if row is None or row[0] != intent.digest() or row[1] != reservation_id:
                raise LiveError("OWNED_EXECUTION_SUBMISSION_REQUIRED")
            try:
                records = [] if row[2] is None else json.loads(row[2])
                if type(records) is not list or len(records) > 128 or any(type(r) is not dict for r in records):
                    raise ValueError()
            except (TypeError, ValueError):
                raise LiveError("RETAINED_EXECUTION_RECORDS_INVALID") from None
            if observation not in records:
                if len(records) >= 128:
                    raise LiveError("RETAINED_EXECUTION_RECORD_LIMIT")
                records.append(observation)
            db.execute("UPDATE live_submissions SET execution_json=? WHERE scope=? AND account=? AND method=? AND endpoint=? AND client_id=?",
                (json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False),
                 intent.scope, account, intent.method, intent.endpoint, intent.client_id))

    def execution_observations(self, intent, account, reservation_id):
        with self._db() as db:
            row = db.execute("SELECT digest,reservation_id,execution_json FROM live_submissions WHERE scope=? AND account=? AND method=? AND endpoint=? AND client_id=?",
                (intent.scope, account, intent.method, intent.endpoint, intent.client_id)).fetchone()
        if row is None or row[0] != intent.digest() or row[1] != reservation_id:
            raise LiveError("OWNED_EXECUTION_SUBMISSION_REQUIRED")
        try:
            records = [] if row[2] is None else json.loads(row[2])
            if type(records) is not list or len(records) > 128 or any(type(r) is not dict for r in records):
                raise ValueError()
            return tuple(records)
        except (TypeError, ValueError):
            raise LiveError("RETAINED_EXECUTION_RECORDS_INVALID") from None


class LiveOrderTransport(LiveReadOnlyTransport):
    """Prepared only. No shipped caller supplies a production grant authority."""

    def __init__(self, credentials, *, journal=None, authority=None, **kwargs):
        super().__init__(credentials, **kwargs)
        self.journal, self.authority = journal, authority

    def submit(self, intent, grant=None):
        if type(intent) is not LiveOrderIntent or type(grant) is not ExecutionGrant or self.authority is None or type(self.journal) is not LiveSubmissionJournal:
            raise LiveError("LIVE_EXECUTION_LOCKED")
        # Validate immutable intent again, independently of an issuer implementation.
        intent.__post_init__()
        now = int(self.clock() * 1000)
        if not 0 < intent.expires_utc_ms - now <= 30_000 or grant.expires_utc_ms != intent.expires_utc_ms:
            raise LiveError("LIVE_GRANT_EXPIRED_OR_TOO_LONG")
        if grant.intent_digest != intent.digest() or grant.policy_digest != intent.policy_digest:
            raise LiveError("LIVE_GRANT_MISMATCH")
        for value in (grant.nonce, grant.reservation_id, grant.authorization_id):
            if type(value) is not str or not AUTH_IDENTIFIER.fullmatch(value):
                raise LiveError("INVALID_LIVE_AUTHORIZATION_IDENTIFIER")
        if intent.scope not in self._credentials or grant.account_fingerprint != self._credentials[intent.scope].fingerprint():
            raise LiveError("LIVE_GRANT_ACCOUNT_MISMATCH")
        # Obtain verified exchange clock before consuming the single-use admission.
        self._clock(intent.scope)
        now = int(self.clock() * 1000)
        if now >= intent.expires_utc_ms:
            raise LiveError("LIVE_AUTHORITY_REJECTED")
        try:
            accepted = self.authority.consume(grant, intent, now_utc_ms=now)
        except Exception:
            raise LiveError("LIVE_AUTHORITY_UNAVAILABLE") from None
        if accepted is not True:
            raise LiveError("LIVE_AUTHORITY_REJECTED")
        try:
            self.journal.claim(grant, intent)
        except sqlite3.Error:
            raise LiveError("LIVE_JOURNAL_UNAVAILABLE") from None
        try:
            capability = _ConsumedGrant((intent.scope, intent.method, intent.endpoint, tuple(sorted(intent.fields))), intent.expires_utc_ms)
            result = self._request(intent.scope, intent.method, intent.endpoint, dict(intent.fields), _write_capability=capability)
            # Even HTTP 200 is not a filled position, native protection or release.
            digest = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self.journal.record(grant.nonce, "ACK_REQUIRES_RECONCILIATION", digest)
            return {"state": "ACK_REQUIRES_RECONCILIATION", "client_id": intent.client_id,
                    "response": result, "execution_confirmed": False, "reservation_release_allowed": False}
        except (LiveError, sqlite3.Error):
            return {"state": "UNKNOWN", "client_id": intent.client_id, "execution_confirmed": False,
                    "reservation_release_allowed": False}

    def reconcile(self, intent):
        """Query exact client identifier; caller must validate fills/protections."""
        if type(intent) is not LiveOrderIntent:
            raise LiveError("LIVE_INTENT_REQUIRED")
        if intent.endpoint.endswith("/oco") or intent.endpoint.endswith("/orderList"):
            endpoint, key = "/api/v3/orderList", "origClientOrderId"
        elif intent.endpoint.endswith("/algoOrder"):
            endpoint, key = "/fapi/v1/algoOrder", "clientAlgoId"
        else:
            endpoint, key = ("/api/v3/order" if intent.scope == "SPOT_LIVE" else "/fapi/v1/order"), "origClientOrderId"
        params = {key: intent.client_id}
        if endpoint not in {"/api/v3/orderList", "/fapi/v1/algoOrder"}:
            params["symbol"] = dict(intent.fields)["symbol"]
        return self.get(intent.scope, endpoint, params)
