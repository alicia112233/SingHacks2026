"""Detect where a client's own words and their portfolio disagree.

Everything here is deterministic: themes come from fixed vocabulary matched
against the client record and RM notes, and every percentage is computed from
current holdings. No client is named in the rules, so a new client is assessed
with the same logic as the existing book.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    client_terms: str  # regex matched against source of wealth and objective phrases
    sectors: frozenset[str] = frozenset()
    keywords: tuple[str, ...] = ()
    asset_classes: frozenset[str] = frozenset()


# "Gulf" maps to energy holdings because the region's economy is energy-led; it
# is domain vocabulary, not a client-specific rule.
THEMES: tuple[Theme, ...] = (
    Theme("energy", "energy", r"\bcoal\b|\benergy\b|\bpetroleum\b|(?<!palm )\boil\b|\bgas\b", frozenset({"Energy"}), ("energy", "coal")),
    Theme("gulf", "energy", r"\bgulf\b", frozenset({"Energy"}), ("gulf",)),
    Theme("shipping", "shipping", r"shipping|marine|charter|port services|logistics|freight", keywords=("shipping", "logistics", "marine", "freight")),
    Theme("property", "property", r"property|real estate", frozenset({"Real Estate"}), ("property",)),
    Theme("plantation", "plantation", r"palm|plantation|agribusiness", keywords=("palm", "plantation")),
    Theme("healthcare", "healthcare", r"health|pharma|clinic", frozenset({"Health Care"}), ("pharma", "health")),
    Theme("technology", "technology", r"software|technology|e-commerce|semiconductor|cloud", frozenset({"Information Technology"})),
    Theme("luxury", "luxury", r"luxury", frozenset({"Consumer Discretionary"}), ("luxury",)),
    Theme("commodities", "commodities", r"commodit", frozenset({"Gold"}), ("commodity",), frozenset({"Commodities"})),
    Theme("industrial", "industrial", r"industrial", frozenset({"Industrials"}), ("industrial",)),
)

RISK_ASSET_CLASSES = ("Equity", "Alternatives", "Structured Products", "Commodities")
GATED_TIERS = ("Quarterly Gate", "Illiquid")
LIQUIDITY_WEIGHT = {"High": 1.0, "Medium": 0.7, "Low": 0.4}

DIVEST = re.compile(r"(?:diversify away from|outside(?: of)?|reduce dependence on|away from)\s+([^;]+)", re.I)
RETAIN = re.compile(r"(?:retain|keep|minimi[sz]e disruption to)\s+([^;]+)", re.I)
OWN_BUSINESS = re.compile(r"operating business|family business|former business|employer|family group", re.I)
CURRENCY_WORDS = {"USD": r"\bUSD\b|US\b", "JPY": r"\bJPY\b|\byen\b", "SGD": r"\bSGD\b", "HKD": r"\bHKD\b", "EUR": r"\bEUR\b"}
INCOME_INTENT = re.compile(r"\bdraw\b|\bincome\b|living costs", re.I)
SUCCESSION = re.compile(r"succession|transfer of assets|estate", re.I)

NOTE_CUES = {
    "concentration": re.compile(r"same (?:theme|sector|conditions|bet|market)|not aware|uncorrelated|currently is not|attachment", re.I),
    "liquidity": re.compile(r"\bgated?\b|sellable|illiquid|liquidity is thin|how little", re.I),
    "risk_profile": re.compile(r"safe and boring|does not understand|de-risk", re.I),
    "currency": re.compile(r"not in yen|USD liquidity|currency", re.I),
    "duration": re.compile(r"drawdown|lost money|duration", re.I),
}

# Minimum points for a detector to count as a contradiction.
DETECTION_THRESHOLD = 15.0
GOAL_CAP = 40.0
NO_DETECTION_POINTS = 8.0


def _members(underlying: Any) -> list[str]:
    text = "" if underlying is None or (isinstance(underlying, float) and underlying != underlying) else str(underlying)
    if ":" not in text or "/" not in text:
        return []
    return [part.strip() for part in text.split(":", 1)[1].split("/") if part.strip()]


def _lookthrough(current: pd.DataFrame, instruments: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Return each held instrument's own sector/text plus its basket members'."""

    catalogue = instruments.set_index("instrument_id")
    names = {row.instrument_id: str(row.instrument_name).lower() for row in instruments.itertuples()}
    profile: dict[str, dict[str, Any]] = {}
    for instrument_id in current.instrument_id.unique():
        row = catalogue.loc[instrument_id]
        sectors = {str(row.sector)}
        text = [str(row.instrument_name), str(row.sector), str(row.underlying_reference)]
        resolved = []
        for member in _members(row.underlying_reference):
            tokens = [t for t in member.lower().split() if t not in {"adr", "ltd", "inc"}]
            for other_id, other_name in names.items():
                if other_id != instrument_id and tokens and all(t in other_name.split() for t in tokens):
                    sectors.add(str(catalogue.loc[other_id].sector))
                    text.append(str(catalogue.loc[other_id].instrument_name))
                    resolved.append(other_id)
        profile[instrument_id] = {
            "sectors": sectors,
            "text": " ".join(text).lower(),
            "asset_class": str(row.asset_class),
            "resolved": resolved,
        }
    return profile


