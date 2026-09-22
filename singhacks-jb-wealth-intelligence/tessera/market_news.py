"""Deterministic RSS ingestion for approved live market signals."""

from __future__ import annotations

import html
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree


_STATE_LOCK = threading.Lock()

DEFAULT_FEEDS = (
    "https://finance.yahoo.com/rss/topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.businesstimes.com.sg/rss/companies-markets",
)
FEED_PUBLISHERS = {
    DEFAULT_FEEDS[0]: "Yahoo Finance",
    DEFAULT_FEEDS[1]: "CNBC",
    DEFAULT_FEEDS[2]: "The Business Times",
}
DEFAULT_GOOGLE_QUERIES = (
    "global markets finance",
    "Federal Reserve markets",
    "oil shipping geopolitics",
)
SEVERITY_KEYWORDS = {
    "Severe": ("war", "blockade", "default", "emergency", "attack", "closure"),
    "High": ("surge", "plunge", "crisis", "sanction", "tariff", "rate hike", "oil"),
    "Medium": ("market", "inflation", "yield", "central bank", "earnings"),
}
TRANSMISSION_KEYWORDS = {
    "Energy, shipping, rates and risk assets": (
        "oil", "gas", "shipping", "tanker", "energy", "rate", "yield", "central bank"
    ),
    "Global risk assets": ("market", "equity", "stock", "bond", "credit", "tariff"),
}


def enabled() -> bool:
    return os.environ.get("TESSERA_LIVE_NEWS_ENABLED", "true").lower() in {"1", "true", "yes"}


def _feed_urls() -> tuple[str, ...]:
    configured = os.environ.get("TESSERA_NEWS_FEEDS", "").strip()
    if configured:
        return tuple(item.strip() for item in configured.split(",") if item.strip())
    return DEFAULT_FEEDS + tuple(
        "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-SG&gl=SG&ceid=SG:en"
        for query in DEFAULT_GOOGLE_QUERIES
    )


def _text(item: ElementTree.Element, name: str) -> str:
    node = item.find(name)
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def _clean_fragment(value: str) -> str:
    anchor = re.search(r">([^<>]+)</a>", value, flags=re.IGNORECASE)
    if anchor:
        value = anchor.group(1)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def _normalise_event(event: dict[str, str]) -> dict[str, str]:
    cleaned = dict(event)
    cleaned["description"] = _clean_fragment(str(event.get("description", "")))
    return cleaned


def _event_date(value: str) -> str:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc).date().isoformat()


def _approved_event(item: ElementTree.Element, feed_publisher: str = "") -> dict[str, str] | None:
    raw_title = _text(item, "title")
    raw_summary = _text(item, "description")
    source_name = _text(item, "source")
    title = _clean_fragment(raw_summary) or _clean_fragment(raw_title)
    if source_name and title.endswith(f" - {source_name}"):
        title = title[: -len(source_name) - 3].rstrip()
    link = _text(item, "link")
    text = f"{title} {raw_title} {raw_summary}".lower()
    matched = [keyword for keywords in TRANSMISSION_KEYWORDS.values() for keyword in keywords if keyword in text]
    if len(set(matched)) < 2:
        return None
    severity = next(
        (level for level, keywords in SEVERITY_KEYWORDS.items() if any(keyword in text for keyword in keywords)),
        "Low",
    )
    transmission = next(
        label for label, keywords in TRANSMISSION_KEYWORDS.items() if any(keyword in text for keyword in keywords)
    )
    guid = _text(item, "guid") or link or title
    return {
        "event_id": f"rss:{guid}",
        "event_date": _event_date(_text(item, "pubDate")),
        "event_type": "Live market signal",
        "region": "Global",
        "description": title,
        "primary_transmission": transmission,
        "severity": severity,
        "source": link,
        "publisher": source_name or feed_publisher,
        "source_type": "live_news",
        "status": "approved",
    }


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, list) else []


def refresh(data_dir: str | Path, state_path: str | Path) -> dict[str, object]:
    """Fetch feeds and persist newly approved, deduplicated market events."""

    if not enabled():
        return {"status": "disabled", "added": 0, "events": _read(Path(state_path))}
    feeds = _feed_urls()
    if not feeds:
        raise RuntimeError("No market-news feeds are configured")

    def fetch_feed(feed_url: str):
        try:
            request = Request(feed_url, headers={"User-Agent": "Mozilla/5.0 TESSERA/1.0"})
            with urlopen(request, timeout=8) as response:
                return ElementTree.fromstring(response.read())
        except (OSError, ElementTree.ParseError):
            return None

    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        roots = list(pool.map(fetch_feed, feeds))
    if all(root is None for root in roots):
        raise RuntimeError("All market-news feeds are unavailable")

    state = Path(state_path)
    with _STATE_LOCK:
        stored = _read(state)
        existing = [_normalise_event(item) for item in stored]
        known = {item.get("event_id") for item in existing}
        added: list[dict[str, str]] = []
        for feed_url, root in zip(feeds, roots):
            if root is None:
                continue
            for item in root.findall(".//item"):
                event = _approved_event(item, FEED_PUBLISHERS.get(feed_url, ""))
                if event and event["event_id"] not in known:
                    known.add(event["event_id"])
                    added.append(event)
        events = sorted(existing + added, key=lambda item: (item.get("event_date", ""), item.get("event_id", "")))
        if added or existing != stored or not state.exists():
            state.parent.mkdir(parents=True, exist_ok=True)
            temporary = state.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                # allow_nan=False keeps the stored register strict JSON; NaN
                # elsewhere would break every client that parses this file.
                json.dump(events, handle, ensure_ascii=True, allow_nan=False, default=str, indent=2)
                handle.write("\n")
            temporary.replace(state)
    return {"status": "partial" if None in roots else "refreshed", "added": len(added), "events": events}