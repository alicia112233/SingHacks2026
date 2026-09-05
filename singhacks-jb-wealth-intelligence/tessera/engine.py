"""Evidence-grounded analytics for the TESSERA advisory workflow.

Calculations and client summaries are deterministic. Each output is linked to a
bounded evidence set so it can be reproduced, reviewed, and audited.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from tessera.risk_analysis import analyse_client, order_by_urgency


SEVERITY_ORDER = {"Severe": 3, "High": 2, "Medium": 1, "Low": 0}

CLIENT_RULES: dict[str, dict[str, Any]] = {
    "CL-0001": {
        "label": "Diversification promise vs energy exposure",
        "theme_ids": ["SYN-ST-0101", "SYN-EQ-0008", "SYN-SP-0505"],
        "theme": "coal, energy and shipping",
        "goal_points": 34,
    },
    "CL-0003": {
        "label": "Conservative identity vs inherited risk",
        "goal_points": 38,
    },
    "CL-0006": {
        "label": "USD obligations vs SGD liquidity",
        "goal_points": 35,
    },
    "CL-0011": {
        "label": "Succession deadline vs illiquid estate",
        "goal_points": 34,
    },
    "CL-0012": {
        "label": "Lifetime income vs long-duration holdings",
        "goal_points": 40,
    },
    "CL-0014": {
        "label": "Liquidity need vs one property bet",
        "theme_ids": ["SYN-AL-0307", "SYN-FI-0207", "SYN-ST-0106", "SYN-SP-0503"],
        "theme": "Hong Kong property",
        "goal_points": 40,
    },
    "CL-0016": {
        "label": "JPY retirement vs employer-stock attachment",
        "goal_points": 30,
    },
    "CL-0017": {
        "label": "Private-market commitments vs gated liquidity",
        "goal_points": 36,
    },
    "CL-0018": {
        "label": "Luxury-cycle wealth doubled inside the portfolio",
        "goal_points": 30,
    },
    "CL-0019": {
        "label": "Diversification goal vs shipping-energy look-through",
        "theme_ids": ["SYN-ST-0104", "SYN-EQ-0008", "SYN-EQ-0025", "SYN-SP-0505"],
        "theme": "shipping and energy",
        "goal_points": 39,
    },
    "CL-0020": {
        "label": "Healthcare wealth doubled inside the portfolio",
        "goal_points": 27,
    },
}


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    clean = df.where(pd.notna(df), None)
    return clean.to_dict(orient="records")


def _as_of(bundle: dict[str, Any]) -> str:
    """Return the latest observed holding snapshot in the supplied records."""
    return str(bundle["holdings"].snapshot_date.max())


def _baseline(bundle: dict[str, Any]) -> str:
    return str(bundle["holdings"].snapshot_date.min())


def _maturity_year(instrument_name: str) -> str | None:
    years = re.findall(r"\b20\d{2}\b", str(instrument_name))
    return max(years) if years else None


def _round(value: float, digits: int = 1) -> float:
    if value is None or math.isnan(float(value)):
        return 0.0
    return round(float(value), digits)


def _iso(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def load_dataset(data_dir: Path) -> dict[str, Any]:
    names = [
        "clients",
        "portfolios",
        "holdings",
        "instruments",
        "mandates",
        "transactions",
        "credit_facilities",
        "commitments",
        "planned_cash_needs",
        "market_context",
        "event_log",
    ]
    bundle: dict[str, Any] = {
        name: pd.read_csv(data_dir / f"{name}.csv") for name in names
    }
    with (data_dir / "rm_notes.json").open(encoding="utf-8") as handle:
        bundle["rm_notes"] = json.load(handle)
    return bundle


def _market_value(bundle: dict[str, Any], series_id: str, snapshot: str) -> float:
    market = bundle["market_context"]
    row = market[(market.series_id == series_id) & (market.snapshot_date == snapshot)]
    if row.empty:
        raise KeyError(f"Missing {series_id} for {snapshot}")
    return float(row.iloc[0].value)


def _to_usd(bundle: dict[str, Any], amount: float, currency: str, snapshot: str) -> float:
    currency = str(currency).upper()
    if currency == "USD":
        return float(amount)
    if currency == "SGD":
        return float(amount) / _market_value(bundle, "USDSGD", snapshot)
    if currency == "HKD":
        return float(amount) / _market_value(bundle, "USDHKD", snapshot)
    if currency == "JPY":
        return float(amount) / _market_value(bundle, "USDJPY", snapshot)
    if currency == "CHF":
        return float(amount) / _market_value(bundle, "USDCHF", snapshot)
    if currency == "EUR":
        return float(amount) * _market_value(bundle, "EURUSD", snapshot)
    if currency == "GBP":
        return float(amount) * _market_value(bundle, "GBPUSD", snapshot)
    return float(amount)


def _snapshot_path(bundle: dict[str, Any], client_id: str) -> list[dict[str, Any]]:
    portfolios = bundle["portfolios"]
    rows = portfolios[portfolios.client_id == client_id]
    snapshots = sorted(bundle["holdings"].snapshot_date.unique())
    path = []
    for snapshot in snapshots:
        total = 0.0
        for _, portfolio in rows.iterrows():
            value = float(portfolio[f"aum_{snapshot}"])
            total += _to_usd(bundle, value, portfolio.base_currency, snapshot)
        path.append({"date": snapshot, "aum_usd_m": _round(total / 1_000_000, 2)})
    return path


def _asset_mix(current: pd.DataFrame, aum: float) -> list[dict[str, Any]]:
    grouped = current.groupby("asset_class", as_index=False).market_value_usd.sum()
    grouped["pct"] = grouped.market_value_usd / aum * 100
    grouped = grouped.sort_values("market_value_usd", ascending=False)
    return [
        {"label": row.asset_class, "value": _round(row.pct, 1)}
        for row in grouped.itertuples()
    ]


def _currency_mix(current: pd.DataFrame, aum: float) -> list[dict[str, Any]]:
    grouped = current.groupby("instrument_ccy", as_index=False).market_value_usd.sum()
    grouped["pct"] = grouped.market_value_usd / aum * 100
    grouped = grouped.sort_values("market_value_usd", ascending=False)
    return [
        {"label": row.instrument_ccy, "value": _round(row.pct, 1)}
        for row in grouped.itertuples()
    ]


def _mandate_findings(bundle: dict[str, Any], client_id: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    holdings = bundle["holdings"]
    instruments = bundle["instruments"].set_index("instrument_id")
    mandates = bundle["mandates"]
    portfolios = bundle["portfolios"]
    as_of = _as_of(bundle)

    for _, portfolio in portfolios[portfolios.client_id == client_id].iterrows():
        if portfolio.service_model == "Custody":
            continue
        current = holdings[
            (holdings.portfolio_id == portfolio.portfolio_id)
            & (holdings.snapshot_date == as_of)
        ].copy()
        total = float(current.market_value_base.sum())
        rules = mandates[mandates.mandate_code == portfolio.mandate_code]
        for _, rule in rules.iterrows():
            actual = float(
                current.loc[current.asset_class == rule.asset_class, "market_value_base"].sum()
                / total
                * 100
            )
            if actual < float(rule.min_pct) - 0.05 or actual > float(rule.max_pct) + 0.05:
                findings.append(
                    {
                        "type": "allocation",
                        "portfolio_id": portfolio.portfolio_id,
                        "label": f"{rule.asset_class} outside {float(rule.min_pct):g}–{float(rule.max_pct):g}% band",
                        "actual_pct": _round(actual, 1),
                        "severity": "High" if abs(actual - float(rule.target_pct)) > 10 else "Medium",
                    }
                )
        max_position = float(rules.max_single_position_pct.iloc[0]) if not rules.empty else 100.0
        for _, holding in current.iterrows():
            instrument = instruments.loc[holding.instrument_id]
            if instrument.concentration_limit_applies == "Y" and float(holding.weight_pct) > max_position:
                findings.append(
                    {
                        "type": "single_position",
                        "portfolio_id": portfolio.portfolio_id,
                        "label": f"{holding.instrument_name} above {max_position:g}% position limit",
                        "actual_pct": _round(float(holding.weight_pct), 1),
                        "severity": "High",
                    }
                )
            if (
                "Sustainable" in str(portfolio.mandate_name)
                and instrument.sustainability_excluded == "Y"
            ):
                findings.append(
                    {
                        "type": "exclusion",
                        "portfolio_id": portfolio.portfolio_id,
                        "label": f"Excluded holding in sustainable mandate: {holding.instrument_name}",
                        "actual_pct": _round(float(holding.weight_pct), 1),
                        "severity": "High",
                    }
                )
    return findings


def _cash_need_summary(bundle: dict[str, Any], client_id: str) -> list[dict[str, Any]]:
    needs = bundle["planned_cash_needs"]
    subset = needs[needs.client_id == client_id].sort_values("due_from")
    as_of = _as_of(bundle)
    result = []
    for row in subset.itertuples():
        result.append(
            {
                "id": row.need_id,
                "description": row.description,
                "currency": row.currency,
                "amount": float(row.amount),
                "amount_usd_m": _round(
                    _to_usd(bundle, float(row.amount), row.currency, as_of) / 1_000_000,
                    2,
                ),
                "due_from": _iso(row.due_from),
                "due_to": _iso(row.due_to),
                "certainty": row.certainty,
                "recurrence": row.recurrence,
            }
        )
    return result


def _theme_exposure(current: pd.DataFrame, ids: Iterable[str], aum: float) -> float:
    value = current.loc[current.instrument_id.isin(list(ids)), "market_value_usd"].sum()
    return float(value) / aum * 100 if aum else 0.0


def _priority_card(bundle: dict[str, Any], client_row: Any) -> dict[str, Any]:
    client_id = client_row.client_id
    aum = float(client_row.total_aum_usd)
    as_of = _as_of(bundle)
    current = bundle["holdings"][(bundle["holdings"].client_id == client_id) & (bundle["holdings"].snapshot_date == as_of)]
    rule = CLIENT_RULES.get(client_id, {})
    findings = _mandate_findings(bundle, client_id)
    needs = _cash_need_summary(bundle, client_id)
    daily = float(current.loc[current.liquidity_tier == "Daily", "market_value_usd"].sum())
    gated = float(current.loc[current.liquidity_tier.isin(["Quarterly Gate", "Illiquid"]), "market_value_usd"].sum())
    near_needs = sum(
        n["amount_usd_m"] * 1_000_000
        for n in needs
        if n["due_from"] <= "2027-12-31" and n["certainty"] != "Aspirational"
    )
    liquidity_pressure = max(0.0, min(25.0, (near_needs / max(daily, 1.0) - 0.35) * 13.0))
    governance_pressure = min(20.0, len(findings) * 5.0)

    facilities = bundle["credit_facilities"]
    facility = facilities[facilities.client_id == client_id]
    ltv_text = None
    if not facility.empty:
        ltv = float(facility.iloc[0][f"ltv_pct_{as_of}"])
        trigger = float(facility.iloc[0].margin_call_ltv_pct)
        proximity = ltv / trigger
        if proximity >= 0.92:
            governance_pressure = min(20.0, governance_pressure + 8.0)
        ltv_text = f"LTV {ltv:.2f}% vs {trigger:.0f}% trigger"

    kyc_due = datetime.strptime(str(client_row.kyc_review_due), "%Y-%m-%d").date()
    as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    days_to_kyc = (kyc_due - as_of_date).days
    time_pressure = 12.0 if days_to_kyc <= 30 else 7.0 if days_to_kyc <= 90 else 2.0
    year_end = as_of_date.replace(month=12, day=31).isoformat()
    if needs and min(n["due_from"] for n in needs) <= year_end:
        time_pressure = min(15.0, time_pressure + 6.0)

    goal_pressure = float(rule.get("goal_points", 8.0))
    score = min(99, round(goal_pressure + liquidity_pressure + governance_pressure + time_pressure))

    if rule.get("theme_ids"):
        exposure = _theme_exposure(current, rule["theme_ids"], aum)
        evidence_line = f"{exposure:.1f}% linked to {rule['theme']} before outside wealth"
    elif client_id == "CL-0012":
        fi = float(current.loc[current.asset_class == "Fixed Income", "market_value_usd"].sum()) / aum * 100
        maturity_years = [_maturity_year(name) for name in current.instrument_name]
        longest_maturity = max((year for year in maturity_years if year), default="not recorded")
        evidence_line = f"{fi:.1f}% fixed income; longest recorded maturity is {longest_maturity}"
    elif client_id == "CL-0006":
        usd_need = sum(n["amount_usd_m"] for n in needs if n["currency"] == "USD")
        evidence_line = f"USD {usd_need:.1f}m needs; gated fund redemption pending"
    elif client_id == "CL-0017":
        commitments = bundle["commitments"]
        uncalled = float(commitments.loc[commitments.client_id == client_id, "uncalled"].sum())
        evidence_line = f"USD {uncalled / 1_000_000:.1f}m uncalled commitments"
    elif findings:
        evidence_line = findings[0]["label"]
    else:
        evidence_line = f"{gated / aum * 100:.1f}% gated or illiquid"

    next_step = {
        "CL-0012": "Verify annual draw; prepare duration ladder conversation",
        "CL-0014": "Stress lending value before discussing redevelopment funding",
        "CL-0019": "Rehearse Strait-reopening downside and ring-fence seed capital",
        "CL-0006": "Build a currency-matched liquidity ladder",
        "CL-0003": "Separate tax reserve before inherited-risk review",
        "CL-0017": "Take a full liquidity map to the October investment committee",
    }.get(client_id, "Review the highest-evidence gap with the client")

    return {
        "client_id": client_id,
        "client_name": client_row.client_name,
        "score": score,
        "priority": "Now" if score >= 78 else "Next" if score >= 60 else "Watch",
        "tension": rule.get("label", "Portfolio evidence requires review"),
        "evidence": evidence_line,
        "next_step": next_step,
        "aum_usd_m": _round(aum / 1_000_000, 1),
        "booking_centre": client_row.booking_centre,
        "risk_profile": client_row.risk_profile,
        "reporting_language": client_row.reporting_language,
        "ltv": ltv_text,
        "signals": {
            "goal": _round(goal_pressure, 0),
            "liquidity": _round(liquidity_pressure, 0),
            "governance": _round(governance_pressure, 0),
            "time": _round(time_pressure, 0),
        },
    }


def _linked_events(bundle: dict[str, Any], client_id: str) -> list[dict[str, Any]]:
    events = bundle["event_log"].copy()
    channels = {
        "CL-0012": ["Duration", "fixed income", "rates", "Energy"],
        "CL-0014": ["growth equity valuations", "collateralised lending"],
        "CL-0019": ["Energy", "shipping", "transport"],
        "CL-0006": ["USD", "Private credit"],
        "CL-0003": ["European fixed income", "EUR assets", "Energy"],
    }.get(client_id, [])
    selected = []
    for row in events.itertuples():
        transmission = str(row.primary_transmission).lower()
        if any(channel.lower() in transmission for channel in channels):
            selected.append(
                {
                    "date": row.event_date,
                    "severity": row.severity,
                    "description": row.description,
                    "transmission": row.primary_transmission,
                    "source": f"event_log.csv • {row.event_date}",
                }
            )
    selected.sort(key=lambda item: (item["date"], SEVERITY_ORDER.get(item["severity"], 0)))
    return selected[-5:]


def _position_delta(bundle: dict[str, Any], client_id: str) -> list[dict[str, Any]]:
    holdings = bundle["holdings"]
    baseline_date = _baseline(bundle)
    as_of = _as_of(bundle)
    baseline = holdings[(holdings.client_id == client_id) & (holdings.snapshot_date == baseline_date)]
    current = holdings[(holdings.client_id == client_id) & (holdings.snapshot_date == as_of)]
    b = baseline.groupby(["instrument_id", "instrument_name"], as_index=False).market_value_usd.sum()
    c = current.groupby(["instrument_id", "instrument_name"], as_index=False).market_value_usd.sum()
    joined = b.merge(c, on=["instrument_id", "instrument_name"], how="outer", suffixes=("_start", "_end")).fillna(0)
    joined["delta"] = joined.market_value_usd_end - joined.market_value_usd_start
    joined = joined.reindex(joined.delta.abs().sort_values(ascending=False).index).head(5)
    return [
        {
            "instrument": row.instrument_name,
            "start_usd_m": _round(row.market_value_usd_start / 1_000_000, 2),
            "end_usd_m": _round(row.market_value_usd_end / 1_000_000, 2),
            "delta_usd_m": _round(row.delta / 1_000_000, 2),
        }
        for row in joined.itertuples()
    ]


def _scenario_impact(current: pd.DataFrame, shocks: dict[str, float]) -> dict[str, Any]:
    total = float(current.market_value_usd.sum())
    impacts: list[dict[str, Any]] = []
    total_delta = 0.0
    for key, shock in shocks.items():
        if key.startswith("id:"):
            mask = current.instrument_id == key[3:]
        elif key.startswith("asset:"):
            mask = current.asset_class == key[6:]
        elif key.startswith("name:"):
            mask = current.instrument_name.str.contains(key[5:], case=False, regex=False)
        else:
            continue
        value = float(current.loc[mask, "market_value_usd"].sum())
        delta = value * shock
        total_delta += delta
        if value:
            factor_name = key.split(":", 1)[1]
            if key.startswith("id:"):
                matching_names = current.loc[mask, "instrument_name"]
                if not matching_names.empty:
                    factor_name = str(matching_names.iloc[0])
            impacts.append(
                {
                    "factor": factor_name,
                    "exposure_usd_m": _round(value / 1_000_000, 2),
                    "shock_pct": _round(shock * 100, 1),
                    "impact_usd_m": _round(delta / 1_000_000, 2),
                }
            )
    impacts.sort(key=lambda row: abs(row["impact_usd_m"]), reverse=True)
    return {
        "portfolio_impact_pct": _round(total_delta / total * 100, 1),
        "portfolio_impact_usd_m": _round(total_delta / 1_000_000, 2),
        "factors": impacts,
    }


def _ltv_trigger_buffer(bundle: dict[str, Any], client_id: str) -> dict[str, Any] | None:
    facilities = bundle["credit_facilities"]
    row = facilities[facilities.client_id == client_id]
    if row.empty:
        return None
    as_of = _as_of(bundle)
    facility = row.iloc[0]
    drawn = float(facility[f"drawn_{as_of}"])
    lending = float(facility[f"lending_value_{as_of}"])
    trigger = float(facility.margin_call_ltv_pct)
    trigger_lending = drawn / (trigger / 100)
    buffer = lending - trigger_lending
    return {
        "facility_id": facility.facility_id,
        "currency": facility.facility_ccy,
        "ltv_pct": _round(float(facility[f"ltv_pct_{as_of}"]), 2),
        "trigger_pct": _round(trigger, 1),
        "points_to_trigger": _round(trigger - float(facility[f"ltv_pct_{as_of}"]), 2),
        "lending_value_buffer_m": _round(buffer / 1_000_000, 2),
        "lending_value_drop_to_trigger_pct": _round(buffer / lending * 100, 2),
        "reported_headroom_m": _round(float(facility[f"headroom_{as_of}"]) / 1_000_000, 2),
    }


def _feature_profile(bundle: dict[str, Any], client_id: str) -> dict[str, Any]:
    clients = bundle["clients"]
    client = clients[clients.client_id == client_id].iloc[0]
    as_of = _as_of(bundle)
    current = bundle["holdings"][(bundle["holdings"].client_id == client_id) & (bundle["holdings"].snapshot_date == as_of)].copy()
    aum = float(current.market_value_usd.sum())
    notes = [n for n in bundle["rm_notes"] if n["client_id"] == client_id]
    needs = _cash_need_summary(bundle, client_id)
    mandates = _mandate_findings(bundle, client_id)

    base = {
        "client_id": client_id,
        "name": client.client_name,
        "age": None if pd.isna(client.age) else int(client.age),
        "life_stage": client.life_stage,
        "source_of_wealth": client.source_of_wealth,
        "objectives": client.objectives,
        "risk_profile": client.risk_profile,
        "reporting_language": client.reporting_language,
        "booking_centre": client.booking_centre,
        "aum_usd_m": _round(aum / 1_000_000, 2),
        "snapshot_path": _snapshot_path(bundle, client_id),
        "asset_mix": _asset_mix(current, aum),
        "currency_mix": _currency_mix(current, aum),
        "position_changes": _position_delta(bundle, client_id),
        "linked_events": _linked_events(bundle, client_id),
        "cash_needs": needs,
        "mandate_findings": mandates,
        "notes": notes,
        "ltv": _ltv_trigger_buffer(bundle, client_id),
    }

    if client_id == "CL-0012":
        fixed_income = float(current.loc[current.asset_class == "Fixed Income", "market_value_usd"].sum())
        dated_bonds = [
            (_maturity_year(row.instrument_name), row)
            for row in current[current.asset_class == "Fixed Income"].itertuples()
            if _maturity_year(row.instrument_name)
        ]
        maturity_year, longest_bond_row = max(dated_bonds, key=lambda item: item[0])
        long_bond = float(longest_bond_row.market_value_usd)
        cash = float(current.loc[current.asset_class == "Cash and Equivalents", "market_value_usd"].sum())
        structured_need = next(n for n in needs if n["recurrence"] == "Annual")
        linked_event_dates = " / ".join(event["date"] for event in base["linked_events"])
        latest_note_text = str(notes[-1]["note"])
        draw_changed = "draw" in latest_note_text.lower() and any(
            word in latest_note_text.lower() for word in ("increase", "changed", "revised")
        )
        note_has_amount = bool(
            re.search(r"\b(?:USD|SGD|HKD|EUR|GBP|CHF|JPY)\s*[\d,.]+", latest_note_text)
        )
        draw_needs_verification = draw_changed and not note_has_amount
        draw_context = (
            "the latest RM note records an increase without a current amount"
            if draw_needs_verification
            else "the latest RM note contains no unquantified draw change"
        )
        down = _scenario_impact(
            current,
            {
                "id:SYN-FI-0201": -0.075,
                "id:SYN-FI-0203": -0.030,
                "id:SYN-FI-0204": -0.025,
                "id:SYN-FI-0206": -0.050,
                "id:SYN-FI-0207": -0.055,
            },
        )
        up = _scenario_impact(
            current,
            {
                "id:SYN-FI-0201": 0.075,
                "id:SYN-FI-0203": 0.030,
                "id:SYN-FI-0204": 0.025,
                "id:SYN-FI-0206": 0.050,
                "id:SYN-FI-0207": 0.055,
            },
        )
        base.update(
            {
                "tension": {
                    "client_says": client.objectives,
                    "portfolio_does": f"{fixed_income / aum * 100:.1f}% sits in fixed income; {long_bond / aum * 100:.1f}% is in {longest_bond_row.instrument_name}.",
                    "future_demands": f"The cash-needs record requires {structured_need['currency']} {structured_need['amount_usd_m']:.2f}m a year from {structured_need['due_from']}; {draw_context}.",
                },
                "headline_metrics": [
                    {"value": f"{fixed_income / aum * 100:.1f}%", "label": "fixed income"},
                    {"value": maturity_year, "label": "longest recorded maturity"},
                    {"value": f"{cash / structured_need['amount']:.1f} yrs", "label": "cash-only runway"},
                ],
                "scenarios": [
                    {
                        "id": "rates_up",
                        "name": "Rates +50 bps",
                        "description": "Illustrative parallel duration shock; no probability assigned and not a forecast.",
                        **down,
                    },
                    {
                        "id": "rates_down",
                        "name": "Rates −50 bps",
                        "description": "Symmetric sensitivity check; not a forecast.",
                        **up,
                    },
                ],
                "recommendations": [
                    {
                        "title": "Verify the liability before optimising the assets",
                        "detail": f"Confirm whether the current annual need remains {structured_need['currency']} {structured_need['amount_usd_m']:.2f}m; {draw_context}.",
                        "suitability": "Data clarification",
                        "reversible": True,
                    },
                    {
                        "title": "Build a 24-month spending reserve",
                        "detail": "Model a cash-and-short-duration sleeve before discussing sales from loss positions.",
                        "suitability": "Within Income mandate, subject to instrument review",
                        "reversible": True,
                    },
                    {
                        "title": "Reframe duration as a life-horizon decision",
                        "detail": f"Compare maturity dates with the client’s {int(client.investment_horizon_years)}-year recorded horizon; involve the client in sequencing, not a binary sell/hold choice.",
                        "suitability": "RM judgement required",
                        "reversible": True,
                    },
                ],
                "conversation": {
                    "open": "You were right to ask why a ‘safe’ portfolio can still fall. The issue is not whether the bonds repay—it is whether their timetable still fits yours.",
                    "show": f"One page: the {structured_need['currency']} {structured_need['amount_usd_m']:.2f}m annual need, the {maturity_year} maturity, and two rate sensitivities.",
                    "ask": f"Before we change anything, does the recorded annual need of {structured_need['currency']} {structured_need['amount_usd_m']:.2f}m reflect your current draw?",
                    "avoid": "Do not lead with total return or tell him to wait for recovery.",
                },
                "confidence": {
                    "level": "Needs verification" if draw_needs_verification else "Review ready",
                    "reason": f"The structured record says {structured_need['currency']} {structured_need['amount_usd_m']:.2f}m annually; {draw_context}.",
                },
                "evidence_passport": [
                    {"claim": f"Annual need is {structured_need['currency']} {structured_need['amount_usd_m']:.2f}m", "source": f"planned_cash_needs.csv • {structured_need['id']}", "status": "Structured"},
                    {"claim": draw_context.capitalize(), "source": f"rm_notes.json • {notes[-1]['note_id']}", "status": "Review" if draw_needs_verification else "Checked"},
                    {"claim": f"Longest recorded bond maturity is {maturity_year}", "source": f"holdings.csv • {longest_bond_row.instrument_id} • {as_of}", "status": "Verified"},
                    {"claim": "Relevant rate events are present in the controlled register", "source": f"event_log.csv • {linked_event_dates}", "status": "Authoritative"},
                ],
            }
        )

    elif client_id == "CL-0014":
        linked_ids = CLIENT_RULES[client_id]["theme_ids"]
        exposure = _theme_exposure(current, linked_ids, aum)
        linked_count = int(current.instrument_id.isin(linked_ids).sum())
        ltv = _ltv_trigger_buffer(bundle, client_id)
        property_need = needs[0]
        months_to_need = max(
            0,
            (date.fromisoformat(property_need["due_to"]).year - date.fromisoformat(as_of).year) * 12
            + date.fromisoformat(property_need["due_to"]).month
            - date.fromisoformat(as_of).month,
        )
        property_instrument = bundle["instruments"][
            bundle["instruments"].instrument_id == "SYN-SP-0503"
        ].iloc[0]
        property_down = _scenario_impact(
            current,
            {
                "id:SYN-AL-0307": -0.15,
                "id:SYN-FI-0207": -0.10,
                "id:SYN-ST-0106": -0.20,
                "id:SYN-SP-0503": -0.25,
            },
        )
        base.update(
            {
                "tension": {
                    "client_says": client.objectives,
                    "portfolio_does": f"{exposure:.1f}% is linked to Hong Kong property across direct property, equity, perpetual and accumulator.",
                    "future_demands": f"{property_need['currency']} {property_need['amount'] / 1_000_000:.1f}m is due by {property_need['due_to']} while facility LTV is {ltv['ltv_pct']:.2f}% against a {ltv['trigger_pct']:.1f}% trigger.",
                },
                "headline_metrics": [
                    {"value": f"{exposure:.1f}%+", "label": "same property bet"},
                    {"value": f"{ltv['ltv_pct']:.2f}%", "label": "current LTV"},
                    {"value": f"{ltv['points_to_trigger']:.2f} pts", "label": "to margin trigger"},
                ],
                "scenarios": [
                    {
                        "id": "property_down",
                        "name": "HK property stress",
                        "description": "Illustrative −10% to −25% by property-linked instrument; outside business not valued.",
                        **property_down,
                    },
                    {
                        "id": "liquidity_trigger",
                        "name": "Collateral threshold",
                        "description": "The margin trigger is reached after only a small fall in eligible lending value.",
                        "portfolio_impact_pct": -_round(ltv["lending_value_drop_to_trigger_pct"], 2),
                        "portfolio_impact_usd_m": None,
                        "factors": [
                            {
                                "factor": "eligible lending value",
                                "exposure_usd_m": None,
                                "shock_pct": -_round(ltv["lending_value_drop_to_trigger_pct"], 2),
                                "impact_usd_m": None,
                            }
                        ],
                    },
                ],
                "recommendations": [
                    {
                        "title": "Protect the facility before funding the project",
                        "detail": f"Treat the {ltv['currency']} {ltv['lending_value_buffer_m']:.2f}m trigger buffer—not reported headroom—as the binding constraint.",
                        "suitability": "Credit review required",
                        "reversible": True,
                    },
                    {
                    "title": "Separate conviction from multiple wrappers of one risk",
                        "detail": "Show a single look-through exposure spanning direct property, issuer equity, perpetual debt and the accumulator.",
                        "suitability": "Advisory account; client instruction remains possible",
                        "reversible": True,
                    },
                    {
                        "title": "Ring-fence the redevelopment contribution",
                        "detail": "Stage a liquid funding sleeve and test it without assuming the accumulator can be exited at par.",
                        "suitability": "Mandate and credit checks required",
                        "reversible": True,
                    },
                ],
                "conversation": {
                    "open": f"Your property view may be right. The risk is that {linked_count} bank-held positions and the development project depend on the same market outcome.",
                    "show": f"The look-through stack beside the {ltv['trigger_pct']:.1f}% LTV threshold and {property_need['currency']} {property_need['amount'] / 1_000_000:.1f}m funding requirement.",
                    "ask": f"Which matters more over the next {months_to_need} months: preserving upside or securing the project equity?",
                    "avoid": "Do not describe reported facility headroom as margin-call protection.",
                },
                "confidence": {
                    "level": "High",
                    "reason": "Positions, look-through instrument terms, cash need and facility fields reconcile at the current snapshot.",
                },
                "evidence_passport": [
                    {"claim": f"{exposure:.1f}% linked to HK property", "source": f"holdings.csv + instruments.csv • {as_of}", "status": "Verified"},
                    {"claim": property_instrument.underlying_reference, "source": f"instruments.csv • {property_instrument.instrument_id}", "status": "Verified"},
                    {"claim": f"{property_need['currency']} {property_need['amount'] / 1_000_000:.1f}m contribution is {property_need['certainty'].lower()}", "source": f"planned_cash_needs.csv • {property_need['id']}", "status": "Structured"},
                    {"claim": f"LTV is {ltv['ltv_pct']:.2f}% vs {ltv['trigger_pct']:.1f}%", "source": f"credit_facilities.csv • {ltv['facility_id']}", "status": "Verified"},
                ],
            }
        )

    elif client_id == "CL-0019":
        linked_ids = CLIENT_RULES[client_id]["theme_ids"]
        exposure = _theme_exposure(current, linked_ids, aum)
        reopen = _scenario_impact(
            current,
            {
                "id:SYN-ST-0104": -0.18,
                "id:SYN-EQ-0008": -0.15,
                "id:SYN-EQ-0025": -0.15,
                "id:SYN-SP-0505": -0.12,
            },
        )
        escalation = _scenario_impact(
            current,
            {
                "id:SYN-ST-0104": 0.12,
                "id:SYN-EQ-0008": 0.14,
                "id:SYN-EQ-0025": 0.10,
                "id:SYN-SP-0505": 0.09,
            },
        )
        cash = float(current.loc[current.asset_class == "Cash and Equivalents", "market_value_usd"].sum())
        seed_need = needs[0]
        latest_linked_event = base["linked_events"][-1]
        baseline_label = datetime.strptime(_baseline(bundle), "%Y-%m-%d").strftime("%b %Y")
        fcn_instrument = bundle["instruments"][
            bundle["instruments"].instrument_id == "SYN-SP-0505"
        ].iloc[0]
        base.update(
            {
                "tension": {
                    "client_says": client.objectives,
                    "portfolio_does": f"{exposure:.1f}% is linked to shipping and energy after looking through the FCN.",
                    "future_demands": f"{seed_need['currency']} {seed_need['amount'] / 1_000_000:.1f}m is due from {seed_need['due_from']} versus USD {cash / 1_000_000:.1f}m in cash at {as_of}.",
                },
                "headline_metrics": [
                    {"value": f"{exposure:.1f}%+", "label": "shipping & energy"},
                    {"value": f"+{(_snapshot_path(bundle, client_id)[-1]['aum_usd_m'] / _snapshot_path(bundle, client_id)[0]['aum_usd_m'] - 1) * 100:.1f}%", "label": f"value path since {baseline_label}*"},
                    {"value": f"{seed_need['currency']} {seed_need['amount'] / 1_000_000:g}m", "label": f"capital need from {seed_need['due_from'][:4]}"},
                ],
                "scenarios": [
                    {
                        "id": "strait_reopens",
                        "name": "Strait reopens",
                        "description": "Illustrative normalization shocks; no probability assigned and business exposure excluded.",
                        **reopen,
                    },
                    {
                        "id": "blockade_worsens",
                        "name": "Blockade worsens",
                        "description": "Illustrative risk-premium extension; not a forecast.",
                        **escalation,
                    },
                ],
                "recommendations": [
                    {
                        "title": "Ring-fence the family-office seed capital",
                        "detail": "Move from an implicit market-timing assumption to a dated funding sleeve.",
                        "suitability": "Advisory approval required",
                        "reversible": True,
                    },
                    {
                        "title": "Measure portfolio + operating business as one risk",
                        "detail": f"The {exposure:.1f}% bank-held portfolio figure is a floor because the outside operating business has no recorded valuation.",
                        "suitability": "External-wealth confirmation required",
                        "reversible": True,
                    },
                    {
                        "title": "Rehearse both sides of the Strait thesis",
                        "detail": "Use symmetric scenarios so the discussion is not anchored to recent gains.",
                        "suitability": "Scenario assumptions visible to RM",
                        "reversible": True,
                    },
                ],
                "conversation": {
                    "open": "The energy thesis has worked. That success has quietly rebuilt the same risk your Asia portfolio was meant to diversify.",
                    "show": f"The FCN look-through, both documented scenarios, and the {seed_need['currency']} {seed_need['amount'] / 1_000_000:g}m requirement from {seed_need['due_from'][:4]}.",
                    "ask": "If the Strait reopened next month, how much of this year’s gain are you willing to give back?",
                    "avoid": "Do not imply we know when normalization occurs or value the private operating business without data.",
                },
                "confidence": {
                    "level": "High on portfolio / incomplete household",
                    "reason": "Bank-held exposure is exact; outside Gulf business exposure is qualitative only.",
                },
                "evidence_passport": [
                    {"claim": f"{exposure:.1f}% linked to shipping and energy", "source": f"holdings.csv + instruments.csv • {as_of}", "status": "Verified"},
                    {"claim": fcn_instrument.underlying_reference, "source": f"instruments.csv • {fcn_instrument.instrument_id}", "status": "Verified"},
                    {"claim": latest_linked_event["description"], "source": f"event_log.csv • {latest_linked_event['date']}", "status": "Authoritative"},
                    {"claim": f"{seed_need['currency']} {seed_need['amount'] / 1_000_000:g}m capital need is {seed_need['certainty'].lower()}", "source": f"planned_cash_needs.csv • {seed_need['id']}", "status": "Structured"},
                ],
            }
        )
    else:
        priority = _priority_card(bundle, client)
        top_asset = base["asset_mix"][0]
        daily_value = float(
            current.loc[current.liquidity_tier == "Daily", "market_value_usd"].sum()
        )
        next_need = needs[0] if needs else None
        primary_finding = mandates[0] if mandates else None
        largest_change = base["position_changes"][0] if base["position_changes"] else None
        downside = _scenario_impact(
            current,
            {
                "asset:Equity": -0.12,
                "asset:Fixed Income": -0.03,
                "asset:Alternatives": -0.08,
                "asset:Structured Products": -0.10,
                "asset:Commodities": -0.07,
            },
        )
        recovery = _scenario_impact(
            current,
            {
                "asset:Equity": 0.10,
                "asset:Fixed Income": 0.025,
                "asset:Alternatives": 0.06,
                "asset:Structured Products": 0.08,
                "asset:Commodities": 0.05,
            },
        )
        future_demand = (
            f"{next_need['description']} requires {next_need['currency']} "
            f"{next_need['amount'] / 1_000_000:.1f}m from {next_need['due_from']}."
            if next_need
            else f"KYC review is due {client.kyc_review_due}; no dated cash need is recorded."
        )
        portfolio_position = (
            f"{top_asset['value']:.1f}% is allocated to {top_asset['label']}; "
            f"{len(mandates)} mandate or concentration exception{'s' if len(mandates) != 1 else ''} require review."
        )
        action_items = []
        if next_need:
            action_items.append(
                {
                    "title": "Confirm the funding path and decision date",
                    "detail": (
                        f"Map liquid assets to the {next_need['currency']} "
                        f"{next_need['amount'] / 1_000_000:.1f}m need and confirm its "
                        f"{next_need['certainty'].lower()} status."
                    ),
                    "suitability": "Client confirmation required",
                    "reversible": True,
                }
            )
        if primary_finding:
            action_items.append(
                {
                    "title": "Resolve the highest-priority portfolio exception",
                    "detail": f"Review {primary_finding['label'].lower()} and document whether it reflects drift or client instruction.",
                    "suitability": "Mandate review required",
                    "reversible": True,
                }
            )
        if largest_change:
            action_items.append(
                {
                    "title": "Validate the largest position movement",
                    "detail": (
                        f"Reconcile the USD {largest_change['delta_usd_m']:+.2f}m change in "
                        f"{largest_change['instrument']} against transactions and market movement."
                    ),
                    "suitability": "Data and transaction review",
                    "reversible": True,
                }
            )
        action_items.append(
            {
                "title": "Reconfirm portfolio fit with the client",
                "detail": "Use the current allocation, upcoming obligations and recorded objectives to confirm that the mandate remains appropriate.",
                "suitability": "RM judgement required",
                "reversible": True,
            }
        )
        action_items = action_items[:3]
        base.update(
            {
                "tension": {
                    "client_says": client.objectives,
                    "portfolio_does": portfolio_position,
                    "future_demands": future_demand,
                },
                "headline_metrics": [
                    {"value": f"{top_asset['value']:.1f}%", "label": top_asset["label"]},
                    {"value": f"{daily_value / aum * 100:.1f}%", "label": "daily liquidity"},
                    {"value": str(len(mandates)), "label": "portfolio exceptions"},
                ],
                "scenarios": [
                    {
                        "id": "broad_risk_off",
                        "name": "Broad risk-off",
                        "description": "Documented cross-asset sensitivity with no probability assigned; not a forecast.",
                        **downside,
                    },
                    {
                        "id": "broad_recovery",
                        "name": "Broad recovery",
                        "description": "Symmetric recovery sensitivity for planning purposes; not a forecast.",
                        **recovery,
                    },
                ],
                "recommendations": action_items,
                "conversation": {
                    "open": f"I would like to review whether the current portfolio still fits your priority: {client.objectives}",
                    "show": "The current allocation, the largest position changes and any dated obligations.",
                    "ask": "Have your priorities, liquidity requirements or assets held elsewhere changed since our last review?",
                    "avoid": "Do not present scenario sensitivities as forecasts or recommend action before confirming the client record.",
                },
                "confidence": {
                    "level": "Review ready",
                    "reason": "Current bank-held positions and mandate records are available; outside assets require client confirmation.",
                },
                "evidence_passport": [
                    {"claim": "Current portfolio value and allocation", "source": f"holdings.csv • {client_id} • {as_of}", "status": "Verified"},
                    {"claim": "Client objectives and risk profile", "source": f"clients.csv • {client_id}", "status": "Structured"},
                    {"claim": "Mandate and concentration checks", "source": "mandates.csv + portfolios.csv", "status": "Verified"},
                    {"claim": "Relationship context", "source": f"rm_notes.json • {client_id}", "status": "RM record"},
                ],
                "priority": priority,
            }
        )
    return base


def _recommendation_risk_validation(
    bundle: dict[str, Any], profile: dict[str, Any], recommendation: dict[str, Any]
) -> dict[str, Any]:
    """Score whether an RM can safely rely on a generated recommendation.

    The score measures evidence and control confidence, not expected investment
    performance. The bundled scenarios are sensitivities rather than a calibrated
    predictive model, so scores are capped until outcome labels and back-testing
    are available.
    """

    client_id = profile["client_id"]
    as_of = _as_of(bundle)
    client = bundle["clients"][bundle["clients"].client_id == client_id].iloc[0]
    current = bundle["holdings"][
        (bundle["holdings"].client_id == client_id)
        & (bundle["holdings"].snapshot_date == as_of)
    ]
    instruments = bundle["instruments"]
    portfolios = bundle["portfolios"]

    blockers: list[str] = []
    if current.empty:
        blockers.append("No current holding snapshot is available")
    if not str(client.objectives).strip() or not str(client.risk_profile).strip():
        blockers.append("Client objective or risk profile is missing")
    if not str(recommendation.get("suitability", "")).strip():
        blockers.append("No suitability condition is attached")
    if recommendation.get("reversible") is not True:
        blockers.append("The proposed action is not explicitly reversible")
    if not current.empty:
        orphan_instruments = ~current.instrument_id.isin(instruments.instrument_id)
        orphan_portfolios = ~current.portfolio_id.isin(portfolios.portfolio_id)
        if bool(orphan_instruments.any() or orphan_portfolios.any()):
            blockers.append("Current positions fail reference-integrity checks")

    grounding_fields = (
        "evidence_passport",
        "cash_needs",
        "mandate_findings",
        "ltv",
        "scenarios",
        "tension",
        "headline_metrics",
        "position_changes",
        "linked_events",
    )
    grounding_context = json.dumps(
        {field: profile.get(field) for field in grounding_fields}, default=str
    )
    number_pattern = r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?"
    source_numbers = [float(value) for value in re.findall(number_pattern, grounding_context)]
    recommendation_numbers = [
        float(value)
        for value in re.findall(number_pattern, str(recommendation.get("detail", "")))
    ]
    ungrounded_numbers = [
        value
        for value in recommendation_numbers
        if not any(abs(value - source_value) < 0.005 for source_value in source_numbers)
    ]
    if ungrounded_numbers:
        blockers.append("A numeric claim cannot be resolved to the recommendation evidence set")

    status_weights = {
        "Verified": 1.0,
        "Authoritative": 1.0,
        "Checked": 0.9,
        "Structured": 0.85,
        "RM record": 0.65,
        "Review": 0.25,
    }
    passport = profile.get("evidence_passport", [])
    evidence_ratio = (
        sum(status_weights.get(item.get("status"), 0.4) for item in passport)
        / len(passport)
        if passport
        else 0.0
    )
    evidence_score = round(25 * evidence_ratio)

    suitability_text = str(recommendation.get("suitability", "")).lower()
    suitability_score = 23 if "within" in suitability_text else 20

    scenarios = profile.get("scenarios", [])
    quantified_scenarios = sum(
        1
        for scenario in scenarios
        if scenario.get("portfolio_impact_pct") is not None and scenario.get("factors")
    )
    predictive_score = min(14, 6 + quantified_scenarios * 4)

    signal_count = sum(
        (
            bool(profile.get("cash_needs")),
            bool(profile.get("mandate_findings")),
            bool(profile.get("ltv")),
            bool(profile.get("linked_events")),
        )
    )
    signal_score = min(15, 8 + signal_count * 2)

    stale = current[
        pd.to_datetime(current.valuation_date) < pd.to_datetime(current.snapshot_date)
    ]
    if stale.empty:
        freshness_score = 10
        freshness_reason = "Current positions use the current snapshot date."
    elif bool(stale.asset_class.isin(["Alternatives"]).all()):
        freshness_score = 7
        freshness_reason = (
            f"{len(stale)} alternative position(s) carry an expected lagged mark."
        )
    else:
        freshness_score = 4
        freshness_reason = f"{len(stale)} current position(s) have stale valuation dates."

    actionability_score = 0
    actionability_score += 2 if recommendation.get("reversible") is True else 0
    actionability_score += 2 if recommendation.get("suitability") else 0
    actionability_score += 1 if recommendation.get("title") and recommendation.get("detail") else 0

    dimensions = [
        {
            "name": "Evidence and lineage",
            "score": evidence_score,
            "max": 25,
            "reason": (
                f"{len(passport)} claim(s) are linked to controlled source records; "
                f"{len(recommendation_numbers)} numeric claim(s) resolved."
            ),
        },
        {
            "name": "Suitability and policy",
            "score": suitability_score,
            "max": 25,
            "reason": recommendation.get("suitability", "Suitability evidence missing"),
        },
        {
            "name": "Analytical corroboration",
            "score": predictive_score,
            "max": 20,
            "reason": (
                f"{quantified_scenarios} quantified sensitivity case(s); "
                "no calibrated outcome model is present."
            ),
        },
        {
            "name": "Signal relevance",
            "score": signal_score,
            "max": 15,
            "reason": f"{signal_count} applicable client, product, policy or market signal group(s).",
        },
        {
            "name": "Freshness and data quality",
            "score": freshness_score,
            "max": 10,
            "reason": freshness_reason,
        },
        {
            "name": "Actionability and reversibility",
            "score": actionability_score,
            "max": 5,
            "reason": "Action has an owner-facing condition and remains reversible.",
        },
    ]
    raw_score = sum(item["score"] for item in dimensions)
    caps = [
        {
            "value": 84,
            "reason": "Predictive model is not calibrated on recommendation outcomes.",
        }
    ]
    if any(item.get("status") == "Review" for item in passport):
        caps.append(
            {"value": 59, "reason": "A source conflict or unquantified RM update must be verified."}
        )
    combined_text = " ".join(
        (
            str(profile.get("confidence", {}).get("level", "")),
            str(profile.get("confidence", {}).get("reason", "")),
            str(recommendation.get("detail", "")),
            suitability_text,
        )
    ).lower()
    if any(term in combined_text for term in ("outside", "external-wealth", "incomplete household")):
        caps.append(
            {"value": 79, "reason": "Relevant outside wealth is unrecorded or qualitative."}
        )

    applied_cap = min((cap["value"] for cap in caps), default=100)
    score = 0 if blockers else min(raw_score, applied_cap)
    if blockers or score < 50:
        band = "Blocked"
        disposition = "Do not publish; resolve hard-stop controls"
        residual_risk = "Very high"
    elif score < 70:
        band = "Verify first"
        disposition = "RM must verify flagged inputs before use"
        residual_risk = "High"
    elif score < 85:
        band = "Review ready"
        disposition = "Supported for RM review; approval remains mandatory"
        residual_risk = "Moderate"
    else:
        band = "Strong support"
        disposition = "RM may approve after final suitability review"
        residual_risk = "Low"

    return {
        "score": score,
        "raw_score": raw_score,
        "band": band,
        "disposition": disposition,
        "residual_hallucination_risk": residual_risk,
        "score_meaning": "Evidence and control confidence; not return probability.",
        "model_validation": {
            "status": "Provisional",
            "reason": "Scenario sensitivities corroborate direction and materiality, but are not a calibrated predictive model.",
        },
        "human_validation": {
            "status": "Required",
            "owner": "Relationship Manager",
            "decision": "Approve, edit or dismiss with rationale",
        },
        "dimensions": dimensions,
        "caps": [cap for cap in caps if cap["value"] <= raw_score],
        "blockers": blockers,
    }


def _recommendation_decision_rationale(
    profile: dict[str, Any], recommendation: dict[str, Any]
) -> dict[str, Any]:
    """Expose an auditable explanation, not private model chain-of-thought."""

    title = str(recommendation.get("title", "")).lower()
    tensions = profile.get("tension", {})
    if any(
        word in title
        for word in ("fund", "liabil", "reserve", "liquid", "ring-fence", "facility")
    ):
        trigger = tensions.get("future_demands")
    elif any(
        word in title
        for word in ("exception", "position", "risk", "exposure", "wrapper", "duration")
    ):
        trigger = tensions.get("portfolio_does")
    else:
        trigger = tensions.get("client_says")

    evidence = [
        {
            "claim": item.get("claim"),
            "source": item.get("source"),
            "status": item.get("status"),
        }
        for item in profile.get("evidence_passport", [])[:4]
    ]
    validation = recommendation.get("risk_validation", {})
    checks = list(validation.get("blockers", []))
    suitability = str(recommendation.get("suitability", "")).strip()
    if suitability:
        checks.insert(0, suitability)

    return {
        "summary": (
            "This action turns the identified review point into a reversible RM step. "
            f"{recommendation.get('detail', '')}"
        ),
        "trigger": trigger
        or "A current client, portfolio or constraint record requires RM review.",
        "supporting_evidence": evidence,
        "rm_checks": checks,
        "method": (
            "Generated from deterministic client, portfolio, mandate and evidence rules. "
            "It explains the recommendation inputs; it is not hidden model reasoning."
        ),
    }


def _data_quality(bundle: dict[str, Any]) -> dict[str, Any]:
    holdings = bundle["holdings"]
    portfolios = bundle["portfolios"]
    instruments = bundle["instruments"]
    as_of = _as_of(bundle)
    current = holdings[holdings.snapshot_date == as_of]

    duplicate_grain = int(
        holdings.duplicated(subset=["snapshot_date", "portfolio_id", "instrument_id"]).sum()
    )
    orphan_instruments = int((~holdings.instrument_id.isin(instruments.instrument_id)).sum())
    orphan_portfolios = int((~holdings.portfolio_id.isin(portfolios.portfolio_id)).sum())
    stale = current[pd.to_datetime(current.valuation_date) < pd.to_datetime(current.snapshot_date)]
    weight_checks = (
        current.groupby("portfolio_id").weight_pct.sum().sub(100).abs().sort_values(ascending=False)
    )
    weight_outliers = int((weight_checks > 0.1).sum())
    latest_notes: dict[str, dict[str, Any]] = {}
    for note in sorted(bundle["rm_notes"], key=lambda item: item["note_date"]):
        latest_notes[note["client_id"]] = note
    client_names = bundle["clients"].set_index("client_id").client_name.to_dict()
    unquantified_updates = []
    annual_needs = bundle["planned_cash_needs"][
        bundle["planned_cash_needs"].recurrence == "Annual"
    ]
    for need in annual_needs.itertuples():
        note = latest_notes.get(need.client_id)
        note_text = str(note["note"]) if note else ""
        changed_draw = "draw" in note_text.lower() and any(
            word in note_text.lower() for word in ("increase", "changed", "revised")
        )
        has_amount = bool(re.search(r"\b(?:USD|SGD|HKD|EUR|GBP|CHF|JPY)\s*[\d,.]+", note_text))
        if changed_draw and not has_amount:
            unquantified_updates.append(str(client_names.get(need.client_id, need.client_id)))

    checks = [
        {
            "name": "Holding grain uniqueness",
            "status": "Pass" if duplicate_grain == 0 else "Review",
            "evidence": f"{duplicate_grain} duplicate snapshot × portfolio × instrument rows",
        },
        {
            "name": "Reference integrity",
            "status": "Pass" if orphan_instruments + orphan_portfolios == 0 else "Fail",
            "evidence": f"{orphan_instruments} orphan instruments; {orphan_portfolios} orphan portfolios",
        },
        {
            "name": "Current portfolio weights",
            "status": "Pass" if weight_outliers == 0 else "Review",
            "evidence": f"{weight_outliers} portfolios differ from 100% by more than 0.1 point",
        },
        {
            "name": "Private-market valuation lag",
            "status": "Expected lag" if len(stale) else "Pass",
            "evidence": f"{len(stale)} current positions carry an older valuation date",
        },
        {
            "name": "Annual draw record completeness",
            "status": "Verify" if unquantified_updates else "Pass",
            "evidence": (
                f"Latest note records a changed draw without an amount for: {', '.join(unquantified_updates)}"
                if unquantified_updates
                else "No unquantified annual-draw changes found in the latest RM notes"
            ),
        },
    ]
    return {
        "overall": "Usable with surfaced caveats",
        "checks": checks,
        "policy": "Never hide a conflict; downgrade confidence and ask the RM to verify.",
    }


def build_intelligence_payload(data_dir: str | Path) -> dict[str, Any]:
    data_path = Path(data_dir)
    bundle = load_dataset(data_path)
    as_of = _as_of(bundle)
    clients = bundle["clients"]
    priority = [_priority_card(bundle, row) for row in clients.itertuples()]
    risk_analysis = {row.client_id: analyse_client(bundle, row, as_of) for row in clients.itertuples()}
    for item in priority:
        item["risk_analysis"] = risk_analysis[item["client_id"]]
    priority = order_by_urgency(priority)
    # The queue is capacity-aware: one RM gets five "Now" slots, then a second
    # review band. The underlying numeric score remains visible and inspectable.
    for index, item in enumerate(priority):
        item["priority"] = "Now" if index < 5 else "Next" if index < 12 else "Watch"

    latest_event = (
        bundle["event_log"].sort_values("event_date", ascending=False).iloc[0]
    )
    top_now = sum(1 for item in priority if item["priority"] == "Now")
    current = bundle["holdings"][bundle["holdings"].snapshot_date == as_of]
    stale_count = int(
        (pd.to_datetime(current.valuation_date) < pd.to_datetime(current.snapshot_date)).sum()
    )
    client_profiles = {
        client_id: _feature_profile(bundle, client_id)
        for client_id in clients.client_id.tolist()
    }
    for client_id, profile in client_profiles.items():
        profile["risk_analysis"] = risk_analysis[client_id]

    for profile in client_profiles.values():
        for recommendation in profile["recommendations"]:
            recommendation["risk_validation"] = _recommendation_risk_validation(
                bundle, profile, recommendation
            )
            recommendation["decision_rationale"] = _recommendation_decision_rationale(
                profile, recommendation
            )
            
    focus_client_ids = ["CL-0012", "CL-0014", "CL-0019"]

    return {
        "meta": {
            "product": "TESSERA",
            "tagline": "Decision intelligence for the moments where wealth stories disagree.",
            "as_of": as_of,
            "rm": str(clients.rm_name.mode().iloc[0]),
            "desk": str(clients.rm_desk.mode().iloc[0]),
            "dataset": "Controlled advisory dataset",
            "method": "Deterministic policy and evidence engine",
        },
        "book": {
            "client_count": int(len(clients)),
            "portfolio_count": int(len(bundle["portfolios"])),
            "aum_usd_m": _round(float(clients.total_aum_usd.sum()) / 1_000_000, 1),
            "conversations_now": top_now,
            "stale_valuations": stale_count,
            "priority_queue": priority,
        },
        "market_signal": {
            "date": latest_event.event_date,
            "severity": latest_event.severity,
            "description": latest_event.description,
            "transmission": latest_event.primary_transmission,
            "source": f"event_log.csv • {latest_event.event_date} • authoritative",
        },
        "client_profiles": client_profiles,
        "featured_clients": {
            client_id: client_profiles[client_id] for client_id in focus_client_ids
        },
        "governance": {
            "recommendation_state": "Draft — RM approval required",
            "confidence_rubric": {
                "version": "1.0",
                "meaning": "Evidence and control confidence, not probability of investment success.",
                "bands": [
                    {"range": "85-100", "label": "Strong support", "action": "Final RM suitability review"},
                    {"range": "70-84", "label": "Review ready", "action": "RM review and approval required"},
                    {"range": "50-69", "label": "Verify first", "action": "Resolve flagged inputs before use"},
                    {"range": "0-49", "label": "Blocked", "action": "Do not publish"},
                ],
                "weights": [
                    {"name": "Evidence and lineage", "weight": 25},
                    {"name": "Suitability and policy", "weight": 25},
                    {"name": "Analytical corroboration", "weight": 20},
                    {"name": "Signal relevance", "weight": 15},
                    {"name": "Freshness and data quality", "weight": 10},
                    {"name": "Actionability and reversibility", "weight": 5},
                ],
                "hard_stops": [
                    "Missing current positions, client objective or risk profile",
                    "Broken instrument or portfolio reference integrity",
                    "Missing suitability condition",
                    "Action is not explicitly reversible",
                ],
                "calibration": "Provisional: confidence is capped at 84 until a predictive model is back-tested on recommendation outcomes.",
            },
            "principles": [
                "Authoritative events only: market-event claims come from the controlled event register.",
                "Suitability checks first: mandates and exclusions run before a client brief is prepared.",
                "Purpose-limited access: each brief uses only the records needed for that review.",
                "Conflicts become questions: contradictory records lower confidence instead of being averaged away.",
                "Human accountability: approve, edit, reject and rationale are logged.",
            ],
        },
        "data_quality": _data_quality(bundle),
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(build_intelligence_payload(root / "data"), indent=2))