def _matches(theme: Theme, holding: dict[str, Any]) -> bool:
    return bool(
        theme.sectors & holding["sectors"]
        or holding["asset_class"] in theme.asset_classes
        or any(word in holding["text"] for word in theme.keywords)
    )


def _themes_in(text: str) -> list[Theme]:
    return [theme for theme in THEMES if re.search(theme.client_terms, text, re.I)]


def _note_support(notes: list[dict[str, Any]], cue: str, terms: str | None = None) -> str | None:
    for note in sorted(notes, key=lambda item: item["note_date"], reverse=True):
        text = str(note["note"])
        if NOTE_CUES[cue].search(text) and (terms is None or re.search(terms, text, re.I)):
            return str(note["note_id"])
    return None


def _join(labels: list[str]) -> str:
    unique = list(dict.fromkeys(labels))
    return " and ".join(unique) if len(unique) <= 2 else ", ".join(unique[:-1]) + " and " + unique[-1]


def _link(themes: list[Theme], current: pd.DataFrame, aum: float, lookthrough: dict) -> dict | None:
    """Measure look-through exposure to a set of themes."""

    linked: dict[str, list[str]] = {}
    for instrument_id, holding in lookthrough.items():
        hit = [t.label for t in themes if _matches(t, holding)]
        if hit:
            linked[instrument_id] = hit
    if not linked:
        return None
    # Order theme labels by how much exposure each one explains.
    weight: dict[str, float] = {}
    for instrument_id, labels in linked.items():
        value = float(current.loc[current.instrument_id == instrument_id, "market_value_usd"].sum())
        for label in labels:
            weight[label] = weight.get(label, 0.0) + value
    return {
        "theme": _join(sorted(weight, key=weight.get, reverse=True)),
        "theme_ids": sorted(linked),
        "exposure_pct": round(float(current.loc[current.instrument_id.isin(linked), "market_value_usd"].sum()) / aum * 100, 1),
    }


def _intent(client: Any) -> tuple[list[Theme], list[Theme], list[Theme], str]:
    """Return source-of-wealth themes, themes to move away from, retained themes and intent strength."""

    wealth_themes = _themes_in(str(client.source_of_wealth))
    objectives = str(client.objectives)
    intended: list[Theme] = []
    for phrase in DIVEST.findall(objectives):
        intended += wealth_themes if OWN_BUSINESS.search(phrase) else _themes_in(phrase)
    retained: list[Theme] = []
    for phrase in RETAIN.findall(objectives):
        retained += wealth_themes if OWN_BUSINESS.search(phrase) else _themes_in(phrase)
    intended = list(dict.fromkeys(intended))
    strength = "stated" if intended else "general" if "diversif" in objectives.lower() else "none"
    return wealth_themes, intended, retained, strength


def _wealth_concentration(client: Any, current: pd.DataFrame, aum: float, lookthrough: dict, notes: list) -> dict | None:
    wealth_themes, intended, retained, intent = _intent(client)
    themes = [t for t in (intended or wealth_themes) if t not in retained]
    link = _link(themes, current, aum, lookthrough) if themes else None
    if not link or link["exposure_pct"] < 10:
        return None
    exposure, theme_label = link["exposure_pct"], link["theme"]

    if intent == "stated":
        points = 15 + 0.55 * exposure
    elif intent == "general":
        points = 8 + 0.3 * exposure  # intent is general or future-dated, e.g. "build a diversified portfolio post-event"
    else:
        points = min(30.0, 0.6 * exposure)
        if float(client.risk_tolerance_score) >= 8:
            points *= 0.5  # a high-tolerance client has knowingly accepted concentrated risk
    terms = "|".join(t.client_terms for t in themes)
    note_id = _note_support(notes, "concentration", terms) or _note_support(notes, "concentration")
    if note_id:
        points += 3
    sources = ["clients.csv: source_of_wealth"]
    if intent != "none":
        sources.append("clients.csv: objectives")
    if note_id:
        sources.append(f"rm_notes.json: {note_id}")
    label = (
        f"Diversification goal vs {theme_label} exposure"
        if intent != "none"
        else f"{theme_label.capitalize()} wealth doubled inside the portfolio"
    )
    return {
        "kind": "wealth_concentration",
        "label": label,
        "points": points,
        "evidence": f"{exposure:.1f}% linked to {theme_label} before outside wealth",
        "next_step": f"Show the {theme_label} look-through and agree a diversification path",
        "sources": sources,
    }


