"""Source provenance checks. An allowed publisher is not a verified claim."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit


NEWS_PUBLISHER_DOMAINS = (
    "finance.yahoo.com", "cnbc.com", "businesstimes.com.sg", "reuters.com",
    "apnews.com", "bloomberg.com", "ft.com", "wsj.com", "bbc.com",
    "channelnewsasia.com", "straitstimes.com", "federalreserve.gov", "mas.gov.sg",
)


def safe_source_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        return value.strip()
    except ValueError:
        return None


def news_source_policy(source_url: object, publisher_url: object = None) -> str:
    """Check domains, never a self-declared publisher name or substring."""

    article = safe_source_url(source_url)
    if not article:
        return "unreviewed_publisher"
    article_host = urlsplit(article).hostname or ""
    candidate = article
    if article_host == "news.google.com":
        candidate = safe_source_url(publisher_url)
        if not candidate:
            return "unreviewed_publisher"
    host = urlsplit(candidate).hostname or ""
    allowed = any(host == domain or host.endswith("." + domain) for domain in NEWS_PUBLISHER_DOMAINS)
    return "allowlisted_publisher" if allowed else "unreviewed_publisher"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
