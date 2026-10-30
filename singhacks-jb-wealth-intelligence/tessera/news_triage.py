"""External models triage public headlines (C1-C2 data only).

Each model reads headline text, publisher and date, nothing about any client,
and says whether the headline matters to a private-bank book, which topics it
hits and how severe it is. Majority vote decides. When triage is off or every
model fails, the keyword rules in market_news.py and escalation.py stay in use.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tessera.escalation import NEWS_TOPICS
from tessera.evaluation import GATEWAY_URL, _gateway_token, _message_text, _parse_judgement


DEFAULT_TRIAGE_MODELS = (
    "openai/gpt-5.4",
    "anthropic/claude-sonnet-4.6",
    "google/gemini-3.7-flash",
)
TOPICS = tuple(name for name, *_ in NEWS_TOPICS)
SEVERITIES = ("Low", "Medium", "High", "Severe")
BATCH_SIZE = 25
# Only the fields below ever leave TESSERA, and all of them are public.
PUBLIC_FIELDS = ("description", "publisher", "event_date")

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "topics": {"type": "array", "items": {"type": "string", "enum": list(TOPICS)}},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                },
                "required": ["index", "relevant", "topics", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
PROMPT = (
    "You triage public financial headlines for private-bank relationship managers. "
    "For each numbered headline decide: relevant (true only if it could move listed "
    "markets, sectors, rates or commodities that a wealth portfolio holds; consumer "
    "finance tips, product promotions and show schedules are not relevant), topics "
    "(only the sectors the headline is actually about, from the allowed list; a company "
    "name that merely contains a word such as Golden is not the gold topic), and "
    "severity (Severe for wars, blockades, defaults or market closures; High for sharp "
    "moves, sanctions or crises; Medium for notable but routine moves; Low otherwise). "
    "Use only the headline text. Return JSON for every index."
)


def enabled() -> bool:
    return os.environ.get("TESSERA_NEWS_TRIAGE_ENABLED", "").lower() in {"1", "true", "yes"}


def _models() -> tuple[str, ...]:
    configured = os.environ.get("TESSERA_NEWS_MODELS", "").strip()
    if not configured:
        return DEFAULT_TRIAGE_MODELS
    return tuple(model.strip() for model in configured.split(",") if model.strip())[:3]


def public_batch(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"index": index, **{field: str(event.get(field, "")) for field in PUBLIC_FIELDS}}
        for index, event in enumerate(events)
    ]


def _ask(model: str, batch: list[dict[str, Any]], token: str) -> dict[int, dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
        ],
        "stream": False,
        "reasoning": {"effort": "none"},
        "max_tokens": 4096,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "headline_triage", "strict": True, "schema": TRIAGE_SCHEMA},
        },
    }
    request = Request(
        GATEWAY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=22) as response:
            items = _parse_judgement(_message_text(json.load(response)))["items"]
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError):
        return {}
    votes = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("severity") not in SEVERITIES:
            continue
        votes[int(item.get("index", -1))] = {
            "relevant": bool(item.get("relevant")),
            "topics": [topic for topic in item.get("topics", []) if topic in TOPICS],
            "severity": item["severity"],
        }
    return votes


def combine(votes: list[dict[str, Any]], models: list[str]) -> dict[str, Any]:
    """Majority vote across the models that answered for one headline."""

    count = len(votes)
    majority = count // 2 + 1
    relevant = sum(vote["relevant"] for vote in votes) >= majority
    topics = [topic for topic in TOPICS if sum(topic in vote["topics"] for vote in votes) >= majority]
    ranks = sorted(SEVERITIES.index(vote["severity"]) for vote in votes)
    severity = SEVERITIES[ranks[(count - 1) // 2]]
    agreeing = sum(vote["severity"] == severity for vote in votes)
    return {
        "relevant": relevant,
        "topics": topics if relevant else [],
        "severity": severity,
        "models": models,
        "agreement": f"{agreeing} of {count} models agree on severity",
    }


def triage(events: list[dict[str, Any]]) -> int:
    """Add a `triage` result to each untriaged event in place; return how many were triaged."""

    token = _gateway_token()
    pending = [event for event in events if "triage" not in event]
    if not (enabled() and token and pending):
        return 0
    models = _models()
    done = 0
    for start in range(0, len(pending), BATCH_SIZE):
        chunk = pending[start : start + BATCH_SIZE]
        batch = public_batch(chunk)
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            answers = list(pool.map(lambda model: _ask(model, batch, token), models))
        for index, event in enumerate(chunk):
            votes = [(model, answer[index]) for model, answer in zip(models, answers) if index in answer]
            if not votes:
                continue
            result = combine([vote for _, vote in votes], [model for model, _ in votes])
            event.setdefault("keyword_severity", event.get("severity", "Low"))
            event["severity"] = result["severity"]
            event["topics"] = result["topics"]
            event["triage"] = result
            done += 1
    return done
