"""Explicit, bounded Testnet/Demo GET audit. Never an execution adapter.

The CLI invokes this outside the supervised trading process. A cut is not atomic
across Binance endpoints or SQLite files. Identity reported by each product does
not link the two accounts, certify API permissions, or authorize shared capital.
No production host, redirect, write verb, model or ledger constructor is used.
"""
from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

HOSTS = {"SPOT_TESTNET": "https://testnet.binance.vision",
         "FUTURES_DEMO": "https://testnet.binancefuture.com"}
PUBLIC = {"SPOT_TESTNET": {"/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/price"},
          "FUTURES_DEMO": {"/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/ticker/price"}}
SIGNED = {"SPOT_TESTNET": {"/api/v3/account", "/api/v3/openOrders", "/api/v3/openOrderList",
                            "/api/v3/myTrades", "/api/v3/account/commission"},
          "FUTURES_DEMO": {"/fapi/v3/account", "/fapi/v3/balance", "/fapi/v3/positionRisk",
                            "/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders", "/fapi/v1/userTrades",
                            "/fapi/v1/income", "/fapi/v1/commissionRate"}}
SYMBOL = re.compile(r"[A-Z0-9]{2,24}USDT\Z", re.ASCII)
ASSET = re.compile(r"[A-Z0-9]{1,24}\Z", re.ASCII)
MAX_RESPONSE = 2_097_152
MAX_ROWS = 10_000
AUTHORITY = {"execution_enabled": False, "controls_enabled": False,
             "reservations_enabled": False, "promotion_allowed": False,
             "financial_authorization": False, "automatic_activation": False}