def _liquidity(client: Any, current: pd.DataFrame, aum: float, needs: list, uncalled_usd: float, notes: list) -> dict | None:
    daily = float(current.loc[current.liquidity_tier == "Daily", "market_value_usd"].sum())
    gated_pct = float(current.loc[current.liquidity_tier.isin(GATED_TIERS), "market_value_usd"].sum()) / aum * 100
    dated = [n for n in needs if n["due_from"] <= "2027-12-31" and n["certainty"] != "Aspirational"]
    near = sum(n["amount_usd_m"] * 1_000_000 for n in dated)
    # Planned cash needs already record capital calls as irregular items, so
    # only commitments beyond those are added.
    irregular = sum(n["amount_usd_m"] * 1_000_000 for n in dated if n["recurrence"] == "Irregular")
    extra_calls = max(0.0, uncalled_usd - irregular)
    coverage = (near + extra_calls) / max(daily, 1.0)
    weight = LIQUIDITY_WEIGHT.get(str(client.liquidity_needs), 0.7)
    points = weight * (0.4 * gated_pct + 25 * min(coverage, 1.5))
    succession = bool(SUCCESSION.search(f"{client.life_stage} {client.objectives}")) and gated_pct >= 30
    if succession:
        points += 10
    note_id = _note_support(notes, "liquidity")
    if note_id:
        points += 3
    sources = ["clients.csv: liquidity_needs", "holdings.csv: liquidity_tier"]
    if near:
        sources.append("planned_cash_needs.csv")
    if uncalled_usd:
        sources.append("commitments.csv")
    if note_id:
        sources.append(f"rm_notes.json: {note_id}")
    if succession:
        label, step = "Succession plan vs illiquid estate", "Separate estate liquidity from the property portfolio"
        evidence = f"{gated_pct:.1f}% gated or illiquid ahead of an estate transfer"
    elif uncalled_usd and uncalled_usd >= 0.5 * (near + extra_calls):
        label, step = "Private-market commitments vs gated liquidity", "Take a full liquidity map to the next investment committee"
        evidence = f"USD {uncalled_usd / 1_000_000:.1f}m uncalled commitments; {gated_pct:.1f}% gated or illiquid"
    else:
        label, step = "Liquidity need vs sellable assets", "Map sellable assets to dated needs before the next commitment"
        evidence = f"USD {(near + extra_calls) / 1_000_000:.1f}m due by 2027 vs USD {daily / 1_000_000:.1f}m daily-liquid"
    return {"kind": "liquidity", "label": label, "points": points, "evidence": evidence, "next_step": step, "sources": sources}


def _risk_profile(client: Any, current: pd.DataFrame, aum: float, notes: list) -> dict | None:
    tolerance = float(client.risk_tolerance_score)
    if tolerance > 3:
        return None
    risk_share = float(current.loc[current.asset_class.isin(RISK_ASSET_CLASSES), "market_value_usd"].sum()) / aum
    target = 0.10 + tolerance * 0.07
    excess = risk_share - target
    if excess < 0.10:
        return None
    points = 10 + 40 * excess
    note_id = _note_support(notes, "risk_profile")
    sources = ["clients.csv: risk_profile", "holdings.csv: asset_class"]
    if note_id:
        points += 3
        sources.append(f"rm_notes.json: {note_id}")
    return {
        "kind": "risk_profile",
        "label": f"{client.risk_profile} profile vs risk-heavy portfolio",
        "points": points,
        "evidence": f"{risk_share * 100:.1f}% in risk assets vs about {target * 100:.0f}% for tolerance {tolerance:g}/10",
        "next_step": "Reconfirm the risk profile before discussing de-risking",
        "sources": sources,
    }


