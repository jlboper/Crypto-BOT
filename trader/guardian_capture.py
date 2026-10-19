"""Strictly read-only, bounded Guardian evidence acquisition.

No engine, ledger constructor, model, transport or network imports. Each database
has its own read transaction; the four observations are NOT globally atomic.
The supervised Guardian service schedules and persists this evidence. This module has
no controls, reservations, order hooks, schema initialization or journal writes.
SQLite may create/update WAL shared-memory coordination files for a read-only
connection; financial rows, schema and existing DB/WAL content remain read-only.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
import json
import math
from pathlib import Path
import re
import sqlite3
import time

MAX_BYTES = 65536
MAX_VALUE_BYTES = 65536
MAX_POSITIONS = 10
MAX_QUERY_ROWS = 100
TIMEOUT_SECONDS = .25
QUANT_SYMBOLS = frozenset(("BTCUSDT", "ETHUSDT", "SOLUSDT"))
SYMBOL = re.compile(r"^[A-Z0-9]{3,20}USDT$")


class EvidenceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _at(value):
    if type(value) in (int, float) and math.isfinite(value) and value > 0:
        return float(value)
    if isinstance(value, str) and len(value) <= 48:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                result = parsed.timestamp()
                return result if math.isfinite(result) and result > 0 else None
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _iso(value):
    stamp = _at(value)
    if stamp is None:
        return None
    instant = datetime.fromtimestamp(stamp, UTC)
    # ISO has microsecond resolution. Never round a real receipt into the future
    # relative to its exact numeric cutoff (e.g. .1234567 -> .123457).
    if instant.timestamp() > stamp:
        instant -= timedelta(microseconds=1)
    return instant.isoformat()


def _number(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e15 or positive and value <= 0:
        raise EvidenceError("MALFORMED_EVIDENCE")
    return value


def _known(value, cutoff):
    stamp = _at(value)
    return stamp is not None and stamp <= cutoff


def _fresh(value, cutoff, maximum):
    stamp = _at(value)
    return stamp is not None and 0 <= cutoff-stamp <= maximum


def _json(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_VALUE_BYTES:
        raise EvidenceError("VALUE_LIMIT")
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        # Bound object depth/width, finite numbers, and strings before projection.
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if count > 10000 or depth > 20:
                raise ValueError()
            if isinstance(item, dict):
                if any(not isinstance(key, str) or len(key) > 120 for key in item):
                    raise ValueError()
                pending.extend((v, depth+1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth+1) for v in item)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError()
            elif isinstance(item, str) and len(item) > 12000:
                raise ValueError()
        return value
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise EvidenceError("MALFORMED_EVIDENCE") from None


def _object(raw):
    value = _json(raw)
    if not isinstance(value, dict):
        raise EvidenceError("MALFORMED_EVIDENCE")
    return value


def _read_settings(db, table, keys):
    if len(keys) > MAX_QUERY_ROWS:
        raise EvidenceError("QUERY_LIMIT")
    # table names are internal constants, never caller/provider content.
    return dict(db.execute(f"SELECT key,value FROM {table} WHERE key IN ({','.join('?' for _ in keys)}) LIMIT 100", keys))


def _setting_json(settings, key, fallback):
    return _json(settings[key]) if key in settings else fallback


@contextmanager
def _read_only(path):
    path = Path(path)
    if not path.is_file():
        raise EvidenceError("MISSING_DATABASE")
    with path.open("rb") as handle:
        header = handle.read(100)
    if len(header) < 100 or not header.startswith(b"SQLite format 3\0"):
        raise EvidenceError("INVALID_DATABASE")
    # A normally closed WAL database retains its WAL-mode header after SQLite
    # removes its sidecars. Let mode=ro use SQLite's normal WAL coordination,
    # including creation of absent -wal/-shm files when directory permissions
    # allow it. Never use immutable here: an active writer's committed WAL must
    # remain visible, and each short BEGIN must keep its consistent read view.
    db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=TIMEOUT_SECONDS)
    try:
        db.row_factory = sqlite3.Row
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES*2)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        started = time.monotonic()
        db.set_progress_handler(lambda: int(time.monotonic()-started > .75), 1000)
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def _positions(db, table, metadata, *, maximum=MAX_POSITIONS):
    count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    metadata["positions_seen"] = count
    if count > maximum:
        raise EvidenceError("INVENTORY_LIMIT")
    rows = [dict(row) for row in db.execute(f"SELECT * FROM {table} LIMIT ?", (maximum,))]
    if len(rows) != count:
        raise EvidenceError("INCOMPLETE_INVENTORY")
    metadata.update(positions_returned=count, inventory_complete=True)
    return rows


def _copy_known(row, fields):
    result = {key: row[key] for key in fields if key in row}
    for key, value in result.items():
        if isinstance(value, str) and len(value) > (300 if key == "reason" else 120):
            result[key] = value[:300 if key == "reason" else 120]
        elif type(value) in (int, float):
            _number(value)
    return result


def _position(row, *, cutoff):
    result = _copy_known(row, ("symbol", "quantity", "entry_price", "stop_price", "take_profit", "opened_at", "direction", "leverage"))
    if not SYMBOL.fullmatch(str(result.get("symbol", ""))) or not _known(result.get("opened_at"), cutoff):
        raise EvidenceError("FUTURE_OR_INVALID_POSITION")
    _number(result.get("quantity"), positive=True)
    _number(result.get("entry_price"), positive=True)
    return result


def _native(raw, cutoff):
    if not isinstance(raw, dict) or len(raw) > MAX_POSITIONS:
        raise EvidenceError("MALFORMED_PROTECTION")
    projected = {}
    for symbol, row in raw.items():
        if not SYMBOL.fullmatch(symbol) or not isinstance(row, dict):
            raise EvidenceError("MALFORMED_PROTECTION")
        value = _copy_known(row, ("status", "quantity", "stop_price", "take_profit", "confirmed_at"))
        if value.get("status") == "ARMED" and not _known(value.get("confirmed_at"), cutoff):
            value["status"] = "UNCONFIRMED"
        projected[symbol] = value
    return {"supported": True, "positions": projected}


def _pause_marker(settings):
    """Read an existing owner-configured marker; never create/remove it."""
    marker = getattr(settings,"kill_switch_path",None)
    return Path(marker).exists() if marker is not None else None


def _spot(config, cutoff, metadata):
    with _read_only(config.bot.database_path) as db:
        settings = _read_settings(db, "settings", ("market_prices", "market_prices_at", "spot_last_cycle", "spot_native_protection", "paper_risk_profile"))
        rows = _positions(db, "positions", metadata)
        positions = [_position(row, cutoff=cutoff) for row in rows]
        equity = [dict(row) for row in db.execute("SELECT equity,cash,exposure,created_at FROM equity ORDER BY id DESC LIMIT 1")]
        if equity and (not _known(equity[0]["created_at"], cutoff) or any(type(equity[0][key]) not in (int,float) or not math.isfinite(equity[0][key]) for key in ("equity","cash","exposure"))):
            raise EvidenceError("FUTURE_OR_INVALID_EQUITY")
        prices = _setting_json(settings, "market_prices", {})
        if not isinstance(prices, dict) or len(prices) > 100:
            raise EvidenceError("MALFORMED_PRICES")
        prices_at = settings.get("market_prices_at")
        if prices_at is not None and not _known(prices_at,cutoff):
            metadata["source_at"] = prices_at
            raise EvidenceError("FUTURE_SOURCE")
        maximum = max(config.bot.cycle_seconds*1.5, config.bot.cycle_seconds+120)
        for position in positions:
            mark = prices.get(position["symbol"])
            position["market_price"] = _number(mark, positive=True) if mark is not None and _fresh(prices_at, cutoff, maximum) else None
            position["priced_at"] = prices_at
        reviews = []
        for row in db.execute("SELECT id,symbol,verdict,confidence,risk_multiplier,reason,created_at FROM ai_reviews ORDER BY id DESC LIMIT 12"):
            if _known(row["created_at"], cutoff):
                reviews.append(_copy_known(dict(row), ("id","symbol","verdict","confidence","risk_multiplier","reason","created_at")))
        risk = asdict(config.risk) if is_dataclass(config.risk) else dict(vars(config.risk))
        source_at = prices_at if positions else equity[0]["created_at"] if equity else None
        metadata["source_at"] = source_at
        if source_at is not None and not _known(source_at, cutoff):
            raise EvidenceError("FUTURE_SOURCE")
        metadata.update(source_at=source_at, _maximum=maximum)
        return {"status": {"mode": str(config.bot.mode).upper(), "cycle_seconds":config.bot.cycle_seconds,
                           "risk":risk, "native_protection":_native(_setting_json(settings,"spot_native_protection",{}),cutoff),
                           "spot_cycle":_setting_json(settings,"spot_last_cycle",None),
                           "paper_risk_profile":settings.get("paper_risk_profile"),"killed":_pause_marker(config.bot)},
                "risk":risk, "positions":positions, "equity":equity,
                "paper_scorecard":{"prices_at":prices_at}, "reviews":reviews, "ai_reviews":reviews}


def _futures(config, cutoff, metadata):
    symbols = tuple(config.futures_testnet.forward_symbols)
    if len(symbols) > 15 or any(not isinstance(s,str) or not SYMBOL.fullmatch(s) for s in symbols):
        raise EvidenceError("SYMBOL_LIMIT")
    base = ("forward_position_metrics", "forward_portfolio_budget", "forward_last_cycle_diagnostic", "forward_native_protection")
    keys = base+tuple("forward_last_ai_review_"+s for s in symbols)+tuple("forward_last_signal_"+s for s in symbols)
    with _read_only(config.futures_testnet.database_path) as db:
        settings = _read_settings(db,"settings",keys)
        positions = [_position(row,cutoff=cutoff) for row in _positions(db,"forward_position",metadata)]
        equity = [dict(row) for row in db.execute("SELECT wallet_balance,available_balance,unrealized_pnl,created_at FROM forward_equity ORDER BY id DESC LIMIT 1")]
        if equity and not _known(equity[0]["created_at"],cutoff):
            raise EvidenceError("FUTURE_OR_INVALID_EQUITY")
        for row in equity:
            for key in ("wallet_balance","available_balance","unrealized_pnl"):
                _number(row[key])
        metrics = _setting_json(settings,"forward_position_metrics",{})
        if not isinstance(metrics,dict) or not isinstance(metrics.get("positions",{}),dict):
            raise EvidenceError("MALFORMED_PRICES")
        if metrics.get("at") is not None and not _known(metrics["at"],cutoff):
            metadata["source_at"] = metrics["at"]
            raise EvidenceError("FUTURE_SOURCE")
        for position in positions:
            value = metrics.get("positions",{}).get(position["symbol"],{})
            identity = isinstance(value,dict) and value.get("opened_at")==position["opened_at"] and value.get("quantity")==position["quantity"]
            position.update(mark_price=None,priced_at=metrics.get("at"))
            if identity and _fresh(metrics.get("at"),cutoff,600):
                position["mark_price"] = _number(value.get("mark_price"),positive=True)
                position["unrealized_pnl_usdt"] = _number(value.get("unrealized_pnl_usdt"))
        budget = _setting_json(settings,"forward_portfolio_budget",{})
        cycle = _setting_json(settings,"forward_last_cycle_diagnostic",{})
        if not isinstance(budget,dict) or not isinstance(cycle,dict):
            raise EvidenceError("MALFORMED_EVIDENCE")
        if any(value.get("at") is not None and not _known(value["at"],cutoff) for value in (budget,cycle)):
            raise EvidenceError("FUTURE_SOURCE")
        source_at = cycle.get("at") or (equity[0]["created_at"] if equity else None) or budget.get("at")
        metadata["source_at"] = source_at
        if source_at is not None and not _known(source_at,cutoff):
            raise EvidenceError("FUTURE_SOURCE")
        reviews, signals = {}, {}
        for symbol in symbols:
            for prefix,target in (("forward_last_ai_review_",reviews),("forward_last_signal_",signals)):
                value = _setting_json(settings,prefix+symbol,None)
                if isinstance(value,dict) and _known(value.get("at"),cutoff):
                    target[symbol] = _copy_known(value, ("verdict","confidence","risk_multiplier","reason","direction","score","at","model","symbol","price","proposed_notional_usdt","proposed_quantity","estimated_stop_loss_usdt","proposed_leverage","candle_close_utc"))
        metadata.update(source_at=source_at,_maximum=600)
        return {"state":"OBSERVING","initialized":True,"positions":positions,"equity":equity,
                "killed":_pause_marker(config.futures_testnet),
                "portfolio_budget":_copy_known(budget,("at","notional_usdt","stop_loss_usdt","notional_limit_usdt","stop_loss_limit_usdt")),
                "cycle_diagnostic":_copy_known(cycle,("at","status","reason_code")),
                "native_protection":_native(_setting_json(settings,"forward_native_protection",{}),cutoff),
                "guardrails":{"forward_total_notional_usdt":config.futures_testnet.forward_total_notional_usdt,
                              "forward_total_stop_loss_usdt":config.futures_testnet.forward_total_stop_loss_usdt},
                "last_ai_reviews":reviews,"latest_signals":signals}


def _pulse(config, cutoff, metadata):
    with _read_only(Path(config.bot.database_path).parent/"market-pulse.db") as db:
        settings = _read_settings(db,"pulse_meta",("market","updated_at","initial_capital","cash","hypotheses","paused","health"))
        at = float(settings.get("updated_at","0")) or None
        metadata["source_at"] = _iso(at)
        if at is None or not _known(at,cutoff):
            raise EvidenceError("FUTURE_OR_MISSING_SOURCE")
        market = _setting_json(settings,"market",[])
        if not isinstance(market,list) or len(market)>10:
            raise EvidenceError("MARKET_LIMIT")
        projected, by_symbol = [], {}
        for item in market:
            if not isinstance(item,dict) or not SYMBOL.fullmatch(str(item.get("symbol",""))) or not _known(item.get("at"),cutoff):
                raise EvidenceError("FUTURE_OR_INVALID_MARKET")
            row = _copy_known(item,("symbol","price","change_1m_pct","change_5m_pct","relative_volume","anomaly_z","momentum","acceleration","volatility_pct","spread_bps","depth_quote","imbalance","liquidity_change_pct","complete","fresh","at"))
            row["fresh"] = item.get("fresh") is True and _fresh(item["at"],cutoff,30) and _fresh(at,cutoff,30)
            projected.append(row)
            by_symbol[row["symbol"]] = row
        positions = []
        for row in _positions(db,"pulse_positions",metadata,maximum=3):
            value = _object(row["data"])
            position = _position({**value,"stop_price":value.get("stop")},cutoff=cutoff)
            position["stop"] = value.get("stop")
            item = by_symbol.get(position["symbol"],{})
            position["mark_price"] = _number(value.get("mark_price"),positive=True) if item.get("fresh") else None
            position["environment"] = "SHADOW"
            positions.append(position)
        cash, initial = _number(float(settings["cash"])), _number(float(settings["initial_capital"]),positive=True)
        hypotheses = _setting_json(settings,"hypotheses",{})
        if not isinstance(hypotheses,dict):
            raise EvidenceError("MALFORMED_HYPOTHESES")
        fee,slip = _number(hypotheses.get("fee_bps")),_number(hypotheses.get("slippage_bps"))
        fraction = _number(hypotheses.get("max_exposure_fraction"),positive=True)
        if not (0<=fee<=100 and 0<=slip<=100 and fraction<=.15):
            raise EvidenceError("MALFORMED_HYPOTHESES")
        rate = (fee+slip)/10000
        equity = cash+sum(p["quantity"]*p["mark_price"]*(1-rate) for p in positions) if all(p["mark_price"] is not None for p in positions) else None
        paused = bool(settings.get("paused") or _pause_marker(getattr(config,"market_pulse",None)))
        metadata.update(source_at=_iso(at),_maximum=30)
        return {"schema":1,"engine":"AI_MARKET_PULSE","mode":"SHADOW","execution_enabled":False,
                "state":"PAUSED" if paused else "SHADOW" if _fresh(at,cutoff,30) else "DEGRADED","paused":paused,
                "updated_at":_iso(at),"freshness":{"state":"FRESH" if _fresh(at,cutoff,30) else "STALE","age_seconds":cutoff-at},
                "market":projected,"positions":positions,"performance":{"initial_capital":initial,"equity":equity,"cash":cash},
                "health":{},"limits":{"gross_usdt":equity*fraction if equity is not None else None}}


def _quant(config, cutoff, metadata):
    with _read_only(Path(config.bot.database_path).parent/"quant-shadow.db") as db:
        keys = ("market_updated_at","last_evaluation","hypotheses","source","wallet_balance","initial_capital","paused","kill_switch_active")
        settings = _read_settings(db,"quant_meta",keys)
        at = float(settings.get("market_updated_at","0")) or None
        metadata["source_at"] = _iso(at)
        if at is None or not _known(at,cutoff):
            raise EvidenceError("FUTURE_OR_MISSING_SOURCE")
        source = _setting_json(settings,"source",{})
        hypotheses = _setting_json(settings,"hypotheses",{})
        if not isinstance(source,dict) or not isinstance(source.get("markets"),list) or len(source["markets"])>3 or not isinstance(hypotheses,dict):
            raise EvidenceError("MALFORMED_EVIDENCE")
        fraction = _number(hypotheses.get("max_exposure_fraction"),positive=True)
        if fraction>.15:
            raise EvidenceError("MALFORMED_HYPOTHESES")
        markets = {}
        for row in source["markets"]:
            if not isinstance(row,dict) or row.get("symbol") not in QUANT_SYMBOLS or row["symbol"] in markets:
                raise EvidenceError("MALFORMED_MARKET_IDENTITY")
            markets[row["symbol"]]=row
            for venue in ("spot","futures"):
                quote=row.get(venue)
                if quote is not None and (not isinstance(quote,dict) or quote.get("symbol")!=row["symbol"]):
                    raise EvidenceError("MALFORMED_MARKET_IDENTITY")
                if quote is not None and (not _known(quote.get("at"),cutoff) or not _known(quote.get("received_at"),cutoff)):
                    raise EvidenceError("FUTURE_OR_INVALID_MARKET")
        positions = []
        for row in _positions(db,"quant_positions",metadata,maximum=2):
            value = _object(row["data"])
            if not _known(value.get("opened"),cutoff) or not isinstance(value.get("legs"),list) or len(value["legs"])!=2:
                raise EvidenceError("MALFORMED_POSITION")
            position = _copy_known(value,("id","strategy","instrument","collateral_usdt","risk_budget_usdt"))
            legs = []
            for original in value["legs"]:
                leg = _copy_known(original,("symbol","venue","direction","quantity","entry_price"))
                if leg.get("symbol") not in QUANT_SYMBOLS or leg.get("venue") not in {"SPOT_REFERENCE","FUTURES_REFERENCE"} or leg.get("direction") not in {"LONG","SHORT"}:
                    raise EvidenceError("MALFORMED_POSITION")
                _number(leg.get("quantity"),positive=True)
                quote = markets.get(leg["symbol"],{}).get("spot" if leg["venue"]=="SPOT_REFERENCE" else "futures",{})
                valid = isinstance(quote,dict) and _fresh(quote.get("at"),cutoff,90) and _fresh(quote.get("received_at"),cutoff,90)
                leg.update(mark_price=None,priced_at=quote.get("at") if isinstance(quote,dict) else None,
                           received_at=quote.get("received_at") if isinstance(quote,dict) else None,state="STALE")
                if valid:
                    bid,ask = _number(quote.get("bid"),positive=True),_number(quote.get("ask"),positive=True)
                    if ask < bid or quote.get("symbol")!=leg["symbol"]:
                        raise EvidenceError("MALFORMED_PRICES")
                    leg.update(mark_price=(bid+ask)/2,state="FRESH",priced_at=_iso(quote["at"]),received_at=_iso(quote["received_at"]))
                legs.append(leg)
            position.update(legs=legs,opened_at=_iso(value["opened"]))
            positions.append(position)
        initial = _number(float(settings["initial_capital"]),positive=True)
        cash = _number(float(settings["wallet_balance"]))-sum(_number(p.get("collateral_usdt")) for p in positions)
        equity_rows = list(db.execute("SELECT equity,data FROM quant_equity ORDER BY at DESC LIMIT 1"))
        equity = None
        if equity_rows:
            point = _object(equity_rows[0]["data"])
            evaluated = float(settings.get("last_evaluation","0"))
            # Quant persists the exact numeric evaluation and publishes its ISO
            # representation in the equity row (milliseconds in current code).
            # Match that representation, rather than demanding equality with a
            # submicrosecond float. Accept historical microsecond ISO too.
            instant = datetime.fromtimestamp(evaluated, UTC)
            identities = {_at(instant.isoformat()), _at(instant.isoformat(timespec="milliseconds"))}
            if (_known(point.get("at"),cutoff) and _at(point["at"]) in identities and _fresh(evaluated,cutoff,90)
                    and all(_at(position["opened_at"])<=evaluated for position in positions)):
                equity = _number(equity_rows[0]["equity"]) if equity_rows[0]["equity"] is not None else None
        # Bars are an independent research input: never invalidate Funding/ledger
        # capture when that optional table has not yet existed or is malformed.
        bars, bars_reason = [], None
        try:
            query = "SELECT at,received,known_at,price FROM quant_closed_bars WHERE symbol='BTCUSDT' AND at<=? AND received<=? AND known_at<=? ORDER BY at DESC LIMIT 100"
            first = [dict(row) for row in db.execute(query,(cutoff,)*3)]
            second = [dict(row) for row in db.execute("SELECT at,received,known_at,price FROM quant_closed_bars WHERE symbol='BTCUSDT' AND at<? AND received<=? AND known_at<=? ORDER BY at DESC LIMIT 21",(first[-1]["at"],cutoff,cutoff))] if len(first)==100 else []
            for row in reversed(first+second):
                stamp,received,known = row["at"],row["received"],row["known_at"]
                if type(stamp) is not int or stamp%60 or not (stamp+5<=received<=known<=cutoff):
                    raise EvidenceError("MALFORMED_CLOSED_BARS")
                bars.append({"at":stamp,"received_at":received,"known_at":known,"price":_number(row["price"],positive=True)})
        except (sqlite3.Error,EvidenceError,TypeError):
            bars,bars_reason = [],"CLOSED_BARS_UNAVAILABLE"
        metadata.update(source_at=_iso(at),_maximum=90,closed_bars_reason=bars_reason)
        paused = bool(settings.get("paused") or settings.get("kill_switch_active") or _pause_marker(getattr(config,"quant_arbitrage",None)))
        result = {"schema":1,"engine":"QUANT_ARBITRAGE","mode":"SHADOW","initialized":True,
                  "execution_enabled":False,"promotion_allowed":False,
                  "state":"PAUSED" if paused else "SHADOW" if _fresh(at,cutoff,90) else "DEGRADED","paused":paused,
                  "updated_at":_iso(at),"freshness":{"state":"FRESH" if _fresh(at,cutoff,90) else "STALE","age_seconds":cutoff-at},
                  "positions":positions,"performance":{"initial_capital":initial,"equity":equity,"cash":cash},
                  "limits":{"gross_usdt":equity*fraction if equity is not None else None}}
        return result,bars


def _unknown_source():
    return {"state":"UNKNOWN","reason":"UNAVAILABLE","captured_at":None,"source_at":None,"available_at":None,
            "positions_seen":None,"positions_returned":0,"inventory_complete":False}


def _unknown_payload(name):
    if name=="spot":
        return {"status":{"mode":"UNKNOWN"},"positions":None,"equity":[],"paper_scorecard":{},"reviews":[],"ai_reviews":[]}
    if name=="futures":
        return {"state":"UNAVAILABLE","initialized":False,"positions":None,"equity":[],"last_ai_reviews":{},"latest_signals":{}}
    return {"schema":1,"engine":"AI_MARKET_PULSE" if name=="pulse" else "QUANT_ARBITRAGE","mode":"SHADOW",
            "state":"UNAVAILABLE","initialized":False,"execution_enabled":False,"promotion_allowed":False,
            "positions":None,"updated_at":None,"performance":{"initial_capital":None,"equity":None,"cash":None},
            "freshness":{"state":"UNAVAILABLE","age_seconds":None},"health":{"last_error":"SHADOW_LEDGER_UNAVAILABLE"}}


def capture_guardian(config, now=None):
    """Capture only evidence actually available by the explicit decision cutoff.

    ``now`` is a cutoff, never a replacement for the actual read receipt clock.
    A historical cutoff cannot turn a current database read into historical
    evidence; only previously frozen captures may be replayed historically.
    Missing/stale/partial data stays explicit. No account-wide reconciliation,
    synchronous pre-submit knowledge or global financial totals are inferred.
    """
    requested = _at(now) if now is not None else None
    if now is not None and requested is None:
        raise ValueError("Invalid Guardian capture cutoff")
    # Source receipts and data filters are finalized after all read transactions.
    started = time.time()
    cutoff = min(requested,started) if requested is not None else started
    dashboard, sources, bars = {},{},[]
    for name,reader,key in (("spot",_spot,None),("futures",_futures,"futures_forward"),("pulse",_pulse,"market_pulse"),("quant",_quant,"quant")):
        meta = _unknown_source()
        value = _unknown_payload(name)
        try:
            # Actual source completion is allowed at the final runtime cutoff;
            # an explicit cutoff remains strict and cannot admit later evidence.
            read_cutoff = min(requested,time.time()) if requested is not None else time.time()
            captured = reader(config,read_cutoff,meta)
            receipt = time.time()
            if requested is not None and receipt > requested:
                raise EvidenceError("CAPTURE_AFTER_CUTOFF")
            value = captured[0] if name=="quant" else captured
            if name=="quant":
                bars = captured[1]
            maximum = meta.pop("_maximum",None)
            meta.update(captured_at=_iso(receipt),available_at=_iso(receipt),
                        state="FRESH" if maximum and _fresh(meta["source_at"],read_cutoff,maximum) else "STALE",
                        reason=None if meta["source_at"] is not None else "SOURCE_TIME_UNAVAILABLE")
        except (EvidenceError,sqlite3.Error,OSError,ValueError,TypeError,KeyError,OverflowError,AttributeError) as error:
            meta.update(state="UNKNOWN",reason=error.code if isinstance(error,EvidenceError) else "DATABASE_BUSY" if isinstance(error,sqlite3.OperationalError) and getattr(error,"sqlite_errorcode",None) in {sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED} else "SOURCE_UNAVAILABLE",
                        captured_at=_iso(time.time()),available_at=None,inventory_complete=False,positions_returned=0)
            meta.pop("_maximum",None)
            if name=="quant":
                bars=[]
        if key:
            dashboard[key]=value
        else:
            dashboard.update(value)
        sources[name]=meta
    finish = time.time()
    cutoff = min(requested,finish) if requested is not None else finish
    result = {"schema":1,"captured_at":_iso(finish),"cutoff_at":cutoff,"dashboard":dashboard,
              "source_metadata":sources,"btc_closed_bars":bars,"globally_atomic":False,
              "execution_enabled":False,"promotion_allowed":False}
    # Bound historical/context fields first; live inventory is never truncated.
    def size():
        return len(json.dumps(result,allow_nan=False,separators=(",",":"),ensure_ascii=True).encode())
    if size()>MAX_BYTES:
        dashboard["ai_reviews"]=dashboard["reviews"]=[]
        dashboard["futures_forward"]["last_ai_reviews"]={}
        dashboard["futures_forward"]["latest_signals"]={}
        result["btc_closed_bars"]=[]
    if size()>MAX_BYTES:
        result["dashboard"]={**_unknown_payload("spot"),"futures_forward":_unknown_payload("futures"),
                             "market_pulse":_unknown_payload("pulse"),"quant":_unknown_payload("quant")}
        for meta in sources.values():
            meta.update(state="UNKNOWN",reason="CAPTURE_SIZE_LIMIT",inventory_complete=False,positions_returned=0)
    return result
