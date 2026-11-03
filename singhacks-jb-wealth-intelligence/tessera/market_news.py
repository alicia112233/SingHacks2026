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

from tessera import news_triage
from tessera.cloud_outputs import LIVE_EVENTS_KEY, mirror_events
from tessera.source_policy import content_hash, news_source_policy, safe_source_url


_STATE_LOCK = threading.Lock()
TRIAGE_RECENT = 60

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


def frozen() -> bool:
    """Keep the stored register but stop fetching, so a rehearsed demo stays identical."""

    return os.environ.get("TESSERA_NEWS_FROZEN", "false").lower() in {"1", "true", "yes"}


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
        return ""


def _contains_keyword(text: str, keyword: str) -> bool:
    plural = {"equity": "equities", "crisis": "crises"}.get(keyword, keyword + "s")
    pattern = "(?:" + re.escape(keyword) + "|" + re.escape(plural) + ")"
    return re.search(r"(?<!\w)" + pattern + r"(?!\w)", text, flags=re.I) is not None


def _approved_event(item: ElementTree.Element, feed_publisher: str = "") -> dict[str, str] | None:
    raw_title = _text(item, "title")
    raw_summary = _text(item, "description")
    source_name = _text(item, "source")
    title = _clean_fragment(raw_summary) or _clean_fragment(raw_title)
    if source_name and title.endswith(f" - {source_name}"):
        title = title[: -len(source_name) - 3].rstrip()
    link = _text(item, "link")
    publisher_node = item.find("source")
    publisher_url = publisher_node.get("url", "") if publisher_node is not None else ""
    publication = _text(item, "pubDate")
    text = f"{title} {_clean_fragment(raw_title)} {_clean_fragment(raw_summary)}".lower()
    matched = [keyword for keywords in TRANSMISSION_KEYWORDS.values() for keyword in keywords if _contains_keyword(text, keyword)]
    if len(set(matched)) < 2:
        return None
    severity = next(
        (level for level, keywords in SEVERITY_KEYWORDS.items() if any(_contains_keyword(text, keyword) for keyword in keywords)),
        "Low",
    )
    transmission = next(
        label for label, keywords in TRANSMISSION_KEYWORDS.items() if any(_contains_keyword(text, keyword) for keyword in keywords)
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
        "publisher_url": safe_source_url(publisher_url) or "",
        "published_at": publication,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": content_hash(title),
        "publisher_policy": news_source_policy(link, publisher_url),
        "verification_status": "external_report_not_verified",
        # This is relevance admission for the register, not factual verification.
        "status": "approved",
    }


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, list) else []


def refresh(data_dir: str | Path, state_path: str | Path, output_store=None) -> dict[str, object]:
    """Fetch feeds and persist newly approved, deduplicated market events."""

    if output_store is not None:
        mirror_events(Path(state_path), output_store.read_json(LIVE_EVENTS_KEY, []))
    if not enabled():
        return {"status": "disabled", "added": 0, "events": _read(Path(state_path))}
    if frozen():
        return {"status": "frozen", "added": 0, "events": _read(Path(state_path))}
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
        by_id = {item.get("event_id"): item for item in existing}
        provenance_updated = False
        added: list[dict[str, str]] = []
        for feed_url, root in zip(feeds, roots):
            if root is None:
                continue
            for item in root.findall(".//item"):
                event = _approved_event(item, FEED_PUBLISHERS.get(feed_url, ""))
                if event:
                    event["feed_url"] = feed_url
                if event and event["event_id"] not in known:
                    known.add(event["event_id"])
                    added.append(event)
                elif event and event["event_id"] in by_id:
                    stored_event = by_id[event["event_id"]]
                    # Preserve the first capture time and model triage on repeated fetches.
                    event["retrieved_at"] = stored_event.get("retrieved_at") or event["retrieved_at"]
                    if any(stored_event.get(key) != value for key, value in event.items()):
                        stored_event.update(event)
                        provenance_updated = True
        events = sorted(existing + added, key=lambda item: (item.get("event_date", ""), item.get("event_id", "")))
        # Only the newest headlines can score, so older ones are not sent for triage.
        triaged = news_triage.triage(events[-TRIAGE_RECENT:])
        if output_store is not None:
            events = output_store.merge_market_events(events)
            mirror_events(state, events)
            return {"status": "partial" if None in roots else "refreshed", "added": len(added), "events": events}
        if added or triaged or provenance_updated or existing != stored or not state.exists():
            state.parent.mkdir(parents=True, exist_ok=True)
            temporary = state.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                # allow_nan=False keeps the stored register strict JSON; NaN
                # elsewhere would break every client that parses this file.
                json.dump(events, handle, ensure_ascii=True, allow_nan=False, default=str, indent=2)
                handle.write("\n")
            temporary.replace(state)
    return {"status": "partial" if None in roots else "refreshed", "added": len(added), "events": events}
