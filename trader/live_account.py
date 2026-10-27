"""Explicit read-only LIVE observation, bounded history and resumable cursors.

A scoped successful query is not account ownership, full historic completeness,
capital allocation, reconciliation, trading authorization or evidence of safety.
Spot and USD-M remain separate wallets. No trading class is imported here.
"""
from __future__ import annotations

import ctypes
import errno
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from trader.live_transport import LiveCredentials, LiveError, LiveHTTPError, LiveReadOnlyTransport, SYMBOL

PERMISSION_FIELDS = ("enableReading", "enableWithdrawals", "ipRestrict", "enableSpotAndMarginTrading",
                     "enableFutures", "enableMargin", "enableInternalTransfer", "permitsUniversalTransfer",
                     "enablePortfolioMarginTrading")
KEY_WRITE_FIELDS = ("enableWithdrawals", "enableSpotAndMarginTrading", "enableFutures", "enableMargin",
                    "enableInternalTransfer", "permitsUniversalTransfer", "enablePortfolioMarginTrading",
                    "enableVanillaOptions", "enableFixApiTrade")
KEY_RIGHT_FIELDS = PERMISSION_FIELDS + ("enableVanillaOptions", "enableFixApiTrade")
LINK_SCOPES = ("SPOT_LIVE", "FUTURES_LIVE")
AUTHORITY = {"execution_enabled": False, "financial_authorization": False,
             "capital_allocated": False, "automatic_activation": False, "account_ownership_certified": False}


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _uid(value):
    """UID is used only in memory and encrypted raw evidence, never returned."""
    if type(value) is not int or not 0 < value < 2**63:
        raise LiveError("LIVE_KEY_IDENTITY_UNKNOWN")
    return value


def _key_rights(raw):
    if type(raw) is not dict or "code" in raw or "msg" in raw:
        return {"status":"UNKNOWN", "subject":"GLOBAL_API_KEY_RIGHTS",
                "read_only_verified":False, "flags":{}, "unexpected_fields_present":False,
                "invalid_fields_present":False,
                "configured_markets_read_only_verified":False, "other_product_rights_unknown":True,
                "reason":"GLOBAL_KEY_RIGHTS_UNAVAILABLE",
                "product_permissions_certified":False}
    values = {key:raw[key] if type(raw.get(key)) is bool else None for key in KEY_RIGHT_FIELDS}
    if "enableFixReadOnly" in raw:
        values["enableFixReadOnly"] = raw["enableFixReadOnly"] if type(raw["enableFixReadOnly"]) is bool else None
    known = set(KEY_RIGHT_FIELDS) | {"enableFixReadOnly", "createTime", "tradingAuthorityExpirationTime"}
    unexpected = bool(set(raw) - known)
    metadata_valid = all(type(raw[key]) is int and 0 <= raw[key] < 2**63
                         for key in ("createTime", "tradingAuthorityExpirationTime") if key in raw)
    invalid = not metadata_valid or any(type(raw[key]) is not bool
                for key in set(raw) & (set(KEY_RIGHT_FIELDS) | {"enableFixReadOnly"}))
    complete = not unexpected and not invalid and all(value is not None for value in values.values())
    configured_read_only = (not unexpected and not invalid and values["enableReading"] is True
        and type(values["ipRestrict"]) is bool
        and all(values[key] is False for key in KEY_WRITE_FIELDS if key not in {"enableVanillaOptions", "enableFixApiTrade"})
        and values["enableFixApiTrade"] in {False, None})
    if "enableFixApiTrade" in raw and type(raw["enableFixApiTrade"]) is not bool:
        configured_read_only = False
    if type(values["enableFixApiTrade"]) is bool and values["enableFixApiTrade"]:
        configured_read_only = False
    other_unknown = values["enableVanillaOptions"] is None or values["enableFixApiTrade"] is None
    reason = ("UNRECOGNIZED_KEY_METADATA" if unexpected else
              "CONFIGURED_MARKETS_READ_ONLY_OTHER_RIGHTS_UNKNOWN" if configured_read_only and other_unknown else
              "INCOMPLETE_KEY_RIGHTS" if not complete
              else "KEY_WRITE_PRIVILEGES_PRESENT" if any(values[key] for key in KEY_WRITE_FIELDS)
              else "READ_ONLY_KEY_RIGHTS_OBSERVED" if values["enableReading"] else "KEY_READING_DISABLED")
    return {"status":"OBSERVED" if complete else "PARTIAL", "subject":"GLOBAL_API_KEY_RIGHTS",
            "read_only_verified":complete and values["enableReading"] is True
                and all(values[key] is False for key in KEY_WRITE_FIELDS),
            "flags":values, "unexpected_fields_present":unexpected,
            "invalid_fields_present":invalid,
            "configured_markets_read_only_verified":configured_read_only,
            "other_product_rights_unknown":other_unknown, "reason":reason,
            "product_permissions_certified":False}


def _amount(value, *, signed=False):
    if type(value) not in {str, int} or len(str(value)) > 64:
        raise LiveError("LIVE_INVALID_ACCOUNT_NUMBER")
    try:
        number = Decimal(value)
        if not number.is_finite() or number.copy_abs() > Decimal("1e18") or number.as_tuple().exponent < -18 or not signed and number < 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise LiveError("LIVE_INVALID_ACCOUNT_NUMBER") from None
    return format(number, "f")


