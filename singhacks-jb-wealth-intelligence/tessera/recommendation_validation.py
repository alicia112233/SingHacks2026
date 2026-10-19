"""Transparent action-specific support checks and typed numeric evidence."""
import hashlib
import json
import math
import re

RUBRIC_VERSION = "1.2"
# Evidence groups, outstanding controls, analytical method, outside-wealth relevance.
CONTRACTS = {
    "funding": (("cash_needs", "asset_mix"), ("Dated funding plan", "Client confirmation"), "funding", True),
    "reserve": (("cash_needs", "asset_mix", "funding_plan"), ("Product review", "Dated funding plan"), "funding", True),
    "mandate": (("mandate_findings",), ("Mandate resolution",), "mandate", False),
    "movement": (("position_changes", "transaction_reconciliation"), ("Transaction attribution",), "movement", False),
    "credit": (("ltv", "cash_needs"), ("Credit approval",), "credit", True),
    "lookthrough": (("asset_mix", "lookthrough"), ("Client instruction",), "lookthrough", False),
    "outside_wealth": (("lookthrough", "outside_wealth_valuation"), ("External valuation",), "lookthrough", True),
    "scenario": (("scenarios", "linked_events"), ("Scenario assumptions",), "scenario", True),
    "duration": (("scenarios", "maturity_schedule"), ("Maturity-to-horizon matching",), "duration", True),
    "liability": (("cash_needs", "rm_context"), ("Updated liability confirmation",), "funding", True),
    "profile": (("asset_mix", "client_profile"), ("Current client instructions", "Outside wealth confirmation"), "profile", True),
    "pressure": (("pressure_driver", "client_profile"), ("Specific risk-reduction step",), "pressure", True),
    "currency": (("currency_mix", "cash_needs"), ("Spending currency confirmation",), "profile", True),
    "followup": (("client_profile",), ("Agreed review date",), "profile", False),
}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def has_text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().casefold() not in {"nan", "none", "null"}


def assess(profile, action):
    kind = action.get("assessment_kind", "unknown")
    groups, checks, method, outside = CONTRACTS.get(kind, (("action_evidence",), ("Action classification",), "unknown", True))
    inputs = dict(profile)
    inputs["client_profile"] = has_text(profile.get("objectives")) and has_text(profile.get("risk_profile"))
    inputs["rm_context"] = [x for x in profile.get("evidence_passport", []) if "rm_notes" in x.get("source", "")]
    inputs["lookthrough"] = [x for x in profile.get("evidence_passport", []) if "instruments.csv" in x.get("source", "")]
    inputs["pressure_driver"] = [x for x in profile.get("evidence_passport", []) if "portfolio intelligence" in x.get("source", "")]
    present = [key for key in groups if inputs.get(key)]
    missing = [key for key in groups if not inputs.get(key)]
    evidence = round(25 * len(present) / len(groups))
    # Pending prerequisites withhold points; a condition is not completed approval.
    suitability = max(0, 25 - 3 * len(checks) - 3 * len(missing)) if has_text(action.get("suitability")) else 0
    analytical, explanation = 0, "No completed action-specific analytical test."
    if method == "credit":
        credit = profile.get("ltv") or {}
        analytical = 5 * all(finite(credit.get(k)) for k in ("ltv_pct", "trigger_pct", "points_to_trigger")) + 5 * finite(credit.get("lending_value_buffer_m"))
        explanation = "LTV/trigger diagnostic and haircut-adjusted buffer each earn 5 when recorded."
    elif method == "mandate":
        analytical = 8 if profile.get("mandate_findings") else 0
        explanation = "Computed mandate breach supports review (8); a corrective allocation has not been simulated."
    elif method == "movement":
        analytical = 4 * bool(profile.get("position_changes")) + 6 * bool(profile.get("transaction_reconciliation"))
        explanation = "Snapshot movement earns 4; completed transaction reconciliation earns 6."
    elif method in ("scenario", "duration"):
        cases = [x for x in profile.get("scenarios", []) if finite(x.get("portfolio_impact_pct")) and x.get("factors")]
        analytical = min(10 if method == "scenario" else 4, len(cases) * 5)
        explanation = f"{len(cases)} quantified cases; duration review still lacks maturity-to-horizon matching." if method == "duration" else f"{len(cases)} quantified cases at 5 points each, maximum 10."
    elif method == "funding":
        dated = any(x.get("due_from") and finite(x.get("amount")) for x in profile.get("cash_needs", []))
        analytical = 3 * dated + 7 * bool(profile.get("funding_plan"))
        explanation = "Dated liability earns 3; a validated funding plan earns 7. Portfolio scenarios do not validate the plan."
    elif method == "lookthrough":
        analytical = 5 * bool(inputs["lookthrough"])
        explanation = "Recorded look-through earns 5; complete household exposure is not independently validated."
    # Only signals required by this action contribute. Broad profile availability
    # is context, not an event or an analytical validation.
    signal_groups = [g for g in groups if g not in ("client_profile", "rm_context", "transaction_reconciliation", "funding_plan")]
    signal = round(15 * sum(bool(inputs.get(g)) for g in signal_groups) / len(signal_groups)) if signal_groups else 0
    actionability = 2 * (action.get("reversible") is True) + bool(action.get("suitability")) + bool(action.get("detail")) + bool(action.get("decision_date"))
    def dim(name, score, maximum, reason):
        return {"name": name, "score": int(score), "max": maximum, "reason": reason}
    dimensions = [
        dim("Evidence and lineage", evidence, 25, f"Required for this action: {', '.join(groups)}. Available: {', '.join(present) or 'none'}. Missing: {', '.join(missing) or 'none'}. Input coverage is not claim-level entailment."),
        dim("Suitability and policy", suitability, 25, f"Condition: {action.get('suitability', 'missing')}. Pending: {', '.join(checks)}. Withheld: 3 per pending check and 3 per missing evidence group; product eligibility remains unverified."),
        dim("Analytical corroboration", analytical, 20, explanation + " Calibration, stability and outcome coverage earn 0/10."),
        dim("Signal relevance", signal, 15, f"Only these action-linked groups contribute: {', '.join(signal_groups) or 'none'}. Unrelated signals earn no points; timing/materiality require RM review."),
        dim("Actionability and reversibility", actionability, 5, "Reversibility earns 2; condition, action text and explicit decision date earn 1 each. Decision date: " + str(action.get("decision_date", "not recorded"))),
    ]
    return dimensions, outside, kind in {"funding", "reserve", "liability", "profile", "pressure"}


