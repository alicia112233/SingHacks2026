"""Reconstruct current action reviews from an append-only event ledger."""
from copy import deepcopy

from tessera.recommendation_validation import fingerprint, publish, revalidate_text

DECISIONS = {"approved", "dismissed", "edited", "pending"}


def action_version(action):
    return fingerprint([action["id"], action.get("evidence_version"), action["detail"], action.get("suitability"), action.get("risk_validation", {}).get("rubric_version")])


def record_matches(record, client_id, index, action):
    if record.get("recommendation_id") == action["id"]:
        return True
    # Legacy index IDs are never trusted without the original title.
    return (record.get("recommendation_id") == f"{client_id}:{index}"
            and record.get("recommendation_title") == action["title"])


def reviewed_intelligence(intelligence, snapshot):
    result = deepcopy(intelligence)
    records = snapshot.get("records", [])
    for client_id, client in result.get("client_profiles", {}).items():
        actions = client["recommendations"]
        candidates = {a["id"]: a for a in client.get("alternative_candidates", [])}
        for record in records:
            if record.get("client_id") != client_id or record.get("action") != "alternative":
                continue
            saved = record["recommendation"]
            if any(a["id"] == saved["id"] for a in actions):
                continue
            action = deepcopy(candidates.get(saved["id"], saved))
            if saved["id"] not in candidates:
                action["risk_validation"] = publish(action["risk_validation"], ["The source-backed alternative is no longer available; review current evidence."])
            action["replacement_for"] = record.get("replacement_for")
            actions.append(action)
        for index, action in enumerate(actions):
            history = [r for r in records if record_matches(r, client_id, index, action)]
            edits = [r for r in history if r.get("action") == "edited"]
            if edits:
                action["detail"] = edits[-1]["note"]
                action["risk_validation"] = revalidate_text(action["risk_validation"], action["detail"])
                action["decision_rationale"] = {"summary": "Edited wording is checked against the source-backed action. See the risk rubric for current controls.", "trigger": "Action wording was edited", "supporting_evidence": [], "rm_checks": action["risk_validation"]["blockers"], "method": "Only the original source-backed wording retains its assessment."}
            action["version"] = action_version(action)
            evaluations = [r for r in history if r.get("action") == "evaluated" and any(j.get("status") == "Completed" for j in r["evaluation"]["judges"])]
            current = [r for r in evaluations if r.get("version") == action["version"]]
            validation = action["risk_validation"]
            if current:
                # A retry or an unavailable provider cannot erase an earlier block.
                evaluation = min(current, key=lambda r: r["evaluation"]["consensus"]["score"])["evaluation"]
                validation["caps"] = [*validation["caps"], {"value": evaluation["consensus"]["score"], "reason": "Persisted independent panel result for this action and evidence version."}]
                action["risk_validation"] = publish(validation, validation["blockers"])
                action["evaluation"] = evaluation
            elif evaluations:
                action["risk_validation"] = publish(validation, [*validation["blockers"], "Action or evidence changed after model review; run the panel on this version before approval."])
    result["featured_clients"] = {key: result["client_profiles"][key] for key in intelligence.get("featured_clients", {})}
    apply_escalation_reviews(result, records)
    return result


ESCALATION_REVIEWS = {"escalation_confirmed": "confirmed", "escalation_dismissed": "dismissed"}


def apply_escalation_reviews(result, records):
    """Attach the latest RM confirm or dismiss to each queue card's breach alert."""
    for card in result.get("book", {}).get("priority_queue", []):
        escalation = card.get("escalation")
        if not escalation:
            continue
        history = [r for r in records if r.get("action") in ESCALATION_REVIEWS
                   and r.get("client_id") == card["client_id"] and r.get("escalation_id") == escalation.get("id")]
        if history:
            latest = history[-1]
            escalation["review"] = {"status": ESCALATION_REVIEWS[latest["action"]], "recorded_at": latest["recorded_at"],
                                    "actor": latest.get("actor"), "note": latest.get("note", "")}


def reviewed_snapshot(snapshot, intelligence):
    reviewed = reviewed_intelligence(intelligence, snapshot)
    effective, reviews = {}, {}
    for client_id, client in reviewed.get("client_profiles", {}).items():
        for index, action in enumerate(client["recommendations"]):
            key = f"{client_id}:{index}"
            reviews[key] = action
            history = [r for r in snapshot.get("records", []) if r.get("action") in DECISIONS and record_matches(r, client_id, index, action)]
            if history:
                latest = history[-1]
                # Old approvals remain in the audit trail, but do not approve new evidence.
                if latest["action"] != "approved" or (latest.get("version") == action["version"] and action["risk_validation"]["score"] >= 50 and not action["risk_validation"]["blockers"]):
                    effective[key] = latest
    return {**snapshot, "effective": effective, "reviews": reviews}


def requested_action(body, intelligence, index_key="recommendation_index"):
    if not isinstance(body, dict):
        raise ValueError("Request body must be an object")
    client = intelligence.get("client_profiles", {}).get(str(body.get("client_id", "")))
    index = int(body.get(index_key, -1))
    if not client:
        raise ValueError("Unknown client")
    if not 0 <= index < len(client["recommendations"]):
        raise ValueError("Unknown recommendation")
    action = client["recommendations"][index]
    if body.get("recommendation_id") != action["id"] or body.get("version") != action["version"]:
        raise ValueError("The action or evidence has changed. Refresh the review before continuing.")
    return client, index, action