def _rows(value):
    if type(value) is not list or len(value) > 10_000 or any(type(row) is not dict for row in value):
        raise LiveError("LIVE_INVALID_ACCOUNT_ROWS")
    return value


def _transfer_rows(value, *, prior_rows=0, page_size=100):
    """A confirmed empty transfer response can omit rows; no other omission is zero."""
    if (type(value) is not dict or set(value) not in ({"total"}, {"total", "rows"})
            or type(value.get("total")) is not int or not 0 <= value["total"] <= 10**12):
        raise LiveError("LIVE_INVALID_ACCOUNT_ROWS")
    if "rows" not in value:
        if value["total"] != 0:
            raise LiveError("LIVE_INVALID_ACCOUNT_ROWS")
        rows = []
    else:
        rows = _rows(value["rows"])
    count = prior_rows + len(rows)
    if count > value["total"] or len(rows) < page_size and count != value["total"]:
        raise LiveError("LIVE_HISTORY_CONTRADICTION")
    return rows


def _asset(value):
    # Binance can return Unicode assets and mixed-case names. Never use as URL,
    # symbol, path, code or markup. JSON text is the sole destination.
    if type(value) is not str or not 1 <= len(value) <= 128 or any(ord(c) < 32 for c in value):
        raise LiveError("LIVE_INVALID_ASSET_NAME")
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def dpapi_protect(raw):
    """Current Windows user only; never create a plaintext fallback."""
    if os.name != "nt":
        raise LiveError("WINDOWS_DPAPI_REQUIRED_FOR_RAW_RETENTION")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), buffer)
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    crypt.CryptProtectData.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not crypt.CryptProtectData(ctypes.byref(source), "CryptoBot LIVE read-only evidence", None, None, None, 1, ctypes.byref(target)):
        raise LiveError("LIVE_RAW_ENCRYPTION_FAILED")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class EncryptedAuditStore:
    """Private immutable folder. Raw responses are Windows-user encrypted."""

    def __init__(self, directory, *, protect=dpapi_protect):
        self.directory = Path(directory).resolve()
        if any((parent / ".git").exists() for parent in (self.directory, *self.directory.parents)):
            raise LiveError("LIVE_EVIDENCE_MUST_BE_OUTSIDE_GIT")
        self.directory.mkdir(parents=True, exist_ok=False)
        self.protect = protect
        self.sequence = 0

    def retain(self, evidence):
        raw = _canonical(evidence)
        encrypted = self.protect(raw)
        if type(encrypted) is not bytes or not encrypted or encrypted == raw:
            raise LiveError("LIVE_RAW_ENCRYPTION_REQUIRED")
        self.sequence += 1
        name = f"response-{self.sequence:04d}.dpapi"
        path = self.directory / name
        with path.open("xb") as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        return {"file": name, "sha256": hashlib.sha256(raw).hexdigest(),
                "encrypted_sha256": hashlib.sha256(encrypted).hexdigest()}

    def report(self, value):
        path = self.directory / "audit.json"
        with path.open("xb") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        return path


