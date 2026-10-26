"""Public institutional context, never an order, private insider feed or flow oracle.

CFTC TFF positions are delayed contracts, not USD flows or directional intent.
EDGAR metadata confirms publication of a filing, not its transaction contents.
All timestamps and the original numeric evidence are retained for forward replay.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .market_pulse_news import iso, timestamp

MAX_BYTES = 1_048_576
MAX_SNAPSHOT_BYTES = 8000
PROVIDERS = {
    "cftc_tff": ("CFTC · CME institutional positioning", "https://publicreporting.cftc.gov/stories/s/r4w3-av2u"),
    "sec_edgar": ("SEC EDGAR · public disclosures", "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"),
}
CATEGORIES = {"CFTC_POSITIONING", "SEC_ETF_FILING", "SEC_INSIDER_FILING", "SEC_INSTITUTIONAL_FILING"}
LIMITATIONS = {
    "DELAYED_CONTEXT_NOT_ENTRY_SIGNAL", "FIRST_OBSERVED_NOT_ORIGINAL_RELEASE",
    "CONTRACTS_NOT_USD_CAPITAL", "SHORT_MAY_BE_HEDGE", "NOT_ALL_MARKET_POSITIONS",
    "FILING_CONTENT_NOT_PARSED", "NO_DIRECTION_FROM_FILING_METADATA",
    "INSIDER_EQUITY_NOT_DIRECT_CRYPTO", "THIRTEEN_F_NO_SHORTS_DELAYED",
    "ETF_NET_FLOWS_UNAVAILABLE", "ETF_HOLDINGS_NOT_FLOWS", "SEC_CONTACT_REQUIRED",
    "NO_NONPUBLIC_INFORMATION", "NO_PROVEN_TRADING_EDGE", "STALE_CONTEXT",
}
METRICS = frozenset({
    "open_interest_contracts", "dealer_long_contracts", "dealer_short_contracts",
    "asset_manager_long_contracts", "asset_manager_short_contracts",
    "leveraged_fund_long_contracts", "leveraged_fund_short_contracts",
    "asset_manager_net_contracts", "leveraged_fund_net_contracts",
    "open_interest_change_contracts", "asset_manager_net_change_contracts",
    "leveraged_fund_net_change_contracts",
})
WATCHLIST = (
    # SEC CIKs confirmed from issuer/SEC filings. Equity proxies are market
    # context: a COIN/MSTR director sale is not a sale of the bot's BTC.
    ("0001980994", "IBIT", "BTCUSDT", "ETF"),
    ("0001588489", "GBTC", "BTCUSDT", "ETF"),
    ("0001763415", "BITB", "BTCUSDT", "ETF"),
    ("0001050446", "Strategy (MSTR)", "MARKET", "EQUITY"),
    ("0001679788", "Coinbase (COIN)", "MARKET", "EQUITY"),
)
CONTRACTS = {"133741": "BTCUSDT", "146021": "ETHUSDT"}


def load_sec_contact(data_dir):
    """One explicit local contact; never inspect keys, .env or portal input."""
    path = Path(data_dir)/"market-pulse-public-sources.json"
    try:
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path, *path.parents)):
            return None
        with path.open("rb") as handle:
            raw = handle.read(1025)
        if len(raw) > 1024:
            return None
        record = _decode(raw)
        if (type(record) is not dict or set(record) != {"schema", "sec_contact"}
                or type(record["schema"]) is not int or record["schema"] != 1):
            return None
        contact = record["sec_contact"]
        if type(contact) is not str or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}", contact):
            return None
        return contact
    except (OSError, ValueError, TypeError):
        return None


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _decode(payload):
    """External JSON has one meaning: reject duplicates, nonfinite and depth."""
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("INSTITUTIONAL_DUPLICATE_JSON_KEY")
            values[key] = value
        return values
    def nonfinite(_value):
        raise ValueError("INSTITUTIONAL_NONFINITE_JSON")
    try:
        value = json.loads(payload, object_pairs_hook=unique, parse_constant=nonfinite)
        pending, count = [(value, 0)], 0
        while pending:
            row, depth = pending.pop()
            count += 1
            if depth > 16 or count > 50_000:
                raise ValueError("INSTITUTIONAL_JSON_STRUCTURE_LIMIT")
            if type(row) is dict:
                pending.extend((item, depth + 1) for item in row.values())
            elif type(row) is list:
                pending.extend((item, depth + 1) for item in row)
            elif type(row) is float and not math.isfinite(row):
                raise ValueError("INSTITUTIONAL_NONFINITE_JSON")
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValueError("INSTITUTIONAL_INVALID_JSON") from None


def _date(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T00:00:00(?:\.000)?)?", value):
        raise ValueError("INSTITUTIONAL_DATE_REQUIRED")
    return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


def _integer(value, *, signed=False):
    if type(value) is int:
        number = value
    elif type(value) is str and re.fullmatch(r"-?\d{1,12}", value):
        number = int(value)
    else:
        raise ValueError("INSTITUTIONAL_INTEGER_REQUIRED")
    if abs(number) > 1_000_000_000_000 or not signed and number < 0:
        raise ValueError("INSTITUTIONAL_INTEGER_REQUIRED")
    return number


def valid_observation(row):
    try:
        if (type(row) is not dict or set(row) != {"id", "provider", "symbol", "category", "as_of", "available_at",
                "received_at", "availability_basis", "title", "url", "metrics", "limitations", "evidence_digest"}
                or row["provider"] not in PROVIDERS or row["category"] not in CATEGORIES
                or row["symbol"] not in {"BTCUSDT", "ETHUSDT", "MARKET"}
                or any(type(row[k]) is not str or not re.fullmatch(r"[0-9a-f]{64}", row[k]) for k in ("id", "evidence_digest"))
                or type(row["title"]) is not str or not 1 <= len(row["title"]) <= 180
                or any(ord(c) < 32 or c in "<>" for c in row["title"])
                or type(row["metrics"]) is not dict or set(row["metrics"]) - METRICS
                or any(type(v) is not int or abs(v) > 10**12 for v in row["metrics"].values())
                or type(row["limitations"]) is not list or not 1 <= len(row["limitations"]) <= 8
                or any(code not in LIMITATIONS for code in row["limitations"])):
            return False
        times = [timestamp(row[k]) for k in ("as_of", "available_at", "received_at")]
        if any(v is None for v in times) or not 0 < times[0] <= times[1] <= times[2]:
            return False
        if row["category"] == "CFTC_POSITIONING":
            if (row["provider"] != "cftc_tff" or row["availability_basis"] != "FIRST_OBSERVED"
                    or row["url"] != PROVIDERS["cftc_tff"][1] or times[1] != times[2]
                    or set(row["metrics"]) != METRICS):
                return False
        elif (row["provider"] != "sec_edgar" or row["availability_basis"] != "SEC_ACCEPTANCE"
                or row["metrics"] or not re.fullmatch(r"https://www\.sec\.gov/Archives/edgar/data/\d{1,10}/\d{18}/\d{10}-\d{2}-\d{6}-index\.html", row["url"])):
            return False
        return len(_json(row)) <= 2500
    except (TypeError, ValueError, OverflowError):
        return False


@dataclass(frozen=True)
class InstitutionalObservation:
    encoded: str

    def __post_init__(self):
        if type(self.encoded) is not str or len(self.encoded) > 2500 or not valid_observation(_decode(self.encoded)):
            raise ValueError("CLOSED_INSTITUTIONAL_OBSERVATION_REQUIRED")

    @property
    def payload(self):
        return json.loads(self.encoded)


def _observation(**values):
    values["id"] = _digest({key: values[key] for key in ("provider", "symbol", "category", "evidence_digest")})
    return InstitutionalObservation(_json(values))


def parse_cftc(payload, received_at):
    if type(payload) is not bytes or len(payload) > MAX_BYTES:
        raise ValueError("CFTC_RESPONSE_LIMIT")
    rows = _decode(payload)
    if type(rows) is not list or len(rows) > 8:
        raise ValueError("CFTC_ROW_LIMIT")
    result = []
    fields = {
        "open_interest_contracts": "open_interest_all", "dealer_long_contracts": "dealer_positions_long_all",
        "dealer_short_contracts": "dealer_positions_short_all", "asset_manager_long_contracts": "asset_mgr_positions_long",
        "asset_manager_short_contracts": "asset_mgr_positions_short", "leveraged_fund_long_contracts": "lev_money_positions_long",
        "leveraged_fund_short_contracts": "lev_money_positions_short", "open_interest_change_contracts": "change_in_open_interest_all",
    }
    for raw in rows:
        if type(raw) is not dict or raw.get("cftc_contract_market_code") not in CONTRACTS:
            continue
        as_of = _date(raw.get("report_date_as_yyyy_mm_dd"))
        if not 0 <= received_at - as_of <= 21 * 86400:
            continue
        metrics = {key: _integer(raw.get(source), signed="change" in key) for key, source in fields.items()}
        oi = metrics["open_interest_contracts"]
        if not oi or any(value > oi for key, value in metrics.items() if "change" not in key):
            raise ValueError("CFTC_POSITION_TOTAL_INVALID")
        metrics["asset_manager_net_contracts"] = metrics["asset_manager_long_contracts"] - metrics["asset_manager_short_contracts"]
        metrics["leveraged_fund_net_contracts"] = metrics["leveraged_fund_long_contracts"] - metrics["leveraged_fund_short_contracts"]
        for label, prefix in (("asset_manager", "asset_mgr"), ("leveraged_fund", "lev_money")):
            metrics[label + "_net_change_contracts"] = (_integer(raw.get("change_in_" + prefix + "_long"), signed=True)
                                                       - _integer(raw.get("change_in_" + prefix + "_short"), signed=True))
        evidence = {"contract": raw["cftc_contract_market_code"], "as_of": iso(as_of), "metrics": metrics}
        result.append(_observation(provider="cftc_tff", symbol=CONTRACTS[raw["cftc_contract_market_code"]],
            category="CFTC_POSITIONING", as_of=iso(as_of), available_at=iso(received_at), received_at=iso(received_at),
            availability_basis="FIRST_OBSERVED", title="CME institutional positions · " + CONTRACTS[raw["cftc_contract_market_code"]],
            url=PROVIDERS["cftc_tff"][1], metrics=metrics,
            limitations=["DELAYED_CONTEXT_NOT_ENTRY_SIGNAL", "FIRST_OBSERVED_NOT_ORIGINAL_RELEASE", "CONTRACTS_NOT_USD_CAPITAL",
                         "SHORT_MAY_BE_HEDGE", "NOT_ALL_MARKET_POSITIONS"], evidence_digest=_digest(evidence)))
    return result[:8]


def parse_sec_submissions(payload, watch, received_at):
    if watch not in WATCHLIST or type(payload) is not bytes or len(payload) > MAX_BYTES:
        raise ValueError("SEC_SOURCE_OR_SIZE_REJECTED")
    body = _decode(payload)
    cik, label, symbol, kind = watch
    if type(body) is not dict or _integer(body.get("cik")) != int(cik):
        raise ValueError("SEC_ISSUER_IDENTITY_MISMATCH")
    filings = body.get("filings")
    if type(filings) is not dict:
        raise ValueError("SEC_SUBMISSION_SCHEMA_INVALID")
    recent = filings.get("recent", {})
    columns = ("accessionNumber", "form", "reportDate", "acceptanceDateTime")
    if (type(recent) is not dict or any(type(recent.get(key)) is not list for key in columns)
            or len({len(recent[key]) for key in columns}) != 1 or len(recent["form"]) > 2000):
        raise ValueError("SEC_SUBMISSION_SCHEMA_INVALID")
    result = []
    for accession, form, report, accepted in zip(*(recent[key] for key in columns)):
        if type(form) is not str or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(accession)):
            continue
        if kind == "ETF" and form in {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "424B3"}:
            category = "SEC_ETF_FILING"
        elif kind == "EQUITY" and form in {"3", "3/A", "4", "4/A", "5", "5/A"}:
            category = "SEC_INSIDER_FILING"
        elif form in {"13F-HR", "13F-HR/A"}:
            category = "SEC_INSTITUTIONAL_FILING"
        else:
            continue
        available = timestamp(accepted)
        if available is None or not 0 <= received_at - available <= 30 * 86400:
            continue
        try:
            as_of = _date(report) if report else available
        except ValueError:
            continue
        if as_of > available:
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.html"
        limits = ["DELAYED_CONTEXT_NOT_ENTRY_SIGNAL", "FILING_CONTENT_NOT_PARSED", "NO_DIRECTION_FROM_FILING_METADATA"]
        if category == "SEC_INSIDER_FILING": limits.append("INSIDER_EQUITY_NOT_DIRECT_CRYPTO")
        if category == "SEC_INSTITUTIONAL_FILING": limits.append("THIRTEEN_F_NO_SHORTS_DELAYED")
        if category == "SEC_ETF_FILING": limits.append("ETF_NET_FLOWS_UNAVAILABLE")
        result.append(_observation(provider="sec_edgar", symbol=symbol, category=category, as_of=iso(as_of),
            available_at=iso(available), received_at=iso(received_at), availability_basis="SEC_ACCEPTANCE",
            title=label + " · published Form " + form, url=url, metrics={}, limitations=limits,
            evidence_digest=_digest({"cik": cik, "accession": accession, "form": form, "report_date": report, "accepted": accepted})))
        if len(result) >= 4:
            break
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Institutional redirect refused", headers, None)


class InstitutionalContextFeeds:
    """At most one fixed public GET per poll. No credential or paid provider.

    SEC is disabled without an explicit owner contact email for Fair Access.
    CFTC is polled every six hours; SEC once per fifteen minutes round-robin.
    No retries in a poll, proxy inheritance, redirects, arbitrary URLs or scrape.
    """
    def __init__(self, *, sec_contact=None, clock=time.monotonic, wall_clock=time.time, opener=None):
        if sec_contact is not None and (type(sec_contact) is not str or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}", sec_contact)):
            raise ValueError("EXPLICIT_SEC_CONTACT_REQUIRED")
        self._sec_contact = sec_contact
        self.clock, self.wall_clock = clock, wall_clock
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirect()).open
        self._next = {"cftc_tff": 0., "sec_edgar": 0.}
        self._index = 0
        self._lock = threading.Lock()
        self._health = {key: {"id": key, "name": name, "url": url,
            "state": "DISABLED" if key == "sec_edgar" and not sec_contact else "STANDBY",
            "last_update": None, "last_error": "SEC_CONTACT_REQUIRED" if key == "sec_edgar" and not sec_contact else None}
            for key, (name, url) in PROVIDERS.items()}

    def health(self):
        with self._lock:
            return [dict(self._health[key]) for key in PROVIDERS]

    def __call__(self):
        with self._lock:
            now = self.clock()
            if now >= self._next["cftc_tff"]:
                provider, watch = "cftc_tff", None
                self._next[provider] = now + 21600
                query = urlencode({"$where": "cftc_contract_market_code in ('133741','146021')",
                                   "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "6"})
                url = "https://publicreporting.cftc.gov/resource/gpe5-46if.json?" + query
                user_agent = "CryptoAITrader-InstitutionalContext/1.0"
            elif self._sec_contact and now >= self._next["sec_edgar"]:
                provider = "sec_edgar"
                self._next[provider] = now + 900
                watch = WATCHLIST[self._index % len(WATCHLIST)]; self._index += 1
                url = "https://data.sec.gov/submissions/CIK" + watch[0] + ".json"
                user_agent = "CryptoAITrader InstitutionalContext " + self._sec_contact
            else:
                return []
        try:
            with self.opener(Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"}), timeout=5) as response:
                if response.url != url:
                    raise ValueError("REDIRECT_REJECTED")
                payload = response.read(MAX_BYTES + 1)
            received = self.wall_clock()
            rows = parse_cftc(payload, received) if provider == "cftc_tff" else parse_sec_submissions(payload, watch, received)
            with self._lock:
                self._health[provider].update(state="READY", last_update=iso(received), last_error=None)
            return rows
        except Exception as exc:
            code = "INSTITUTIONAL_HTTP_ERROR" if isinstance(exc, HTTPError) else "INSTITUTIONAL_UNAVAILABLE"
            with self._lock:
                self._health[provider].update(state="ERROR", last_error=code)
            return []


def institutional_snapshot(observations, providers, now):
    rows, earliest = [], {}
    for raw in observations[:64] if type(observations) in {list, tuple} else []:
        if not valid_observation(raw) or timestamp(raw["received_at"]) > now:
            continue
        # Same report/evidence polled again is one observation, not another vote.
        identity = (raw["provider"], raw["symbol"], raw["evidence_digest"])
        if identity not in earliest or timestamp(raw["received_at"]) < timestamp(earliest[identity]["received_at"]):
            earliest[identity] = raw
    for raw in sorted(earliest.values(), key=lambda value: timestamp(value["received_at"]), reverse=True):
        row = dict(raw)
        limits = list(row["limitations"])
        age_limit = 14 * 86400 if row["category"] == "CFTC_POSITIONING" else 30 * 86400
        if now - timestamp(row["as_of"]) > age_limit and "STALE_CONTEXT" not in limits:
            limits.append("STALE_CONTEXT")
        row["limitations"] = limits[:8]
        rows.append(row)
        if len(rows) >= 6:
            break
    health = []
    for raw in providers[:2] if type(providers) is list else []:
        if type(raw) is not dict or type(raw.get("id")) is not str or raw.get("id") not in PROVIDERS:
            continue
        identity = raw["id"]
        name, url = PROVIDERS[identity]
        state = raw.get("state") if type(raw.get("state")) is str and raw["state"] in {"DISABLED", "STANDBY", "READY", "ERROR"} else "ERROR"
        updated = timestamp(raw.get("last_update"))
        error = raw.get("last_error")
        if error is not None and (type(error) is not str or error not in {"SEC_CONTACT_REQUIRED", "INSTITUTIONAL_HTTP_ERROR", "INSTITUTIONAL_UNAVAILABLE"}):
            error = "INSTITUTIONAL_UNAVAILABLE"
        if updated is not None and updated > now:
            state, updated, error = "ERROR", None, "INSTITUTIONAL_UNAVAILABLE"
        health.append({"id": identity, "name": name, "url": url, "state": state,
                       "last_update": iso(updated) if updated is not None else None, "last_error": error})
    value = {"schema": 1, "mode": "CONTEXT_ONLY", "execution_enabled": False, "at": iso(now),
             "providers": health, "observations": rows,
             "limitations": ["NO_NONPUBLIC_INFORMATION", "ETF_NET_FLOWS_UNAVAILABLE", "NO_PROVEN_TRADING_EDGE"]}
    while len(_json(value)) > MAX_SNAPSHOT_BYTES and value["observations"]:
        value["observations"].pop()
    return value