NUMBER = r"[-+]?\d+(?:\.\d+)?"
TOKEN = re.compile(r"(?<![A-Za-z0-9])" + NUMBER)


def numeric_claims(text):
    """Parse display quantities, retaining currency/percent/year/point units."""
    text = re.sub(r"(?<=\d)-(?=\d)", "\u2013", text)
    text = text.replace("\u2212", "-")
    claims = []
    for match in TOKEN.finditer(text):
        before, after = text[:match.start()], text[match.end():]
        currency = re.search(r"\b([A-Z]{3})\s*$", before)
        range_end = re.match(r"[\u2013-]\d+(?:\.\d+)?%", after)
        unit = "number"
        if currency and re.match(r"m\b", after):
            unit = currency.group(1) + " million"
        elif re.match(r"%", after) or range_end:
            unit = "percent"
        elif re.match(r"(?:-year| year)", after):
            unit = "years"
        elif re.match(r" point", after):
            unit = "points"
        elif re.match(r"(?:-month| month)", after):
            unit = "months"
        claims.append({"value": float(match.group()), "unit": unit})
    return claims


def validate_numbers(text, evidence):
    for fact in evidence:
        if fact.get("literal"):
            text = re.sub(re.escape(fact["literal"]), "instrument", text, flags=re.I)
    unresolved, resolved = [], []
    for claim in numeric_claims(text):
        matches = [fact for fact in evidence if fact["unit"] == claim["unit"] and abs(fact["value"] - claim["value"]) < 0.005]
        if matches:
            resolved.append({**claim, "sources": matches})
        else:
            unresolved.append(claim)
    # A range is one claim: both bounds must belong to the same mandate,
    # in their recorded roles. Two unrelated matching numbers are insufficient.
    for match in re.finditer(r"(\d+(?:\.\d+)?)[\u2013-](\d+(?:\.\d+)?)%", text):
        lower, upper = map(float, match.groups())
        sources = {f["source"] for f in evidence if f.get("field") == "min_pct" and f["value"] == lower}
        if lower > upper or not any(f.get("field") == "max_pct" and f["value"] == upper and f["source"] in sources for f in evidence):
            unresolved.append({"value": lower, "unit": "percent range with unsupported bound roles"})
    return resolved, unresolved


def publish(validation, blockers):
    result = dict(validation)
    result["blockers"] = blockers
    result["score"] = 0 if blockers else min([result["raw_score"]] + [c["value"] for c in result["caps"]])
    score = result["score"]
    result["band"] = "Blocked" if score < 50 else "Verify first" if score < 70 else "Review ready" if score < 85 else "Strong support"
    result["disposition"] = "Do not publish; resolve validation failures" if score < 50 else "RM must verify flagged inputs before use" if score < 70 else "Supported for RM review; approval remains mandatory"
    result["residual_hallucination_risk"] = "Very high" if score < 50 else "High" if score < 70 else "Moderate"
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def canonical_wording(text):
    # Only case, whitespace and typographic dash changes preserve the assessment.
    return " ".join(text.replace("\u2013", "-").replace("\u2212", "-").casefold().split())


def revalidate_text(validation, text):
    blockers = list(validation.get("source_blockers", validation.get("blockers", [])))
    if canonical_wording(text) != canonical_wording(validation.get("assessed_detail", "")):
        blockers.append("Changed action wording has not been assessed. Restore the source-backed wording or request a source-backed alternative.")
    resolved, unresolved = validate_numbers(text, validation.get("numeric_evidence", []))
    blockers += [f"Unsupported numeric claim: {c['value']:g} {c['unit']}" for c in unresolved]
    result = publish(validation, list(dict.fromkeys(blockers)))
    result["resolved_claims"] = resolved
    return result