class LiveAccountAudit:
    def __init__(self, transport, *, symbols, start_utc_ms, end_utc_ms, max_pages=3,
                 page_size=100, cursors=None, raw_store=None, clock=time.time, verify_account_link=False):
        if not isinstance(transport, LiveReadOnlyTransport) or type(transport) is not LiveReadOnlyTransport:
            raise LiveError("LIVE_GET_ONLY_TRANSPORT_REQUIRED")
        if type(symbols) not in {list, tuple} or not 1 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols) or any(type(s) is not str or not SYMBOL.fullmatch(s) for s in symbols):
            raise LiveError("LIVE_AUDIT_SYMBOLS_REQUIRED")
        if any(type(x) is not int for x in (start_utc_ms, end_utc_ms)) or not 0 < start_utc_ms < end_utc_ms <= int(clock() * 1000) or end_utc_ms - start_utc_ms > 86_400_000:
            raise LiveError("LIVE_AUDIT_WINDOW_MAX_ONE_DAY")
        if type(max_pages) is not int or not 1 <= max_pages <= 10 or type(page_size) is not int or not 1 <= page_size <= 1000:
            raise LiveError("LIVE_AUDIT_PAGE_BUDGET_REQUIRED")
        if cursors is not None and (type(cursors) is not dict or len(cursors) > 100):
            raise LiveError("LIVE_AUDIT_CURSORS_INVALID")
        if type(verify_account_link) is not bool:
            raise LiveError("LIVE_EXPLICIT_ACCOUNT_LINK_REQUIRED")
        if verify_account_link:
            if set(transport._credentials) != set(LINK_SCOPES):
                raise LiveError("LIVE_ACCOUNT_LINK_REQUIRES_BOTH_SCOPES")
            if len({pair.fingerprint() for pair in transport._credentials.values()}) != 2:
                raise LiveError("LIVE_ACCOUNT_LINK_REQUIRES_DISTINCT_KEYS")
            if raw_store is None:
                raise LiveError("LIVE_ACCOUNT_LINK_ENCRYPTED_EVIDENCE_REQUIRED")
        self.transport, self.symbols = transport, tuple(symbols)
        self.start, self.end, self.max_pages, self.page_size = start_utc_ms, end_utc_ms, max_pages, page_size
        self.cursors, self.store, self.clock = cursors or {}, raw_store, clock
        self.observations = []
        self._errors = []
        self.verify_account_link = verify_account_link
        self._native_uids = {}

    def _get(self, scope, name, endpoint, params=None, *, key_metadata=False):
        began = int(self.clock() * 1000)
        try:
            value = (self.transport.get_key_metadata(scope, endpoint) if key_metadata else
                     self.transport.get(scope, endpoint, params))
            received = int(self.clock() * 1000)
            evidence = {"scope": scope, "endpoint": endpoint, "params": params or {},
                        "request_started_utc": _iso(began), "received_utc": _iso(received), "response": value}
            if key_metadata:
                evidence["purpose"] = "GLOBAL_KEY_METADATA"
            retained = self.store.retain(evidence) if self.store else None
            self.observations.append({"scope": scope, "name": name, "request_started_utc": _iso(began),
                "received_utc": _iso(received), "response_sha256": hashlib.sha256(_canonical(value)).hexdigest(),
                "raw": retained, "status": "OBSERVED",
                **({"purpose":"GLOBAL_KEY_METADATA"} if key_metadata else {})})
            return value
        except LiveError as error:
            code = str(error)
            # Only our closed error alphabet may leave the exception boundary.
            if not re.fullmatch(r"[A-Z0-9_]{1,80}", code, re.ASCII):
                code = "LIVE_READ_FAILED"
            self.observations.append({"scope": scope, "name": name, "request_started_utc": _iso(began),
                "received_utc": _iso(int(self.clock() * 1000)), "status": "UNKNOWN", "code": code,
                **({"purpose":"GLOBAL_KEY_METADATA"} if key_metadata else {}),
                **(LiveHTTPError.diagnostics(error) if isinstance(error, LiveHTTPError) else {})})
            self._errors.append(code)
            return None

    def _permissions(self, scope):
        # SAPI lives only on Spot host, with the effective key of this scope.
        # Futures-specific credentials cannot be silently substituted for Spot.
        if scope != "SPOT_LIVE":
            return {"status": "UNKNOWN", "withdrawals_disabled": None, "ip_restricted": None,
                    "reason": "NO_PRODUCT_PERMISSION_CERTIFICATION"}
        raw = self._get(scope, "api_permissions", "/sapi/v1/account/apiRestrictions")
        if type(raw) is not dict:
            return {"status": "UNKNOWN", "withdrawals_disabled": None, "ip_restricted": None}
        values = {key: raw[key] if type(raw.get(key)) is bool else None for key in PERMISSION_FIELDS}
        return {"status": "OBSERVED" if all(value is not None for value in values.values()) else "PARTIAL",
                "withdrawals_disabled": None if values["enableWithdrawals"] is None else not values["enableWithdrawals"],
                "ip_restricted": values["ipRestrict"], "flags": values,
                "dedicated_key_certified": False}

    def _account(self, scope):
        raw = self._get(scope, "account", "/api/v3/account" if scope == "SPOT_LIVE" else "/fapi/v3/account")
        try:
            if type(raw) is not dict:
                raise LiveError("LIVE_ACCOUNT_UNKNOWN")
            if scope == "SPOT_LIVE":
                balances, seen = [], set()
                for row in _rows(raw.get("balances")):
                    asset = _asset(row.get("asset"))
                    if asset in seen:
                        raise LiveError("LIVE_DUPLICATE_BALANCE")
                    seen.add(asset)
                    free, locked = _amount(row.get("free")), _amount(row.get("locked"))
                    if Decimal(free) or Decimal(locked):
                        balances.append({"asset": asset, "free": free, "locked": locked})
                if type(raw.get("canTrade")) is not bool:
                    raise LiveError("LIVE_ACCOUNT_PERMISSIONS_UNKNOWN")
                if self.verify_account_link and type(raw.get("uid")) is int and 0 < raw["uid"] < 2**63:
                    self._native_uids[scope] = raw["uid"]
                return {"status": "OBSERVED", "wallet": "SPOT_LIVE", "balances": balances,
                        "can_trade_reported": raw["canTrade"], "identity_reported": "uid" in raw,
                        "identity_linked": False, "ledger_reconciled": False}
            assets, seen = [], set()
            for row in _rows(raw.get("assets")):
                asset = _asset(row.get("asset"))
                if asset in seen:
                    raise LiveError("LIVE_DUPLICATE_BALANCE")
                seen.add(asset)
                assets.append({"asset": asset, "wallet_balance": _amount(row.get("walletBalance")),
                               "available_balance": _amount(row.get("availableBalance")),
                               "unrealized_pnl": _amount(row.get("unrealizedProfit"), signed=True)})
            _rows(raw.get("positions"))
            totals = {key: _amount(raw.get(key), signed=key == "totalUnrealizedProfit")
                      for key in ("totalWalletBalance", "availableBalance", "totalUnrealizedProfit", "totalMarginBalance")}
            return {"status": "OBSERVED", "wallet": "FUTURES_LIVE", "assets": assets,
                    "reported_totals": totals, "can_trade_reported": None,
                    "identity_reported": False, "identity_linked": False, "ledger_reconciled": False}
        except LiveError as error:
            self._errors.append(str(error))
            return {"status": "UNKNOWN", "wallet": scope, "ledger_reconciled": False}

    def _account_link(self, wallets):
        """Compare global key-origin UIDs; wallets and funds remain separate."""
        uids, rows = {}, []
        for scope in LINK_SCOPES:
            raw = self._get(scope, "global_key_identity", "/api/v3/account", key_metadata=True)
            identity_evidence = self.observations[-1]
            try:
                if (type(raw) is not dict or "code" in raw or "msg" in raw
                        or raw.get("accountType") != "SPOT" or type(raw.get("canTrade")) is not bool):
                    raise LiveError("LIVE_KEY_IDENTITY_UNKNOWN")
                _rows(raw.get("balances"))
                uids[scope] = _uid(raw.get("uid"))
            except LiveError as error:
                self._errors.append(str(error))
            permissions = _key_rights(self._get(scope, "global_key_permissions",
                "/sapi/v1/account/apiRestrictions", key_metadata=True))
            rights_evidence = self.observations[-1]
            rows.append({"origin_scope":scope, "identity_reported":scope in uids,
                "observed_at":rights_evidence["received_utc"], "global_key_permissions":permissions,
                "evidence_refs":{"identity":(identity_evidence.get("raw") or {}).get("sha256"),
                                 "permissions":(rights_evidence.get("raw") or {}).get("sha256")}})
        native_match = ("SPOT_LIVE" in uids and self._native_uids.get("SPOT_LIVE") == uids["SPOT_LIVE"])
        accounts_observed = all(wallets[scope]["account"].get("status") == "OBSERVED" for scope in LINK_SCOPES)
        if len(uids) != 2 or not native_match or not accounts_observed:
            status, same = "UNKNOWN", None
            if len(uids) == 2 and not native_match:
                self._errors.append("LIVE_KEY_IDENTITY_CONTRADICTION")
        elif uids["SPOT_LIVE"] != uids["FUTURES_LIVE"]:
            status, same = "DIFFERENT_ACCOUNTS", False
        else:
            status, same = "SAME_ACCOUNT_OBSERVED", True
        # Raw identifiers are intentionally not copied into this plain report.
        return {"schema":1, "status":status, "same_account_observed":same,
                "identity_namespace":"BINANCE_GLOBAL_UID", "credential_origins_separate":True,
                "scopes":rows, "wallets_merged":False, "human_ownership_certified":False,
                "financial_authorization":False}

    def _current(self, scope):
        endpoints = ({"orders": "/api/v3/openOrders", "order_lists": "/api/v3/openOrderList"} if scope == "SPOT_LIVE" else
                     {"positions": "/fapi/v3/positionRisk", "orders": "/fapi/v1/openOrders",
                      "algo_orders": "/fapi/v1/openAlgoOrders", "account_config": "/fapi/v1/accountConfig"})
        result = {}
        for name, endpoint in endpoints.items():
            value = self._get(scope, name, endpoint)
            try:
                if name == "account_config":
                    if type(value) is not dict or any(type(value.get(k)) is not bool for k in ("dualSidePosition", "multiAssetsMargin", "canTrade")):
                        raise LiveError("LIVE_ACCOUNT_CONFIG_UNKNOWN")
                    result[name] = {"status": "OBSERVED", **{key: value[key] for key in ("dualSidePosition", "multiAssetsMargin", "canTrade")},
                                    "eligible_one_way_single_asset": not value["dualSidePosition"] and not value["multiAssetsMargin"] and value["canTrade"]}
                    continue
                rows = _rows(value)
                if name == "positions":
                    positions = []
                    for row in rows:
                        amount = _amount(row.get("positionAmt"), signed=True)
                        if not Decimal(amount):
                            continue
                        symbol = row.get("symbol")
                        if type(symbol) is not str or not SYMBOL.fullmatch(symbol) or row.get("positionSide") not in {"BOTH", "LONG", "SHORT"}:
                            raise LiveError("LIVE_POSITION_UNKNOWN")
                        positions.append({"symbol": symbol, "quantity_signed": amount, "position_side": row["positionSide"],
                                          "entry_price": _amount(row.get("entryPrice")), "mark_price": _amount(row.get("markPrice")),
                                          "unrealized_pnl": _amount(row.get("unRealizedProfit"), signed=True),
                                          "protection_status": "UNKNOWN", "recognized_by_bot": False})
                    result[name] = {"status": "OBSERVED", "count": len(positions), "positions": positions}
                else:
                    # Count only: IDs and raw account/order data remain encrypted.
                    result[name] = {"status": "OBSERVED", "count": len(rows), "reconciled": False}
            except LiveError as error:
                self._errors.append(str(error))
                result[name] = {"status": "UNKNOWN", "count": None, "reconciled": False}
        return result

    def _time_history(self, scope, name, endpoint, params):
        """Split inclusive time windows; never advance past saturated millisecond.

        Current official income API documents no page field. Full segments are
        re-queried as disjoint halves; only exhausted halves contribute counts.
        """
        binding = hashlib.sha256(_canonical({"scope": scope, "endpoint": endpoint, "params": params,
                                            "start": self.start, "end": self.end, "page_size": self.page_size})).hexdigest()
        cursor = self.cursors.get(scope + ":" + name)
        pending, previous = [[self.start, self.end]], 0
        if cursor is not None:
            if type(cursor) is not dict or set(cursor) != {"binding", "windows", "rows_previously_observed"} or cursor.get("binding") != binding:
                return {"status": "UNKNOWN", "reason": "CURSOR_BINDING_MISMATCH", "window_complete": False, "rows": None}
            pending, previous = cursor.get("windows"), cursor.get("rows_previously_observed")
            if type(pending) is not list or not 1 <= len(pending) <= 100 or type(previous) is not int or previous < 0:
                return {"status": "UNKNOWN", "reason": "CURSOR_BINDING_MISMATCH", "window_complete": False, "rows": None}
            prior_end = self.start - 1
            for pair in pending:
                if type(pair) is not list or len(pair) != 2 or any(type(x) is not int for x in pair) or not self.start <= pair[0] <= pair[1] <= self.end or pair[0] <= prior_end:
                    return {"status": "UNKNOWN", "reason": "CURSOR_BINDING_MISMATCH", "window_complete": False, "rows": None}
                prior_end = pair[1]
        pending = [list(pair) for pair in pending]
        observed, pages, reason = 0, 0, None
        while pending and pages < self.max_pages:
            start, end = pending[0]
            value = self._get(scope, name + f"_segment{pages + 1}", endpoint,
                              dict(params, startTime=start, endTime=end, limit=self.page_size))
            pages += 1
            try:
                rows = _rows(value)
                identities = set()
                for row in rows:
                    stamp, identity = row.get("time"), row.get("tranId")
                    if type(stamp) is not int or not start <= stamp <= end or type(identity) is not int or identity < 0 or identity in identities or row.get("incomeType") != params.get("incomeType"):
                        raise LiveError("LIVE_HISTORY_CONTRADICTION")
                    identities.add(identity)
                    _amount(row.get("income"), signed=True)
                    _asset(row.get("asset"))
                if len(rows) < self.page_size:
                    observed += len(rows)
                    pending.pop(0)
                elif start < end:
                    midpoint = (start + end) // 2
                    pending[:1] = [[start, midpoint], [midpoint + 1, end]]
                else:
                    reason = "LIVE_HISTORY_TIMESTAMP_SATURATED"
                    break
            except LiveError as error:
                reason = str(error)
                self._errors.append(reason)
                break
        resume = ({"binding": binding, "windows": pending, "rows_previously_observed": previous + observed} if pending else None)
        return {"status": "OBSERVED_WINDOW" if not pending else "PARTIAL", "rows": observed,
                "rows_previously_observed": previous, "pages": pages, "cursor": resume,
                "reason": reason, "window_complete": not pending, "account_history_complete": False}

    def _history(self, scope, name, endpoint, params, *, pagination="id", row_key=None):
        if pagination == "time":
            return self._time_history(scope, name, endpoint, params)
        cursor_key = scope + ":" + name
        cursor = self.cursors.get(cursor_key)
        binding = hashlib.sha256(_canonical({"scope": scope, "endpoint": endpoint, "params": params,
                                            "start": self.start, "end": self.end, "page_size": self.page_size})).hexdigest()
        expected = {"binding", "next", "rows_previously_observed"}
        if cursor is not None and (type(cursor) is not dict or set(cursor) != expected or cursor.get("binding") != binding
                or type(cursor.get("next")) is not int or cursor["next"] < 0
                or type(cursor.get("rows_previously_observed")) is not int or cursor["rows_previously_observed"] < 0):
            return {"status": "UNKNOWN", "rows": None, "reason": "CURSOR_BINDING_MISMATCH", "window_complete": False}
        next_value = cursor["next"] if cursor else (1 if pagination in {"page", "current"} else 0)
        previous = cursor["rows_previously_observed"] if cursor else 0
        observed, pages, exhausted, last_next = 0, 0, False, None
        seen_ids = set()
        for _ in range(self.max_pages):
            fields = dict(params, startTime=self.start, endTime=self.end)
            effective_limit = min(self.page_size, 100) if pagination == "current" else self.page_size
            fields["size" if pagination == "current" else "limit"] = effective_limit
            if pagination == "id" and next_value:
                fields["fromId"] = next_value
                # Binance Spot myTrades forbids mixing fromId with start/end.
                fields.pop("startTime", None)
                fields.pop("endTime", None)
            elif pagination in {"page", "current", "offset"}:
                fields[pagination] = next_value
            value = self._get(scope, name + f"_page{pages + 1}", endpoint, fields)
            pages += 1
            try:
                if scope == "SPOT_LIVE" and endpoint == "/sapi/v1/asset/transfer" and row_key == "rows":
                    rows = _transfer_rows(value, prior_rows=previous + observed, page_size=effective_limit)
                else:
                    rows = _rows(value.get(row_key) if row_key and type(value) is dict else value)
                ids = []
                for row in rows:
                    if pagination == "id":
                        row_id, stamp = row.get("id"), row.get("time")
                        if type(row_id) is not int or row_id < next_value or type(stamp) is not int or stamp < self.start:
                            raise LiveError("LIVE_HISTORY_CONTRADICTION")
                        if row_id in seen_ids:
                            raise LiveError("LIVE_HISTORY_DUPLICATE")
                        seen_ids.add(row_id)
                        ids.append(row_id)
                    else:
                        stamp = row.get("time", row.get("insertTime", row.get("applyTime", self.start)))
                    # Some withdrawal timestamps are text. Preserve raw evidence
                    # but do not certify their window without a product parser.
                    if type(stamp) is int and stamp > self.end:
                        continue
                    observed += 1
                if len(rows) < effective_limit:
                    exhausted = True
                    break
                if pagination == "id":
                    if not ids or ids != sorted(ids):
                        raise LiveError("LIVE_HISTORY_ORDER_UNKNOWN")
                    last_next = max(ids) + 1
                elif pagination in {"page", "current"}:
                    last_next = next_value + 1
                else:
                    last_next = next_value + len(rows)
                if last_next <= next_value:
                    raise LiveError("LIVE_HISTORY_CURSOR_STALLED")
                next_value = last_next
            except LiveError as error:
                self._errors.append(str(error))
                return {"status": "UNKNOWN", "rows": observed, "pages": pages, "window_complete": False,
                        "reason": str(error), "cursor": cursor}
        resume = None if exhausted else {"binding": binding, "next": next_value,
                                         "rows_previously_observed": previous + observed}
        return {"status": "OBSERVED_WINDOW" if exhausted else "PARTIAL", "rows": observed,
                "rows_previously_observed": previous, "pages": pages, "cursor": resume,
                "window_complete": exhausted, "account_history_complete": False}

    def run(self):
        started = int(self.clock() * 1000)
        wallets = {}
        for scope in sorted(self.transport._credentials):
            wallet = {"scope": scope, "account": self._account(scope), "permissions": self._permissions(scope),
                      "current": self._current(scope), "market_and_fees": {}, "history": {}}
            for symbol in self.symbols:
                endpoint = "/api/v3/exchangeInfo" if scope == "SPOT_LIVE" else "/fapi/v1/exchangeInfo"
                filters = self._get(scope, symbol + "_filters", endpoint, {"symbol": symbol} if scope == "SPOT_LIVE" else None)
                fee = self._get(scope, symbol + "_fees", "/api/v3/account/commission" if scope == "SPOT_LIVE" else "/fapi/v1/commissionRate", {"symbol": symbol})
                price = self._get(scope, symbol + "_price", "/api/v3/ticker/price" if scope == "SPOT_LIVE" else "/fapi/v2/ticker/price", {"symbol": symbol})
                wallet["market_and_fees"][symbol] = {"filters_observed": filters is not None,
                    "fees_observed": fee is not None, "price_observed": price is not None,
                    "execution_feasibility_certified": False}
                endpoint = "/api/v3/myTrades" if scope == "SPOT_LIVE" else "/fapi/v1/userTrades"
                wallet["history"]["trades_" + symbol] = self._history(scope, "trades_" + symbol, endpoint, {"symbol": symbol})
            if scope == "SPOT_LIVE":
                wallet["history"]["deposits"] = self._history(scope, "deposits", "/sapi/v1/capital/deposit/hisrec", {}, pagination="offset")
                wallet["history"]["withdrawals"] = self._history(scope, "withdrawals", "/sapi/v1/capital/withdraw/history", {}, pagination="offset")
                for direction in ("MAIN_UMFUTURE", "UMFUTURE_MAIN"):
                    wallet["history"][direction] = self._history(scope, direction, "/sapi/v1/asset/transfer", {"type": direction}, pagination="current", row_key="rows")
            else:
                for kind in ("FUNDING_FEE", "COMMISSION", "TRANSFER", "REALIZED_PNL"):
                    wallet["history"][kind] = self._history(scope, kind, "/fapi/v1/income", {"incomeType": kind}, pagination="time")
            wallet["cashflows_reconciled"] = False
            wallet["all_symbols_history_complete"] = False
            wallets[scope] = wallet
        account_link = self._account_link(wallets) if self.verify_account_link else None
        finished = int(self.clock() * 1000)
        report = {"schema": "live-account-audit/v1", "status": "PARTIAL" if self._errors else "SCOPED_OBSERVATION",
                  "started_utc": _iso(started), "finished_utc": _iso(finished),
                  "account_cut_utc": _iso(started), "atomic_account_cut": False,
                  "history_window": {"start_utc": _iso(self.start), "end_utc": _iso(self.end), "symbols": list(self.symbols)},
                  "wallets": wallets, "wallets_merged": False, "account_history_complete": False,
                  "initial_inventory_certified": False, "calls": self.transport.calls,
                  "raw_retention_requested": self.store is not None,
                  "raw_encrypted_retention": self.store is not None and self.store.sequence > 0,
                  "observations": self.observations,
                  "authority": dict(AUTHORITY), "errors": sorted(set(self._errors)),
                  "limitations": ["BOUNDED_SYMBOLS_AND_TIME_WINDOW", "IDENTITY_NOT_LINKED", "NO_INITIAL_LEDGER_RECONCILIATION",
                                  "NO_ORDER_EXECUTION_OR_PROTECTION_CERTIFICATION", "NO_COMPLETE_ACCOUNT_HISTORY",
                                  "PERMISSIONS_OBSERVATION_IS_NOT_OWNER_AUTHORIZATION"]}
        if account_link is not None:
            report["account_link"] = account_link
            if account_link["same_account_observed"] is True:
                report["limitations"].remove("IDENTITY_NOT_LINKED")
                report["limitations"].append("KEY_UID_LINK_IS_NOT_HUMAN_OWNERSHIP_CERTIFICATION")
        if self.store:
            self.store.report(report)
        return report


