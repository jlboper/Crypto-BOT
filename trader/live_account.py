"""Explicit read-only LIVE observation, bounded history and resumable cursors.

A scoped successful query is not account ownership, full historic completeness,
capital allocation, reconciliation, trading authorization or evidence of safety.
Spot and USD-M remain separate wallets. No trading class is imported here.
"""
from __future__ import annotations

import ctypes
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from trader.live_transport import LiveCredentials, LiveError, LiveHTTPError, LiveReadOnlyTransport, SYMBOL

PERMISSION_FIELDS = ("enableReading", "enableWithdrawals", "ipRestrict", "enableSpotAndMarginTrading",
                     "enableFutures", "enableMargin", "enableInternalTransfer", "permitsUniversalTransfer",
                     "enablePortfolioMarginTrading")
AUTHORITY = {"execution_enabled": False, "financial_authorization": False,
             "capital_allocated": False, "automatic_activation": False, "account_ownership_certified": False}


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
                 page_size=100, cursors=None, raw_store=None, clock=time.time):
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
        self.transport, self.symbols = transport, tuple(symbols)
        self.start, self.end, self.max_pages, self.page_size = start_utc_ms, end_utc_ms, max_pages, page_size
        self.cursors, self.store, self.clock = cursors or {}, raw_store, clock
        self.observations = []
        self._errors = []

    def _get(self, scope, name, endpoint, params=None):
        began = int(self.clock() * 1000)
        try:
            value = self.transport.get(scope, endpoint, params)
            received = int(self.clock() * 1000)
            evidence = {"scope": scope, "endpoint": endpoint, "params": params or {},
                        "request_started_utc": _iso(began), "received_utc": _iso(received), "response": value}
            retained = self.store.retain(evidence) if self.store else None
            self.observations.append({"scope": scope, "name": name, "request_started_utc": _iso(began),
                "received_utc": _iso(received), "response_sha256": hashlib.sha256(_canonical(value)).hexdigest(),
                "raw": retained, "status": "OBSERVED"})
            return value
        except LiveError as error:
            code = str(error)
            # Only our closed error alphabet may leave the exception boundary.
            if not re.fullmatch(r"[A-Z0-9_]{1,80}", code, re.ASCII):
                code = "LIVE_READ_FAILED"
            self.observations.append({"scope": scope, "name": name, "request_started_utc": _iso(began),
                "received_utc": _iso(int(self.clock() * 1000)), "status": "UNKNOWN", "code": code,
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
        if self.store:
            self.store.report(report)
        return report


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