class InventoryError(ValueError):
    """Only closed error codes; never echo credentials, URLs or provider text."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_value):
    raise InventoryError("NONFINITE_JSON")


def _json(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if count > 100_000 or depth > 16:
                raise ValueError()
            if isinstance(item, dict):
                pending.extend((v, depth+1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth+1) for v in item)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError()
        return value
    except (ValueError, RecursionError, UnicodeError):
        raise InventoryError("INVALID_BOUNDED_JSON") from None


def _decimal(value, *, signed=False):
    if type(value) not in (str, int) or len(str(value)) > 64:
        raise InventoryError("INVALID_EXCHANGE_NUMBER")
    try:
        number = Decimal(value)
        if (not number.is_finite() or number.copy_abs() > Decimal("1e18")
                or number.as_tuple().exponent < -18 or not signed and number < 0):
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        raise InventoryError("INVALID_EXCHANGE_NUMBER") from None


def _text(value):
    with localcontext() as context:
        context.prec = 80
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text


def _iso(at):
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _rows(value):
    if not isinstance(value, list) or len(value) > MAX_ROWS or any(type(row) is not dict for row in value):
        raise InventoryError("INVALID_EXCHANGE_ROWS")
    return value


class TestnetReadOnlyTransport:
    """Closed GET capability; credentials explicit, no environment lookup/retry."""
    __test__ = False

    def __init__(self, credentials, *, max_calls=40, clock=time.time, monotonic=time.monotonic):
        if type(max_calls) is not int or not 1 <= max_calls <= 80:
            raise InventoryError("CALL_BUDGET_REQUIRED")
        self.credentials = {}
        for scope, pair in credentials.items():
            if scope not in HOSTS or not isinstance(pair, tuple) or len(pair) != 2:
                raise InventoryError("TEST_ENVIRONMENT_REQUIRED")
            if any(type(x) is not str or not 1 <= len(x) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in x) for x in pair):
                raise InventoryError("CREDENTIALS_UNAVAILABLE")
            self.credentials[scope] = pair
        self.max_calls, self.calls, self.clock, self.monotonic = max_calls, 0, clock, monotonic
        self.samples = {}

    @staticmethod
    def _opener():
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),
            type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                 {"redirect_request": lambda *args: None})())

    def get(self, scope, endpoint, fields=None):
        if scope not in HOSTS or endpoint not in PUBLIC[scope] | SIGNED[scope]:
            raise InventoryError("READ_ENDPOINT_BLOCKED")
        params = dict(fields or {})
        if set(params) - {"symbol", "startTime", "endTime", "limit", "incomeType"}:
            raise InventoryError("READ_PARAMETERS_BLOCKED")
        if "symbol" in params and (type(params["symbol"]) is not str or not SYMBOL.fullmatch(params["symbol"])):
            raise InventoryError("INVALID_AUDIT_SYMBOL")
        for key in ("startTime", "endTime", "limit"):
            if key in params and (type(params[key]) is not int or not 0 <= params[key] <= 253402300799000):
                raise InventoryError("INVALID_READ_PARAMETERS")
        if "limit" in params and not 1 <= params["limit"] <= 1000:
            raise InventoryError("INVALID_READ_PARAMETERS")
        if "incomeType" in params and params["incomeType"] != "FUNDING_FEE":
            raise InventoryError("READ_PARAMETERS_BLOCKED")
        headers = {"User-Agent": "CryptoAITrader/ReadOnlyTestAudit"}
        if endpoint in SIGNED[scope]:
            if scope not in self.credentials:
                raise InventoryError("CREDENTIALS_UNAVAILABLE")
            sample = self.samples.get(scope)
            if sample is None or not 0 <= self.monotonic()-sample[1] <= 60:
                path = "/api/v3/time" if scope == "SPOT_TESTNET" else "/fapi/v1/time"
                started = self.monotonic()
                value = self.get(scope, path)
                received = self.monotonic()
                stamp = value.get("serverTime") if isinstance(value, dict) else None
                if type(stamp) is not int or stamp <= 0 or not 0 <= received-started <= 2:
                    raise InventoryError("SERVER_CLOCK_UNVERIFIED")
                sample = self.samples[scope] = (stamp, received)
            key, secret = self.credentials[scope]
            params.update(timestamp=sample[0]+int((self.monotonic()-sample[1])*1000), recvWindow=5000)
            query = urllib.parse.urlencode(params)
            params["signature"] = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = key
        if self.calls >= self.max_calls:
            raise InventoryError("CALL_BUDGET_EXHAUSTED")
        self.calls += 1
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(HOSTS[scope]+endpoint+("?"+query if query else ""),
                                         headers=headers, method="GET")
        try:
            with self._opener().open(request, timeout=8) as response:
                raw = response.read(MAX_RESPONSE+1)
                if len(raw) > MAX_RESPONSE:
                    raise InventoryError("RESPONSE_SIZE_LIMIT")
                return _json(raw)
        except urllib.error.HTTPError as error:
            raise InventoryError("RATE_LIMITED" if error.code in (418, 429) else "READ_HTTP_UNAVAILABLE") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise InventoryError("READ_NETWORK_UNAVAILABLE") from None


def read_local_positions(spot_path, futures_path):
    """Separate read transactions, no Database/FuturesLedger constructors."""
    result = {}
    for scope, path, table in (("SPOT_TESTNET", Path(spot_path), "positions"),
                                ("FUTURES_DEMO", Path(futures_path), "forward_position")):
        result[scope] = {"state": "UNKNOWN", "positions": [], "at": None}
        try:
            if not path.is_file() or path.is_symlink():
                continue
            with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=.25)) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                deadline = time.monotonic()+2
                db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                db.execute("BEGIN")
                fields = "symbol,quantity"+(",direction" if scope == "FUTURES_DEMO" else "")
                rows = db.execute("SELECT "+fields+" FROM "+table+" ORDER BY symbol LIMIT 101").fetchall()
                if len(rows) > 100:
                    continue
                positions = []
                for row in rows:
                    if not SYMBOL.fullmatch(row[0]):
                        raise ValueError()
                    quantity = _decimal(str(row[1]))
                    direction = row[2] if len(row) == 3 else "LONG"
                    if quantity <= 0 or direction not in ("LONG", "SHORT"):
                        raise ValueError()
                    positions.append({"symbol": row[0], "quantity": _text(quantity), "direction": direction})
                result[scope] = {"state": "OBSERVED", "positions": positions, "at": _iso(time.time())}
        except (OSError, sqlite3.Error, ValueError, TypeError):
            pass
    return result


def capture_inventory(transport, local, *, symbols=(), clock=time.time):
    """Collect bounded recent evidence; history deliberately remains incomplete.

    Trades/funding are one recent page per requested symbol. Even an empty page
    cannot certify all history, cashflows or ownership. Report contains no account
    identifier, API key, order ID or raw provider error. Market fixtures are private.
    """
    if (not isinstance(symbols, tuple) or len(symbols) > 4 or len(set(symbols)) != len(symbols)
            or any(type(s) is not str or not SYMBOL.fullmatch(s) for s in symbols)):
        raise InventoryError("BOUNDED_SYMBOL_SCOPE_REQUIRED")
    started = clock()
    result = {"schema": 1, "mode": "READ_ONLY_TEST_ENVIRONMENTS", "started_at": _iso(started),
        "at": None, **AUTHORITY, "accounts_linked": False, "atomic": False,
        "complete_exchange_inventory": False, "history_complete": False,
        "cashflows_reconciled": False, "calls": 0, "accounts": [], "market_inputs": []}
    history_start = int((started-86400)*1000)
    for scope in HOSTS:
        observations = {}
        def fetch(name, endpoint, fields=None):
            at = clock()
            try:
                value = transport.get(scope, endpoint, fields)
                observations[name] = {"state": "OBSERVED", "requested_at": _iso(at), "received_at": _iso(clock()), "error": None}
                return value
            except InventoryError as error:
                observations[name] = {"state": "UNKNOWN", "requested_at": _iso(at), "received_at": _iso(clock()), "error": str(error)}
                return None
        spot = scope == "SPOT_TESTNET"
        account = fetch("account", "/api/v3/account" if spot else "/fapi/v3/account")
        balances = account.get("balances") if spot and isinstance(account, dict) else fetch("balance", "/fapi/v3/balance") if not spot else None
        positions = None if spot else fetch("positions", "/fapi/v3/positionRisk")
        orders = fetch("open_orders", "/api/v3/openOrders" if spot else "/fapi/v1/openOrders")
        conditional = fetch("conditional_orders", "/api/v3/openOrderList" if spot else "/fapi/v1/openAlgoOrders")
        row = {"environment": scope, "at": None, "state": "PARTIAL", "identity": "UNKNOWN",
               "balance_semantics": "FREE_PLUS_LOCKED" if spot else "AVAILABLE_ALREADY_NET_OF_MARGIN",
               "quote_balance": None, "nonzero_assets": None, "exchange_positions": None,
               "local_positions": None, "local_at": None, "quantity_check": "UNKNOWN", "untracked_positions": None,
               "open_orders": None, "conditional_orders": None, "recent_fills": 0 if symbols else None,
               "recent_funding_rows": 0 if symbols and not spot else None, "history_scope": "REQUESTED_SYMBOLS_LAST_24H_FIRST_PAGE",
               "history_complete": False, "observations": observations}
        try:
            if type(account) is not dict or "code" in account or "msg" in account:
                raise InventoryError("INVALID_ACCOUNT_RESPONSE")
            if spot:
                if type(account.get("canTrade")) is not bool:
                    raise InventoryError("INVALID_ACCOUNT_RESPONSE")
            else:
                # Futures V3 separates account configuration from balances.
                # Its documented response omits canTrade. Observation of this
                # shape never certifies key permissions or execution authority.
                if "canTrade" in account and type(account["canTrade"]) is not bool:
                    raise InventoryError("INVALID_ACCOUNT_RESPONSE")
                _decimal(account.get("totalWalletBalance"), signed=True)
                _decimal(account.get("availableBalance"), signed=True)
                _rows(account.get("assets"))
                _rows(account.get("positions"))
            assets = _rows(balances)
            by_asset = {}
            for value in assets:
                asset = value.get("asset")
                # Binance balances include mixed-case and non-Latin asset names.
                # They remain in memory only, never become tradable symbols/UI.
                if type(asset) is not str or not 1 <= len(asset) <= 32 or not asset.isalnum() or asset in by_asset:
                    raise InventoryError("INVALID_BALANCE_ASSET")
                if spot:
                    free, locked = _decimal(value.get("free")), _decimal(value.get("locked"))
                    with localcontext() as ctx:
                        ctx.prec = 80
                        total = free+locked
                    by_asset[asset] = (total, free, locked)
                else:
                    total, free = _decimal(value.get("balance"), signed=True), _decimal(value.get("availableBalance"), signed=True)
                    by_asset[asset] = (total, free, None)
            row["nonzero_assets"] = sum(v[0] != 0 for v in by_asset.values())
            if "USDT" in by_asset:
                total, free, locked = by_asset["USDT"]
                row["quote_balance"] = {"asset": "USDT", "total": _text(total), "free": _text(free),
                                          "locked": _text(locked) if locked is not None else None}
            if spot:
                uid = account.get("uid")
                if type(uid) in (int, str) and re.fullmatch(r"[0-9]{1,30}", str(uid)):
                    row["identity"] = "PRODUCT_ID_REPORTED_NOT_LINKED"
            else:
                aliases = {v.get("accountAlias") for v in assets if isinstance(v.get("accountAlias"), str) and 1 <= len(v["accountAlias"]) <= 128}
                if len(aliases) == 1 and all(v.get("accountAlias") in aliases for v in assets):
                    row["identity"] = "PRODUCT_ID_REPORTED_NOT_LINKED"
            known = local.get(scope, {})
            local_rows = known.get("positions", [])
            actual = {}
            if not spot:
                for v in _rows(positions):
                    quantity = _decimal(v.get("positionAmt"), signed=True)
                    symbol, side = v.get("symbol"), v.get("positionSide")
                    if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9_]{2,40}", symbol)
                            or side not in ("BOTH", "LONG", "SHORT")):
                        raise InventoryError("INVALID_POSITION_STRUCTURE")
                    if quantity == 0:
                        continue
                    if (type(symbol) is not str or not SYMBOL.fullmatch(symbol)
                            or side not in ("BOTH", "LONG", "SHORT")
                            or side == "LONG" and quantity < 0 or side == "SHORT" and quantity > 0):
                        raise InventoryError("UNSUPPORTED_POSITION_SCOPE")
                    key = (symbol, "SHORT" if side == "SHORT" or side == "BOTH" and quantity < 0 else "LONG")
                    if key in actual:
                        raise InventoryError("DUPLICATE_POSITION_SCOPE")
                    actual[key] = quantity.copy_abs()
                row["exchange_positions"] = len(actual)
            if known.get("state") == "OBSERVED":
                row["local_positions"] = len(local_rows)
                row["local_at"] = known.get("at")
                if spot:
                    covered = all(s["symbol"][:-4] in by_asset and by_asset[s["symbol"][:-4]][0] >= _decimal(s["quantity"]) for s in local_rows)
                    row["quantity_check"] = "BALANCE_COVERS_LOCAL_AT_CUT" if covered else "DIFFERENT_CUT_REQUIRES_RECONCILIATION"
                else:
                    expected = {(v["symbol"], v["direction"]): _decimal(v["quantity"]) for v in local_rows}
                    row["untracked_positions"] = len(actual.keys()-expected.keys())
                    row["quantity_check"] = "EXACT_QUANTITIES_AT_CUT" if actual == expected else "DIFFERENT_CUT_REQUIRES_RECONCILIATION"
            row["open_orders"] = len(_rows(orders))
            row["conditional_orders"] = len(_rows(conditional))
            row["state"] = "OBSERVED" if isinstance(account, dict) else "PARTIAL"
        except (InventoryError, KeyError, TypeError, ValueError):
            row["state"] = "PARTIAL"
            row["quantity_check"] = "UNKNOWN"
        for symbol in symbols:
            fields = {"symbol": symbol, "startTime": history_start, "endTime": int(started*1000), "limit": 1000}
            fills = fetch("fills_"+symbol, "/api/v3/myTrades" if spot else "/fapi/v1/userTrades", fields)
            try:
                counted = _rows(fills)
                if len(counted) > 1000:
                    raise ValueError()
                for v in counted:
                    _decimal(v.get("qty")); _decimal(v.get("price")); _decimal(v.get("commission"), signed=True)
                    if type(v.get("time")) is not int or not history_start <= v["time"] <= int(started*1000):
                        raise ValueError()
                if row["recent_fills"] is not None:
                    row["recent_fills"] += len(counted)
            except (InventoryError, ValueError, TypeError):
                row["recent_fills"] = None
            if not spot:
                funding = fetch("funding_"+symbol, "/fapi/v1/income", {**fields, "incomeType": "FUNDING_FEE"})
                try:
                    counted = _rows(funding)
                    if len(counted) > 1000:
                        raise ValueError()
                    for v in counted:
                        _decimal(v.get("income"), signed=True)
                        if (v.get("incomeType") != "FUNDING_FEE" or type(v.get("time")) is not int
                                or not history_start <= v["time"] <= int(started*1000)):
                            raise ValueError()
                    if row["recent_funding_rows"] is not None:
                        row["recent_funding_rows"] += len(counted)
                except (InventoryError, ValueError, TypeError):
                    row["recent_funding_rows"] = None
            info = fetch("filters_"+symbol, "/api/v3/exchangeInfo" if spot else "/fapi/v1/exchangeInfo", {"symbol": symbol})
            price = fetch("price_"+symbol, "/api/v3/ticker/price" if spot else "/fapi/v1/ticker/price", {"symbol": symbol})
            fees = fetch("fees_"+symbol, "/api/v3/account/commission" if spot else "/fapi/v1/commissionRate", {"symbol": symbol})
            # Private reproducible sizing inputs, not the remote DTO. Strictly
            # select numeric documented filters; never persist the raw response.
            try:
                matches = [v for v in _rows(info["symbols"]) if v.get("symbol") == symbol]
                p = next(v for v in price if v.get("symbol") == symbol) if isinstance(price, list) else price
                if len(matches) != 1 or p.get("symbol") != symbol:
                    raise ValueError()
                selected = {}
                for v in _rows(matches[0]["filters"]):
                    kind = v.get("filterType")
                    if kind not in ("LOT_SIZE", "MARKET_LOT_SIZE", "PRICE_FILTER", "MIN_NOTIONAL", "NOTIONAL"):
                        continue
                    if kind in selected:
                        raise ValueError()
                    selected[kind] = {k: _text(_decimal(v[k])) for k in ("stepSize", "minQty", "maxQty", "tickSize", "minNotional", "notional") if k in v}
                selected_price = _text(_decimal(p.get("price")))
                if fees is None:
                    raise ValueError()
                rate = _text(_decimal(fees["standardCommission"]["taker"])) if spot else _text(_decimal(fees["takerCommissionRate"]))
                result["market_inputs"].append({"environment": scope, "symbol": symbol, "at": _iso(clock()),
                    "reference_price": selected_price, "taker_fee_rate": rate, "filters": selected,
                    "fee_scope": "STANDARD_ONLY_EXTRA_COMMISSION_AND_DISCOUNTS_NOT_APPLIED" if spot else "REPORTED_TAKER_ONLY",
                    "all_exchange_filters_validated": False})
            except (ValueError, KeyError, TypeError, StopIteration):
                pass
        # The earliest participating cut, never the end of all later history/
        # market calls. Receipts are not exchange publication timestamps.
        base_names = ("account", "open_orders", "conditional_orders") if spot else ("account", "balance", "positions", "open_orders", "conditional_orders")
        stamps = [observations[key]["requested_at"] for key in base_names if observations[key]["state"] == "OBSERVED"]
        if row["quantity_check"] != "UNKNOWN":
            if row["local_at"] is None:
                stamps = []
            else:
                stamps.append(row["local_at"])
        row["at"] = min(stamps) if stamps else None
        result["accounts"].append(row)
    result["at"], result["calls"] = _iso(clock()), transport.calls
    return result
