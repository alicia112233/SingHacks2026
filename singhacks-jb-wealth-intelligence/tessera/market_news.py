"""Deterministic RSS ingestion for approved live market signals."""

from __future__ import annotations

import html
import json
import os
import re
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree


DEFAULT_FEED_QUERIES = (
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
    return os.environ.get("TESSERA_LIVE_NEWS_ENABLED", "").lower() in {"1", "true", "yes"}


def _feed_urls() -> tuple[str, ...]:
    configured = os.environ.get("TESSERA_NEWS_FEEDS", "").strip()
    if configured:
        return tuple(item.strip() for item in configured.split(",") if item.strip())
    return tuple(
        "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-SG&gl=SG&ceid=SG:en"
        for query in DEFAULT_FEED_QUERIES
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


def _approved_event(item: ElementTree.Element) -> dict[str, str] | None:
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
    state = Path(state_path)
    existing = [_normalise_event(item) for item in _read(state)]
    known = {item.get("event_id") for item in existing}
    added: list[dict[str, str]] = []
    for feed_url in _feed_urls():
        request = Request(feed_url, headers={"User-Agent": "TESSERA/1.0 market-news monitor"})
        with urlopen(request, timeout=15) as response:
            root = ElementTree.fromstring(response.read())
        for item in root.findall(".//item"):
            event = _approved_event(item)
            if event and event["event_id"] not in known:
                known.add(event["event_id"])
                added.append(event)
    events = sorted(existing + added, key=lambda item: (item.get("event_date", ""), item.get("event_id", "")))
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = state.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(events, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
    temporary.replace(state)
    return {"status": "refreshed", "added": len(added), "events": events}


class LocalNewsScheduler:
    """Poll live feeds in a local process when explicitly enabled."""

    def __init__(self, data_dir: Path, state_path: Path, refresh_callback):
        self.data_dir = data_dir
        self.state_path = state_path
        self.refresh_callback = refresh_callback
        self.interval = max(300, int(os.environ.get("TESSERA_NEWS_INTERVAL_SECONDS", "21600")))
        self._stop = threading.Event()

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    refresh(self.data_dir, self.state_path)
                    self.refresh_callback()
                except Exception:
                    pass
                self._stop.wait(self.interval)

        threading.Thread(target=loop, name="tessera-market-news", daemon=True).start()