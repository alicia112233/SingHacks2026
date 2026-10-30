"""Independent recommendation evaluators for the RM decision workflow."""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tessera.recommendation_validation import finite, fingerprint, CONTRACTS
from tessera.retrieval import retrieve_recommendation_evidence


GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
# Client data (C3-C4) may only reach the bank's in-house model. The demo has no
# in-house model, so one labelled stand-in plays that role; external models
# only ever read public headlines (see news_triage.py).
INHOUSE_STANDIN_MODEL = "anthropic/claude-sonnet-4.6"
REVIEW_ANGLES = (
    (
        "suitability",
        "Suitability and compliance",
        "Focus on suitability and compliance: the risk profile, mandate limits, risk indicators and deterministic hard stops.",
    ),
    (
        "client_fit",
        "Client fit",
        "Focus on client fit: whether the action serves the detected contradictions, cash needs and the portfolio as a whole.",
    ),
    (
        "evidence",
        "Evidence quality",
        "Focus on evidence quality: whether every claim and number in the action is backed by the supplied evidence.",
    ),
)


def _inhouse_model() -> str:
    return os.environ.get("TESSERA_INHOUSE_MODEL", "").strip() or INHOUSE_STANDIN_MODEL


def _inhouse_url() -> str:
    """An OpenAI-compatible endpoint, e.g. a local offline model, else the gateway stand-in."""

    return os.environ.get("TESSERA_INHOUSE_URL", "").strip()


def _review_enabled() -> bool:
    # The old flag name still works so existing deployments keep their setting.
    return any(
        os.environ.get(name, "").lower() in {"1", "true", "yes"}
        for name in ("TESSERA_INHOUSE_REVIEW_ENABLED", "TESSERA_EXTERNAL_JUDGES_ENABLED")
    )


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


RISK_PROFILES = {"Conservative", "Income", "Balanced", "Balanced Growth", "Growth", "Dynamic Opportunistic", "Sustainable Balanced"}
DETECTION_KINDS = {"wealth_concentration", "liquidity", "risk_profile", "currency", "duration"}
AUM_BANDS = ((10, "under USD 10m"), (25, "USD 10-25m"), (50, "USD 25-50m"), (100, "USD 50-100m"))
GENERIC_NAME_WORDS = {"family", "office", "enterprises", "group", "holdings", "trust", "capital"}


def wording_fingerprint(recommendation: dict[str, Any]) -> str:
    return fingerprint([recommendation.get(field) for field in ("title", "detail", "suitability")])


def _aum_band(value: Any) -> str | None:
    if not finite(value):
        return None
    return next((label for limit, label in AUM_BANDS if float(value) < limit), "USD 100m and above")