def _currency(client: Any, current: pd.DataFrame, aum: float, needs: list, notes: list) -> dict | None:
    mix = current.groupby("instrument_ccy").market_value_usd.sum() / aum * 100
    objectives = str(client.objectives)
    best = None
    totals: dict[str, float] = {}
    for need in needs:
        if need["certainty"] != "Aspirational":
            totals[need["currency"]] = totals.get(need["currency"], 0.0) + need["amount_usd_m"] * 1_000_000
    stated = {ccy for ccy, pattern in CURRENCY_WORDS.items() if re.search(pattern, objectives)}
    for ccy in set(totals) | stated:
        share = float(mix.get(ccy, 0.0))
        need_usd = totals.get(ccy, 0.0)
        if share >= 50 or not (ccy in stated or need_usd >= 0.10 * aum):
            continue
        intensity = min(1.0, need_usd / max(aum * share / 100, 1.0))
        points = 8 + 0.4 * (50 - share) + 12 * intensity
        if best is None or points > best["points"]:
            best = {
                "kind": "currency",
                "label": f"{ccy} obligations vs {mix.idxmax()}-heavy assets",
                "points": points,
                "evidence": f"{ccy} needs of USD {need_usd / 1_000_000:.1f}m against {share:.1f}% of assets in {ccy}",
                "next_step": f"Build a {ccy}-matched liquidity ladder",
                "sources": ["planned_cash_needs.csv" if need_usd else "clients.csv: objectives", "holdings.csv: instrument_ccy"],
            }
    if best:
        note_id = _note_support(notes, "currency")
        if note_id:
            best["points"] += 3
            best["sources"].append(f"rm_notes.json: {note_id}")
    return best


def _duration(client: Any, current: pd.DataFrame, aum: float, as_of: str, notes: list) -> dict | None:
    if not INCOME_INTENT.search(str(client.objectives)):
        return None
    horizon_year = int(as_of[:4]) + 15
    bonds = current[current.asset_class == "Fixed Income"]
    long_mask = bonds.instrument_name.str.contains("Perpetual", case=False) | bonds.instrument_name.map(
        lambda name: max((int(y) for y in re.findall(r"\b20\d{2}\b", str(name))), default=0) >= horizon_year
    )
    long_pct = float(bonds.loc[long_mask, "market_value_usd"].sum()) / aum * 100
    if long_pct < 8:
        return None
    points = 10 + 0.7 * long_pct
    note_id = _note_support(notes, "duration")
    sources = ["clients.csv: objectives", "holdings.csv: maturities"]
    if note_id:
        points += 3
        sources.append(f"rm_notes.json: {note_id}")
    return {
        "kind": "duration",
        "label": "Lifetime income vs long-duration holdings",
        "points": points,
        "evidence": f"{long_pct:.1f}% in perpetual or {horizon_year}+ bonds against an income objective",
        "next_step": "Verify the annual draw; prepare a duration ladder conversation",
        "sources": sources,
    }


def detect(
    client: Any,
    current: pd.DataFrame,
    instruments: pd.DataFrame,
    needs: list[dict[str, Any]],
    uncalled_usd: float,
    notes: list[dict[str, Any]],
    as_of: str,
) -> dict[str, Any]:
    """Return every detected contradiction for one client, strongest first."""

    aum = float(current.market_value_usd.sum())
    if not aum:
        return {"detections": [], "goal_points": NO_DETECTION_POINTS, "primary": None, "theme_ids": []}
    lookthrough = _lookthrough(current, instruments)
    candidates = [
        _wealth_concentration(client, current, aum, lookthrough, notes),
        _liquidity(client, current, aum, needs, uncalled_usd, notes),
        _risk_profile(client, current, aum, notes),
        _currency(client, current, aum, needs, notes),
        _duration(client, current, aum, as_of, notes),
    ]
    detections = sorted(
        (d for d in candidates if d and d["points"] >= DETECTION_THRESHOLD),
        key=lambda d: d["points"],
        reverse=True,
    )
    for d in detections:
        d["points"] = round(min(GOAL_CAP, d["points"]), 1)
    # The wealth link is measured even when the client chose to keep it, so a
    # review can still show the look-through behind a retained exposure.
    wealth_themes, intended, _, _ = _intent(client)
    link = _link(list(dict.fromkeys(wealth_themes + intended)), current, aum, lookthrough) or {}
    if detections:
        # Each further contradiction adds a little: stacked gaps are harder to resolve.
        goal = min(GOAL_CAP, detections[0]["points"] + 2 * min(2, len(detections) - 1))
    else:
        goal = NO_DETECTION_POINTS
    return {
        "detections": detections,
        "goal_points": round(goal, 1),
        "primary": detections[0] if detections else None,
        "theme": link.get("theme"),
        "theme_ids": link.get("theme_ids", []),
        "theme_exposure_pct": link.get("exposure_pct"),
    }