def _evidence_stamp(value, *, now):
    if (type(now) not in {int, float} or not 0 < now < 1e12
            or type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value)):
        raise LiveError("LIVE_CONNECTION_EVIDENCE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        stamp = parsed.timestamp()
        if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value or not 0 <= now - stamp <= 300:
            raise ValueError()
    except (ValueError, OverflowError):
        raise LiveError("LIVE_CONNECTION_EVIDENCE_TIME_INVALID") from None
    return stamp


def connection_status_from_audit(report, *, now=None):
    """Closed observation cache; cannot issue readiness or financial authority.

    Only an explicit, fresh two-key UID observation with retained encrypted raw
    evidence may label the configured Spot/USD-M REST scopes read-only verified.
    Unknown rights for other products remain explicit in the audit, not silently
    false. Account ownership, history, wallet pooling and execution stay unapproved.
    """
    now = time.time() if now is None else now
    if (type(report) is not dict or report.get("schema") != "live-account-audit/v1"
            or report.get("wallets_merged") is not False or report.get("account_history_complete") is not False
            or report.get("initial_inventory_certified") is not False or report.get("raw_encrypted_retention") is not True
            or type(report.get("authority")) is not dict or set(report["authority"]) != set(AUTHORITY)
            or any(value is not False for value in report["authority"].values())
            or type(report.get("wallets")) is not dict or set(report["wallets"]) != set(LINK_SCOPES)):
        raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
    finished_stamp = _evidence_stamp(report.get("finished_utc"), now=now)
    link = report.get("account_link")
    if (type(link) is not dict or set(link) != {"schema", "status", "same_account_observed", "identity_namespace",
            "credential_origins_separate", "scopes", "wallets_merged", "human_ownership_certified", "financial_authorization"}
            or type(link["schema"]) is not int or link["schema"] != 1
            or link["identity_namespace"] != "BINANCE_GLOBAL_UID" or link["credential_origins_separate"] is not True
            or link["wallets_merged"] is not False or link["human_ownership_certified"] is not False
            or link["financial_authorization"] is not False or type(link["scopes"]) is not list or len(link["scopes"]) != 2
            or not (link["same_account_observed"] is None or type(link["same_account_observed"]) is bool)
            or link["status"] not in {"SAME_ACCOUNT_OBSERVED", "DIFFERENT_ACCOUNTS", "UNKNOWN"}
            or (link["status"], link["same_account_observed"]) not in
               {("SAME_ACCOUNT_OBSERVED", True), ("DIFFERENT_ACCOUNTS", False), ("UNKNOWN", None)}):
        raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
    observations = report.get("observations")
    if type(observations) is not list or not 1 <= len(observations) <= 200:
        raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
    scopes, stamps = [], []
    for row, scope in zip(link["scopes"], LINK_SCOPES):
        if (type(row) is not dict or set(row) != {"origin_scope", "identity_reported", "observed_at",
                "global_key_permissions", "evidence_refs"} or row["origin_scope"] != scope
                or type(row["identity_reported"]) is not bool or type(row["evidence_refs"]) is not dict
                or set(row["evidence_refs"]) != {"identity", "permissions"}):
            raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
        wallet = report["wallets"][scope]
        if type(wallet) is not dict or type(wallet.get("account")) is not dict:
            raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
        account_observed = wallet["account"].get("status") == "OBSERVED"
        if account_observed:
            native = [item for item in observations if type(item) is dict and item.get("scope") == scope
                      and item.get("name") == "account" and item.get("status") == "OBSERVED"
                      and "purpose" not in item]
            if len(native) != 1 or type(native[0].get("raw")) is not dict:
                raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
            raw = native[0]["raw"]
            if (set(raw) != {"file", "sha256", "encrypted_sha256"}
                    or type(raw["file"]) is not str or not re.fullmatch(r"response-\d{4}\.dpapi", raw["file"])
                    or any(type(raw[field]) is not str or not re.fullmatch(r"[a-f0-9]{64}", raw[field])
                           for field in ("sha256", "encrypted_sha256"))):
                raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
            stamps.append(_evidence_stamp(native[0].get("received_utc"), now=now))
        stamps.append(_evidence_stamp(row["observed_at"], now=now))
        for kind, name in (("identity", "global_key_identity"), ("permissions", "global_key_permissions")):
            digest = row["evidence_refs"][kind]
            matching = [item for item in observations if type(item) is dict and item.get("scope") == scope
                        and item.get("name") == name and item.get("purpose") == "GLOBAL_KEY_METADATA"
                        and item.get("status") == "OBSERVED" and type(item.get("raw")) is dict
                        and item["raw"].get("sha256") == digest]
            if digest is None:
                if matching:
                    raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
                continue
            if type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", digest) or len(matching) != 1:
                raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
            item = matching[0]
            raw = item.get("raw")
            if (type(raw) is not dict or set(raw) != {"file", "sha256", "encrypted_sha256"}
                    or type(raw["file"]) is not str or not re.fullmatch(r"response-\d{4}\.dpapi", raw["file"])
                    or raw["sha256"] != digest or type(raw["encrypted_sha256"]) is not str
                    or not re.fullmatch(r"[a-f0-9]{64}", raw["encrypted_sha256"])):
                raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
            stamps.append(_evidence_stamp(item.get("received_utc"), now=now))
        rights = row["global_key_permissions"]
        if (type(rights) is not dict or set(rights) != {"status", "subject", "read_only_verified", "flags",
                "unexpected_fields_present", "product_permissions_certified", "configured_markets_read_only_verified",
                "other_product_rights_unknown", "invalid_fields_present", "reason"}
                or rights["status"] not in {"OBSERVED", "PARTIAL", "UNKNOWN"}
                or rights["subject"] != "GLOBAL_API_KEY_RIGHTS" or type(rights["flags"]) is not dict
                or type(rights["read_only_verified"]) is not bool or type(rights["unexpected_fields_present"]) is not bool
                or type(rights["invalid_fields_present"]) is not bool
                or type(rights["configured_markets_read_only_verified"]) is not bool
                or type(rights["other_product_rights_unknown"]) is not bool
                or rights["reason"] not in {"GLOBAL_KEY_RIGHTS_UNAVAILABLE", "UNRECOGNIZED_KEY_METADATA",
                    "INCOMPLETE_KEY_RIGHTS", "KEY_WRITE_PRIVILEGES_PRESENT", "READ_ONLY_KEY_RIGHTS_OBSERVED", "KEY_READING_DISABLED",
                    "CONFIGURED_MARKETS_READ_ONLY_OTHER_RIGHTS_UNKNOWN"}
                or rights["product_permissions_certified"] is not False):
            raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
        flags = rights["flags"]
        if set(flags) - (set(KEY_RIGHT_FIELDS) | {"enableFixReadOnly"}) or any(
                value is not None and type(value) is not bool for value in flags.values()):
            raise LiveError("LIVE_CONNECTION_LINK_EVIDENCE_REQUIRED")
        verified = (rights["status"] in {"OBSERVED", "PARTIAL"} and not rights["unexpected_fields_present"]
            and not rights["invalid_fields_present"]
            and rights["configured_markets_read_only_verified"] is True and flags.get("enableReading") is True
            and all(flags.get(key) is False for key in KEY_WRITE_FIELDS if key not in {"enableVanillaOptions", "enableFixApiTrade"})
            and flags.get("enableFixApiTrade") in {False, None}
            and type(flags.get("ipRestrict")) is bool)
        observed = (row["identity_reported"] is True and row["evidence_refs"]["identity"] is not None and account_observed)
        scopes.append({"environment":scope, "identity":"REPORTED" if observed else "UNKNOWN",
                       "permissions":"VERIFIED" if observed and verified and row["evidence_refs"]["permissions"] else "UNKNOWN",
                       "at":row["observed_at"]})
    if max(stamps) > finished_stamp or max(stamps) - min(stamps) > 120:
        raise LiveError("LIVE_CONNECTION_EVIDENCE_CUT_TOO_WIDE")
    ready = (link["same_account_observed"] is True
             and all(row["identity"] == "REPORTED" and row["permissions"] == "VERIFIED" for row in scopes))
    return {"schema":1, "state":"READ_ONLY_VERIFIED" if ready else "CONFIGURED_UNVERIFIED",
            "at":report["finished_utc"], "scopes":scopes}


def publish_connection_status(report, data_dir, *, now=None):
    """Atomic bounded observation cache only; no keys or activation records."""
    value = connection_status_from_audit(report, now=now)
    encoded = _canonical(value)
    if len(encoded) > 8000:
        raise LiveError("LIVE_CONNECTION_STATUS_SIZE_LIMIT")
    target = Path(data_dir)/"live-preproduction"/"connection-status.json"
    lock = target.with_suffix(".json.lock")
    for path in (target, lock, *target.parents):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise LiveError("LIVE_CONNECTION_STATUS_LINK_BLOCKED")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".connection-" + uuid.uuid4().hex)
    handle, acquired = None, False
    try:
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_BINARY", 0), 0o600)
        handle = os.fdopen(descriptor, "r+b")
        opened, named = os.fstat(handle.fileno()), os.stat(lock, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size not in {0, 1}
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                or getattr(named, "st_file_attributes", 0) & 0x400):
            raise LiveError("LIVE_CONNECTION_STATUS_LINK_BLOCKED")
        # Lock beyond EOF without writing a marker first: two Windows writers
        # cannot race a buffered initialization write against the other's lock.
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        for path in (target, lock, *target.parents):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise LiveError("LIVE_CONNECTION_STATUS_LINK_BLOCKED")
        current_lock = os.stat(lock, follow_symlinks=False)
        if ((opened.st_dev, opened.st_ino) != (current_lock.st_dev, current_lock.st_ino)
                or current_lock.st_nlink != 1):
            raise LiveError("LIVE_CONNECTION_STATUS_LINK_BLOCKED")
        if target.exists():
            if target.stat().st_size > 8000:
                raise LiveError("LIVE_CONNECTION_STATUS_SIZE_LIMIT")
            current = json.loads(target.read_text(encoding="utf-8"))
            if type(current) is not dict or type(current.get("at")) not in {str, type(None)}:
                raise LiveError("LIVE_CONNECTION_STATUS_INVALID")
            if current["at"] is not None and current["at"] > value["at"]:
                raise LiveError("LIVE_CONNECTION_STATUS_OLDER_THAN_CURRENT")
        with temporary.open("xb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except OSError as error:
        raise LiveError("LIVE_CONNECTION_STATUS_BUSY" if error.errno in
                        {errno.EACCES, errno.EAGAIN, errno.EDEADLK} else "LIVE_CONNECTION_STATUS_UNAVAILABLE") from None
    finally:
        if handle is not None:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()
        temporary.unlink(missing_ok=True)
    return value


def credentials_from_environment(environment):
    """Explicit mapping passed by caller. Never falls back to Testnet/.env."""
    result = {}
    for name, scope in (("SPOT", "SPOT_LIVE"), ("FUTURES", "FUTURES_LIVE")):
        key = environment.get(f"BINANCE_LIVE_{name}_API_KEY")
        secret = environment.get(f"BINANCE_LIVE_{name}_API_SECRET")
        if key or secret:
            if not key or not secret:
                raise LiveError("LIVE_CREDENTIAL_PAIR_INCOMPLETE")
            result[scope] = LiveCredentials(key, secret)
    if not result:
        raise LiveError("NO_SEPARATE_LIVE_CREDENTIALS")
    return result


def audit_directory(parent):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(parent) / ("live-audit-" + stamp + "-" + uuid.uuid4().hex[:8])
