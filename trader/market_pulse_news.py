"""Untrusted event normalization and optional, bounded public RSS adapters."""
from __future__ import annotations

import hashlib
import html
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree


OFFICIAL_HOSTS = {"blog.ethereum.org": "Ethereum Foundation", "bitcoincore.org": "Bitcoin Core"}
MAX_FEED_BYTES = 1_048_576


@dataclass(frozen=True)
class NewsProvider:
    id: str
    name: str
    url: str
    kind: str
    hosts: tuple[str, ...]


# Anonymous canonical feeds verified before inclusion. Commercial news services
# that prohibit automated/AI use are deliberately absent.
NEWS_PROVIDERS = (
    NewsProvider("ethereum", "Ethereum Foundation", "https://blog.ethereum.org/en/feed.xml", "official", ("blog.ethereum.org",)),
    NewsProvider("bitcoin", "Bitcoin Core", "https://bitcoincore.org/en/rss.xml", "official", ("bitcoincore.org",)),
    NewsProvider("kraken", "Kraken", "https://blog.kraken.com/feed", "official", ("blog.kraken.com",)),
    NewsProvider("federal_reserve", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml", "regulatory", ("www.federalreserve.gov", "federalreserve.gov")),
    NewsProvider("sec", "SEC", "https://www.sec.gov/news/pressreleases.rss", "regulatory", ("www.sec.gov", "sec.gov")),
)
PUBLIC_FEEDS = tuple(provider.url for provider in NEWS_PROVIDERS)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Feed redirect refused", headers, None)


urlopen = build_opener(ProxyHandler({}), _NoRedirect()).open
ASSET_WORDS = {"BTCUSDT": r"\b(?:bitcoin|btc)\b", "ETHUSDT": r"\b(?:ethereum|ether|eth)\b",
               "SOLUSDT": r"\b(?:solana|sol)\b", "BNBUSDT": r"\b(?:binance coin|bnb)\b",
               "XRPUSDT": r"\b(?:ripple|xrp)\b", "TRXUSDT": r"\b(?:tron|trx)\b",
               "ZECUSDT": r"\b(?:zcash|zec)\b", "HYPEUSDT": r"\b(?:hyperliquid|hype)\b",
               "DOGEUSDT": r"\b(?:dogecoin|doge)\b", "LINKUSDT": r"\b(?:chainlink|link)\b"}
IMPACTS = {"positive", "negative", "neutral", "uncertain"}


def clean_text(value: object, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f<>]", " ",
                   html.unescape(re.sub(r"<[^>]*>", " ", value))))[:limit].strip()


def safe_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return ""
    if port not in {None, 443}:
        return ""
    return urlunsplit(("https", parts.hostname.lower(), parts.path, "", ""))[:240]


def timestamp(value: object) -> float | None:
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            number = float(value)
            return number if 0 < number < 32_503_680_000 else None
        if not isinstance(value, str):
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return None
        return dt.timestamp()
    except (ValueError, OverflowError, TypeError):
        return None


