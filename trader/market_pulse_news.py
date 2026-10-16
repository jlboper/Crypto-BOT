"""Untrusted event normalization and optional, bounded public RSS adapters."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from xml.etree import ElementTree


OFFICIAL_HOSTS = {"blog.ethereum.org": "Ethereum Foundation", "bitcoincore.org": "Bitcoin Core"}
PUBLIC_FEEDS = ("https://blog.ethereum.org/feed.xml", "https://bitcoincore.org/en/rss.xml")
MAX_FEED_BYTES = 1_048_576


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Feed redirect refused", headers, None)


urlopen = build_opener(ProxyHandler({}), _NoRedirect()).open
ASSET_WORDS = {"BTCUSDT": r"\b(?:bitcoin|btc)\b", "ETHUSDT": r"\b(?:ethereum|ether|eth)\b",
               "SOLUSDT": r"\b(?:solana|sol)\b"}
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
    official = host in OFFICIAL_HOSTS
    kind = "rumor" if rumor else "official" if official else "report"
    credibility = 0.35 if rumor else 0.90 if official else 0.55
    positive = bool(re.search(r"\b(?:approved|approval|launch|upgrade|adoption|released)\b", content))
    negative = bool(re.search(r"\b(?:hack|exploit|outage|breach|crash|ban|lawsuit|vulnerability)\b", content))
    impact = "uncertain" if rumor or (positive and negative) else "negative" if negative else "positive" if positive else "neutral"
    reason = "Rumor requires independent verification" if rumor else "Official publisher; impact still requires market confirmation" if official else "Unverified report; excluded from confirmation"
    if published > received_at + 5:
        reason = "Future publication timestamp rejected"
    elif received_at - published > 1800:
        reason = "Publication older than 30-minute event window"
    # Receipt-time eligibility is immutable. Later wall-clock passage or an AI
    # interpretation must never rehabilitate rejected provenance/timestamps.
    admissible = (published <= received_at + 5 and received_at - published <= 1800
                  and credibility >= 0.8 and kind != "rumor")
    rows = []
    # Provider-injected asset symbols are ignored; infer affected assets from text.
    for symbol in symbols:
        if re.search(ASSET_WORDS.get(symbol, r"(?!)"), content):
            fingerprint = hashlib.sha256((symbol + "|" + re.sub(r"\W+", " ", content).strip()).encode()).hexdigest()
            rows.append({"id": fingerprint, "published_at": iso(published), "received_at": iso(received_at),
                         "symbol": symbol, "source": OFFICIAL_HOSTS.get(host, host or "Unknown")[:80],
                         "url": url, "title": title, "impact": impact, "credibility": credibility,
                         "kind": kind, "decision": "WAIT FOR CONFIRMATION" if admissible else "REJECT",
                         "reason": reason, "market_reaction_pct": None, "_admissible": admissible})
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
    if source.hostname not in OFFICIAL_HOSTS or len(payload) > MAX_FEED_BYTES:
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
        if urlsplit(url).hostname != source.hostname:
            continue
        published = (item.findtext("pubDate") or item.findtext("a:published", namespaces=ns)
                     or item.findtext("a:updated", namespaces=ns))
        rows.append({"title": title or "", "url": url, "published_at": published})
    return rows


class PublicNewsFeeds:
    """Optional RSS access; one allowlisted publisher per bounded poll.

    Connectivity/usage terms remain provider-specific. No paid subscription,
    token, social scraper, arbitrary URL or external credential is introduced.
    """
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> list[dict]:
        url = PUBLIC_FEEDS[self.index % len(PUBLIC_FEEDS)]
        self.index += 1
        request = Request(url, headers={"User-Agent": "CryptoAITrader-MarketPulse/1.0"})
        with urlopen(request, timeout=5) as response:
            if urlsplit(response.url).hostname != urlsplit(url).hostname:
                raise ValueError("Feed redirect rejected")
            payload = response.read(MAX_FEED_BYTES + 1)
        return parse_feed(payload, url)
