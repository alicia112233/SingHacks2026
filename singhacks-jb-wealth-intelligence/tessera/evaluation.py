"""Independent recommendation evaluators for the RM decision workflow."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
DEFAULT_JUDGE_MODELS = (
    "openai/gpt-5.4",
    "anthropic/claude-sonnet-4.6",
    "google/gemini-3.7-flash",
)


def _models() -> tuple[str, ...]:
    configured = os.environ.get("TESSERA_JUDGE_MODELS", "").strip()
    if not configured:
        return DEFAULT_JUDGE_MODELS
    return tuple(model.strip() for model in configured.split(",") if model.strip())[:3]


def _external_judges_enabled() -> bool:
    return os.environ.get("TESSERA_EXTERNAL_JUDGES_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }


def _gateway_token() -> str:
    return (
        os.environ.get("AI_GATEWAY_API_KEY", "").strip()
        or os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
    )


def _client(intelligence: dict[str, Any], client_id: str) -> dict[str, Any]:
    client = intelligence.get("client_profiles", {}).get(client_id)
    if client is None:
        client = intelligence.get("featured_clients", {}).get(client_id)
    if client is None:
        raise ValueError("Unknown client")
    return client


def _recommendation(
    intelligence: dict[str, Any], client_id: str, recommendation_index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    client = _client(intelligence, client_id)
    recommendations = client.get("recommendations", [])
    if recommendation_index < 0 or recommendation_index >= len(recommendations):
        raise ValueError("Unknown recommendation")
    return client, recommendations[recommendation_index]


def _evaluation_packet(
    client: dict[str, Any], recommendation: dict[str, Any]
) -> dict[str, Any]:
    """Return a purpose-limited packet without client name, ID or raw RM notes."""

    return {
        "customer_dataset": {
            "risk_profile": client.get("risk_profile"),
            "objectives": client.get("objectives"),
            "cash_needs": client.get("cash_needs", []),
            "portfolio_position": client.get("tension", {}).get("portfolio_does"),
            "upcoming_constraint": client.get("tension", {}).get("future_demands"),
        },
        "product_dataset": {
            "asset_mix": client.get("asset_mix", []),
            "mandate_findings": client.get("mandate_findings", []),
            "credit": client.get("ltv"),
            "position_changes": client.get("position_changes", [])[:3],
        },
        "signal_dataset": {
            "controlled_events": client.get("linked_events", [])[-3:],
            "scenario_sensitivities": client.get("scenarios", []),
        },
        "recommendation": {
            "title": recommendation.get("title"),
            "detail": recommendation.get("detail"),
            "suitability_condition": recommendation.get("suitability"),
            "reversible": recommendation.get("reversible"),
        },
        "evidence_passport": client.get("evidence_passport", []),
        "deterministic_validation": recommendation.get("risk_validation", {}),
    }


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["support_for_rm_review", "revise", "block"],
        },
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "customer_fit": {"type": "integer", "minimum": 0, "maximum": 100},
        "product_fit": {"type": "integer", "minimum": 0, "maximum": 100},
        "signal_support": {"type": "integer", "minimum": 0, "maximum": 100},
        "unsupported_claims": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 180},
        },
        "conflicts": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 180},
        },
        "required_rm_checks": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 180},
        },
        "rationale": {"type": "string", "maxLength": 700},
    },
    "required": [
        "verdict",
        "score",
        "customer_fit",
        "product_fit",
        "signal_support",
        "unsupported_claims",
        "conflicts",
        "required_rm_checks",
        "rationale",
    ],
    "additionalProperties": False,
}


def _message_text(result: dict[str, Any]) -> str:
    """Normalise OpenAI-compatible string and content-part responses."""

    content = result["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text"}
        )
    raise TypeError("Provider returned an unsupported message format")


def _parse_judgement(content: str) -> dict[str, Any]:
    """Parse structured output while tolerating code fences or trailing prose."""

    candidate = content.strip()
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1 :]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
        candidate = candidate.strip()
    try:
        judgement = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise
        judgement, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(judgement, dict):
        raise TypeError("Provider judgement must be a JSON object")
    return judgement


def _normalise_judgement(judgement: dict[str, Any]) -> dict[str, Any]:
    """Validate fields used by the UI and constrain provider-supplied scores."""

    missing = [field for field in JUDGE_SCHEMA["required"] if field not in judgement]
    if missing:
        raise ValueError(f"Provider judgement omitted: {', '.join(missing)}")
    if judgement["verdict"] not in {"support_for_rm_review", "revise", "block"}:
        raise ValueError("Provider judgement returned an unknown verdict")
    for field in ("score", "customer_fit", "product_fit", "signal_support"):
        judgement[field] = max(0, min(100, int(judgement[field])))
    for field in ("unsupported_claims", "conflicts", "required_rm_checks"):
        if not isinstance(judgement[field], list):
            raise TypeError(f"Provider judgement field {field} must be a list")
    return judgement


def _call_judge(model: str, packet: dict[str, Any], token: str) -> dict[str, Any]:
    prompt = (
        "Evaluate only the supplied evidence packet. You are an independent wealth "
        "recommendation risk judge, not an investment recommender. Treat absent facts "
        "as unsupported, do not use outside knowledge, and never waive deterministic "
        "hard stops. Score whether the recommendation is safe to present for RM review, "
        "not whether an investment will make money. Return only the complete JSON "
        "object required by the schema. Keep the rationale below 80 words and each "
        "list to at most three short items."
    )
    for attempt in range(2):
        retry_instruction = (
            " A previous response was incomplete. Start over and return a fresh, "
            "compact, complete JSON object."
            if attempt
            else ""
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt + retry_instruction},
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ],
            "stream": False,
            # These judges only classify a supplied packet; hidden reasoning wastes
            # the completion budget and was truncating Claude and Gemini JSON.
            "reasoning": {"effort": "none"},
            "max_tokens": 4096,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "recommendation_risk_judgement",
                    "strict": True,
                    "schema": JUDGE_SCHEMA,
                },
            },
        }
        request = Request(
            GATEWAY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=22) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            return {
                "model": model,
                "provider": model.split("/", 1)[0],
                "status": "Unavailable",
                "error": f"Provider request failed: {str(error)[:180]}",
            }
        try:
            judgement = _normalise_judgement(
                _parse_judgement(_message_text(result))
            )
            return {
                "model": model,
                "provider": model.split("/", 1)[0],
                "status": "Completed",
                **judgement,
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            if attempt == 0:
                continue

    return {
        "model": model,
        "provider": model.split("/", 1)[0],
        "status": "Incomplete response",
        "error": (
            "The provider twice returned an incomplete structured judgement. "
            "Deterministic controls remain available; run the panel again later."
        ),
    }


def _band(score: int) -> str:
    if score < 50:
        return "Blocked"
    if score < 70:
        return "Verify first"
    if score < 85:
        return "Review ready"
    return "Strong support"


def evaluate_recommendation(
    intelligence: dict[str, Any], client_id: str, recommendation_index: int
) -> dict[str, Any]:
    client, recommendation = _recommendation(
        intelligence, client_id, recommendation_index
    )
    validation = recommendation.get("risk_validation", {})
    deterministic_score = int(validation.get("score", 0))
    dimensions = {
        item["name"]: (float(item["score"]), float(item["max"]))
        for item in validation.get("dimensions", [])
    }

    def ratio(name: str) -> float:
        score, maximum = dimensions.get(name, (0.0, 1.0))
        return score / maximum if maximum else 0.0

    dataset_lenses = {
        "customer": {
            "score": round(
                100
                * (
                    ratio("Suitability and policy") * 0.7
                    + ratio("Evidence and lineage") * 0.3
                )
            ),
            "detail": "Profile, objectives, cash needs and client constraints",
        },
        "product": {
            "score": round(
                100
                * (
                    ratio("Evidence and lineage") * 0.35
                    + ratio("Freshness and data quality") * 0.25
                    + ratio("Actionability and reversibility") * 0.15
                    + ratio("Analytical corroboration") * 0.25
                )
            ),
            "detail": "Holdings, look-through, mandates, liquidity and credit",
        },
        "signal": {
            "score": round(
                100
                * (
                    ratio("Signal relevance") * 0.55
                    + ratio("Analytical corroboration") * 0.45
                )
            ),
            "detail": "Controlled events and scenario sensitivities",
        },
    }
    scenarios = client.get("scenarios", [])
    impacts = [
        float(item["portfolio_impact_pct"])
        for item in scenarios
        if item.get("portfolio_impact_pct") is not None
    ]
    predictive = {
        "status": "Not calibrated",
        "probability": None,
        "reason": (
            "The current data contains scenario sensitivities but no labelled outcomes "
            "for an out-of-time probability model. No probability is fabricated."
        ),
        "scenario_impact_range_pct": [min(impacts), max(impacts)] if impacts else None,
    }

    models = _models()
    enabled = _external_judges_enabled()
    token = _gateway_token()
    packet = _evaluation_packet(client, recommendation)
    if enabled and token:
        judges: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(models)) as executor:
            futures = {
                executor.submit(_call_judge, model, packet, token): model
                for model in models
            }
            for future in as_completed(futures):
                judges.append(future.result())
        judges.sort(key=lambda item: models.index(item["model"]))
    else:
        reason = (
            "External judges are disabled. Set TESSERA_EXTERNAL_JUDGES_ENABLED=true "
            "and configure AI Gateway authentication to opt in."
            if not enabled
            else "AI Gateway authentication is not configured."
        )
        judges = [
            {
                "model": model,
                "provider": model.split("/", 1)[0],
                "status": "Not run",
                "reason": reason,
            }
            for model in models
        ]

    completed = [judge for judge in judges if judge["status"] == "Completed"]
    panel_score = deterministic_score
    spread = None
    consensus_rule = "Deterministic score only; external judges did not run."
    if completed:
        scores = [int(judge["score"]) for judge in completed]
        judge_median = round(median(scores))
        panel_score = min(deterministic_score, judge_median)
        spread = max(scores) - min(scores)
        consensus_rule = "Lower of deterministic score and median independent-judge score."
        if spread > 20:
            panel_score = min(panel_score, 69)
            consensus_rule += " Judge disagreement above 20 points caps the result at 69."
        if any(judge.get("verdict") == "block" for judge in completed):
            panel_score = min(panel_score, 49)
            consensus_rule += " Any judge block verdict caps the result at 49."

    return {
        "recommendation_id": f"{client_id}:{recommendation_index}",
        "recommendation_title": recommendation.get("title"),
        "datasets": dataset_lenses,
        "deterministic": {
            "score": deterministic_score,
            "band": validation.get("band", _band(deterministic_score)),
            "blockers": validation.get("blockers", []),
            "status": "Passed" if not validation.get("blockers") else "Blocked",
        },
        "predictive": predictive,
        "judges": judges,
        "consensus": {
            "score": panel_score,
            "band": _band(panel_score),
            "judge_spread": spread,
            "rule": consensus_rule,
            "rm_decision_required": True,
        },
        "privacy": (
            "Purpose-limited packet excludes client name, client ID and raw RM notes. "
            "External evaluation remains opt-in."
        ),
    }