def iso(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value is not None else None


def normalize_event(raw: dict, received_at: float, symbols: tuple[str, ...]) -> list[dict]:
    """Classification is a conservative hypothesis, not authenticated truth.

    No claimed impact/source/credibility/action from the payload is trusted.
    Positive announcements alone can never authorize a hypothetical entry.
    """
    title = clean_text(raw.get("title"), 180)
    url = safe_url(raw.get("url"))
    published = timestamp(raw.get("published_at"))
    if not title or not url or published is None:
        return []
    host = urlsplit(url).hostname
    content = title.lower()
    rumor = bool(re.search(r"\b(?:rumou?r|unconfirmed|reportedly|speculat|may|might)\w*\b", content))
    provider = next((p for p in NEWS_PROVIDERS if host in p.hosts), None)
    official = bool(provider and provider.kind in {"official", "regulatory"})
    # A company blog is primary evidence for its own announcements, not for
    # third-party claims it reports or repeats.
    if provider and provider.id == "kraken":
        own_announcement = bool(re.search(
            r"\bkraken\s+(?:launch(?:es|ed)?|introduc(?:es|ed)|release(?:s|d)?|list(?:s|ed)?|add(?:s|ed)?|enable(?:s|d)?|support(?:s|ed)?)\b"
            r"|\b(?:now|is|are)\s+(?:available|supported|listed)\s+(?:on|at)\s+kraken\b", content))
        third_party_report = bool(re.search(
            r"\b(?:reports?|says?|discuss(?:es|ed)?|according to|comments? on|reacts? to|repeats?)\b", content))
        official = own_announcement and not third_party_report
    kind = "rumor" if rumor else "official" if official else "report"
    credibility = 0.35 if rumor else 0.90 if official else 0.65 if provider else 0.55
    positive = bool(re.search(r"\b(?:approved|approval|launch|upgrade|adoption|released)\b", content))
    negative = bool(re.search(r"\b(?:hack|exploit|outage|breach|crash|ban|lawsuit|vulnerability|fraud|charges)\b", content))
    impact = "uncertain" if rumor or (positive and negative) else "negative" if negative else "positive" if positive else "neutral"
    promotional = bool(provider and provider.id == "kraken" and re.search(
        r"\b(?:predict\w*|forecast\w*|outlook|opinion|price target|sponsor\w*|promotion\w*|giveaway|reward\w*|earn|discount|campaign|moon)\b", content))
    macro = bool(provider and provider.id == "federal_reserve")
    if promotional or macro:
        impact = "uncertain"
    reason = "Rumor requires independent verification" if rumor else "Official publisher; impact still requires market confirmation" if official else "Unverified report; excluded from confirmation"
    if published > received_at + 5:
        reason = "Future publication timestamp rejected"
    elif received_at - published > 1800:
        reason = "Publication older than 30-minute event window"
    # Receipt-time eligibility is immutable. Later wall-clock passage or an AI
    # interpretation must never rehabilitate rejected provenance/timestamps.
    timely = published <= received_at + 5 and received_at - published <= 1800
    admissible = timely and credibility >= 0.8 and kind != "rumor" and not promotional and not macro
    if promotional:
        reason = "Publisher opinion/promotion is not directional confirmation"
    elif macro:
        reason = "Official macro context; no asset-specific directional inference"
    rows = []
    # Provider-injected asset symbols are ignored; infer affected assets from text.
    affected = ("MARKET",) if macro else symbols
    for symbol in affected:
        pattern = ASSET_WORDS.get(symbol, r"\b" + re.escape(symbol.removesuffix("USDT").lower()) + r"\b")
        if symbol in {"LINKUSDT", "HYPEUSDT"}:
            name = "chainlink" if symbol == "LINKUSDT" else "hyperliquid"
            ticker = symbol.removesuffix("USDT")
            if name not in content and not re.search(r"(?<!\w)\$?" + ticker + r"(?!\w)", title):
                continue
        if macro or re.search(pattern, content):
            fingerprint = hashlib.sha256((symbol + "|" + re.sub(r"\W+", " ", content).strip()).encode()).hexdigest()
            rows.append({"id": fingerprint, "published_at": iso(published), "received_at": iso(received_at),
                         "symbol": symbol, "source": provider.name if provider else (host or "Unknown")[:80],
                         "url": url, "title": title, "impact": impact, "credibility": credibility,
                         "kind": kind, "decision": "HOLD" if macro and timely else "WAIT FOR CONFIRMATION" if admissible else "REJECT",
                         "reason": reason, "market_reaction_pct": None, "_admissible": admissible,
                         "_provider_id": provider.id if provider else None,
                         "_scope": "MARKET_CONTEXT" if macro else "ASSET"})
    return rows


def validate_review(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"impact", "confidence", "reason"}:
        raise ValueError("Invalid event review fields")
    confidence = value["confidence"]
    if value["impact"] not in IMPACTS or isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("Invalid event review classification")
    reason = clean_text(value["reason"], 240)
    if not reason:
        raise ValueError("Missing event review explanation")
    return {"impact": value["impact"], "confidence": float(confidence), "reason": reason}


def parse_feed(payload: bytes, source_url: str) -> list[dict]:
    source = urlsplit(source_url)
    provider = next((p for p in NEWS_PROVIDERS if p.url == source_url), None)
    if provider is None or len(payload) > MAX_FEED_BYTES:
        raise ValueError("Feed source or size rejected")
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("External XML entities rejected")
    root = ElementTree.fromstring(payload)
    rows = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = root.findall("./channel/item")[:24] or root.findall("a:entry", ns)[:24]
    for item in items:
        title = item.findtext("title") or item.findtext("a:title", namespaces=ns)
        url = item.findtext("link")
        if url is None:
            link = item.find("a:link", ns)
            url = link.get("href") if link is not None else None
        url = safe_url(url)
        # A feed cannot upgrade a third party's report to official news.
        if urlsplit(url).hostname not in provider.hosts:
            continue
        published = (item.findtext("pubDate") or item.findtext("a:published", namespaces=ns)
                     or item.findtext("a:updated", namespaces=ns))
        summary = item.findtext("description") or item.findtext("a:summary", namespaces=ns) or ""
        rows.append({"title": title or "", "url": url, "published_at": published,
                     "summary": clean_text(summary, 1000)})
    return rows


class PublicNewsFeeds:
    """Optional RSS access; one allowlisted publisher per bounded poll.

    Connectivity/usage terms remain provider-specific. No paid subscription,
    token, social scraper, arbitrary URL or external credential is introduced.
    """
    def __init__(self, *, clock=time.monotonic, wall_clock=time.time) -> None:
        self.index = 0
        self.clock, self.wall_clock = clock, wall_clock
        self._next_poll = 0.0
        self._lock = threading.Lock()
        self._health = {p.id: {"id": p.id, "name": p.name, "url": p.url, "kind": p.kind,
                              "state": "STANDBY", "last_update": None, "last_error": None}
                        for p in NEWS_PROVIDERS}

    def health(self) -> list[dict]:
        with self._lock:
            return [dict(self._health[p.id]) for p in NEWS_PROVIDERS][:5]

    def __call__(self) -> list[dict]:
        with self._lock:
            now = self.clock()
            if now < self._next_poll:
                return []
            provider = NEWS_PROVIDERS[self.index % len(NEWS_PROVIDERS)]
            self.index += 1
            self._next_poll = now + 60
        url = provider.url
        request = Request(url, headers={"User-Agent": "CryptoAITrader-MarketPulse/1.0"})
        try:
            with urlopen(request, timeout=5) as response:
                if response.url != url:
                    raise ValueError("Feed redirect rejected")
                payload = response.read(MAX_FEED_BYTES + 1)
            rows = parse_feed(payload, url)
            with self._lock:
                self._health[provider.id].update(state="READY", last_update=iso(self.wall_clock()), last_error=None)
            return rows
        except Exception as exc:
            code = ("NEWS_HTTP_ERROR" if isinstance(exc, HTTPError) else "NEWS_TIMEOUT"
                    if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)
                    else "NEWS_NETWORK_ERROR" if isinstance(exc, (URLError, OSError)) else "NEWS_INVALID_FEED")
            with self._lock:
                self._health[provider.id].update(state="ERROR", last_error=code)
            raise