def _evaluation_packet(
    client: dict[str, Any],
    recommendation: dict[str, Any],
    retrieved_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the de-identified packet the model panel reviews.

    The models see the proposed action and what the client needs, never who the
    client is. Action wording is sent only when it is exactly the code-generated
    text; RM-edited wording, objectives in the client's own words, RM notes,
    names, IDs, nationality and retrieval excerpts never leave the application.
    """
    def metrics(value, fields):
        if not isinstance(value, dict):
            return {}
        return {key: value[key] for key in fields if finite(value.get(key))}

    def rows(key, fields):
        return [metrics(row, fields) for row in client.get(key, [])]

    kind = recommendation.get("assessment_kind")
    validation = recommendation.get("risk_validation", {})
    generated = recommendation.get("wording_fingerprint") and wording_fingerprint(recommendation) == recommendation.get("wording_fingerprint")
    action = {
        "assessment_kind": kind if kind in CONTRACTS else "unknown",
        "reversible": recommendation.get("reversible") is True,
    }
    if generated:
        action.update({field: recommendation.get(field) for field in ("title", "detail", "suitability")})
    else:
        action["wording"] = "Withheld: edited by the RM or not generated by TESSERA."
    risk_profile = client.get("risk_profile")
    detections = (client.get("priority") or {}).get("detections") or []
    return {
        "scope": "De-identified review of one proposed action. Client identity, the client's own words, RM notes and source references are withheld. Judge only what is supplied.",
        "proposed_action": action,
        "client_profile": {
            "risk_profile": risk_profile if isinstance(risk_profile, str) and risk_profile in RISK_PROFILES else None,
            "risk_indicators_1_to_5": metrics(client.get("risk_analysis"), ("capacity", "tolerance", "horizon")),
            "aum_band": _aum_band(client.get("aum_usd_m")),
            "detected_contradictions": [
                {"kind": item["kind"], "summary": item.get("label")}
                for item in detections
                if isinstance(item, dict) and item.get("kind") in DETECTION_KINDS
            ],
        },
        "customer_dataset": {"cash_needs": rows("cash_needs", ("amount_usd_m",))},
        "product_dataset": {
            "asset_mix": [{"asset_class": row["label"], **metrics(row, ("value",))}
                          for row in client.get("asset_mix", [])
                          if row.get("label") in {"Equity", "Fixed Income", "Cash", "Alternatives", "Structured Products", "Funds"}],
            "mandate_findings": rows("mandate_findings", ("min_pct", "max_pct", "actual_pct")),
            "credit": metrics(client.get("ltv"), ("ltv_pct", "trigger_pct", "points_to_trigger", "lending_value_buffer_m")),
            "position_changes": rows("position_changes", ("delta_usd_m",)),
        },
        "signal_dataset": {"scenarios": rows("scenarios", ("portfolio_impact_pct",))},
        "deterministic_validation": metrics(validation, ("score", "raw_score")),
    }


def outbound_privacy_check(packet: dict[str, Any], client: dict[str, Any]) -> dict[str, Any]:
    """Block the packet if anything identifying the client would leave the application."""

    text = json.dumps(packet, ensure_ascii=False).lower()
    issues = []
    if re.search(r"\bcl-\d{4}\b", text):
        issues.append("client ID")
    if re.search(r"\bn-\d{2,4}\b", text):
        issues.append("RM note reference")
    name_parts = [part for part in re.split(r"[\s,]+", str(client.get("name") or "").lower())
                  if len(part) >= 4 and part not in GENERIC_NAME_WORDS]
    if any(re.search(rf"(?<![a-z]){re.escape(part)}(?![a-z])", text) for part in name_parts):
        issues.append("client name")
    for field, label in (("objectives", "objectives in the client's own words"), ("source_of_wealth", "source of wealth")):
        value = client.get(field)
        if isinstance(value, str) and len(value) > 20 and value.lower() in text:
            issues.append(label)
    for note in client.get("notes") or []:
        snippet = str(note.get("note", ""))[:40].lower() if isinstance(note, dict) else ""
        if len(snippet) >= 20 and snippet in text:
            issues.append("RM note text")
            break
    return {"status": "Blocked" if issues else "Passed", "issues": issues}


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


def _call_judge(
    model: str,
    packet: dict[str, Any],
    token: str,
    angle: tuple[str, str, str] | None = None,
    url: str = "",
) -> dict[str, Any]:
    labels = {"angle_id": angle[0], "angle": angle[1]} if angle else {}
    provider = "local in-house model" if url else model.split("/", 1)[0]
    prompt = (
        (angle[2] + " " if angle else "")
        + "Evaluate only the supplied evidence packet. You are an independent wealth "
        "recommendation risk judge, not an investment recommender. Review the proposed "
        "action against the client profile, detected contradictions and evidence. The "
        "client is de-identified on purpose; do not ask who they are. Treat absent facts "
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
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            url or GATEWAY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=22) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            return {
                "model": model,
                "provider": provider,
                **labels,
                "status": "Unavailable",
                "error": f"Provider request failed: {str(error)[:180]}",
            }
        try:
            judgement = _normalise_judgement(
                _parse_judgement(_message_text(result))
            )
            return {
                "model": model,
                "provider": provider,
                **labels,
                "status": "Completed",
                **judgement,
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            if attempt == 0:
                continue

    return {
        "model": model,
        "provider": provider,
        **labels,
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

    model = _inhouse_model()
    url = _inhouse_url()
    enabled = _review_enabled()
    token = _gateway_token()
    retrieval = retrieve_recommendation_evidence(client, recommendation)
    packet = _evaluation_packet(client, recommendation, retrieval["evidence"])
    privacy_check = outbound_privacy_check(packet, client)

    def not_run(reason: str) -> list[dict[str, Any]]:
        provider = "local in-house model" if url else model.split("/", 1)[0]
        return [
            {"model": model, "provider": provider, "angle_id": angle[0], "angle": angle[1],
             "status": "Not run", "reason": reason}
            for angle in REVIEW_ANGLES
        ]

    if privacy_check["status"] != "Passed":
        judges = not_run("The outbound privacy check blocked this packet: " + ", ".join(privacy_check["issues"]) + ".")
    elif enabled and (token or url):
        judges: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(REVIEW_ANGLES)) as executor:
            futures = [
                executor.submit(_call_judge, model, packet, token, angle, url)
                for angle in REVIEW_ANGLES
            ]
            for future in as_completed(futures):
                judges.append(future.result())
        order = [angle[0] for angle in REVIEW_ANGLES]
        judges.sort(key=lambda item: order.index(item.get("angle_id", order[0])))
    else:
        judges = not_run(
            "The in-house review is off. Set TESSERA_INHOUSE_REVIEW_ENABLED=true and "
            "configure TESSERA_INHOUSE_URL or AI Gateway authentication to turn it on."
            if not enabled
            else "AI Gateway authentication is not configured."
        )

    completed = [judge for judge in judges if judge["status"] == "Completed"]
    panel_score = deterministic_score
    spread = None
    consensus_rule = "Deterministic score only; the in-house review did not run."
    if completed:
        scores = [int(judge["score"]) for judge in completed]
        judge_median = round(median(scores))
        panel_score = min(deterministic_score, judge_median)
        spread = max(scores) - min(scores)
        consensus_rule = "Lower of the deterministic score and the median of the review angles."
        if spread > 20:
            panel_score = min(panel_score, 69)
            consensus_rule += " Angles more than 20 points apart cap the result at 69."
        if any(judge.get("verdict") == "block" for judge in completed):
            panel_score = min(panel_score, 49)
            consensus_rule += " A block from any angle caps the result at 49."

    return {
        "recommendation_id": recommendation["id"],
        "recommendation_title": recommendation.get("title"),
        "retrieval": retrieval,
        "datasets": dataset_lenses,
        "deterministic": {
            "score": deterministic_score,
            "band": validation.get("band", _band(deterministic_score)),
            "blockers": validation.get("blockers", []),
            "status": "Passed" if deterministic_score >= 50 and not validation.get("blockers") else "Blocked",
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
        "reviewer": {
            "model": model,
            "deployment": "Local in-house model" if url else "Demo stand-in for the bank's in-house model",
        },
        "privacy": (
            "Client data in this review only goes to the bank's in-house model. The reviewer sees the proposed action, "
            "the client's risk profile and detected contradictions, and key numbers. Names, IDs, nationality, "
            "the client's own words, RM notes and RM-edited wording never leave TESSERA. "
            "External models only read public news headlines."
        ),
        "packet": packet,
        "packet_fingerprint": fingerprint(packet),
        "privacy_check": privacy_check,
    }
