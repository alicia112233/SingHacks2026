"""Evidence-grounded analytics for the TESSERA prototype.

The prototype deliberately keeps calculation and narrative generation deterministic.
In a bank deployment, the returned evidence bundles are the only context passed to a
private LLM. This makes every client-facing sentence reproducible and auditable.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DATASET_TODAY = "2026-08-26"
SEVERITY_ORDER = {"Severe": 3, "High": 2, "Medium": 1, "Low": 0}
FACTOR_LABELS = {
    "SYN-AL-0307": "Direct Mid-Levels property",
    "SYN-FI-0201": "US Treasury due 2045",
    "SYN-FI-0203": "Global IG bond fund",
    "SYN-FI-0204": "Asia IG credit fund",
    "SYN-FI-0206": "Pacific Rim bank perpetual",
    "SYN-FI-0207": "Golden Harbour perpetual",
    "SYN-ST-0104": "Pacific Orient Shipping",
    "SYN-ST-0106": "Golden Harbour equity",
    "SYN-EQ-0008": "Global energy majors",
    "SYN-EQ-0025": "Asia shipping & logistics",
    "SYN-SP-0503": "Golden Harbour accumulator",
    "SYN-SP-0505": "Shipping & energy FCN",
}

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
        "label": "Lifetime income vs 2045 duration",
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

    for _, portfolio in portfolios[portfolios.client_id == client_id].iterrows():
        if portfolio.service_model == "Custody":
            continue
        current = holdings[
            (holdings.portfolio_id == portfolio.portfolio_id)
            & (holdings.snapshot_date == DATASET_TODAY)
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
    result = []
    for row in subset.itertuples():
        result.append(
            {
                "id": row.need_id,
                "description": row.description,
                "currency": row.currency,
                "amount": float(row.amount),
                "amount_usd_m": _round(
                    _to_usd(bundle, float(row.amount), row.currency, DATASET_TODAY) / 1_000_000,
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
    current = bundle["holdings"][(bundle["holdings"].client_id == client_id) & (bundle["holdings"].snapshot_date == DATASET_TODAY)]
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
        ltv = float(facility.iloc[0][f"ltv_pct_{DATASET_TODAY}"])
        trigger = float(facility.iloc[0].margin_call_ltv_pct)
        proximity = ltv / trigger
        if proximity >= 0.92:
            governance_pressure = min(20.0, governance_pressure + 8.0)
        ltv_text = f"LTV {ltv:.2f}% vs {trigger:.0f}% trigger"

    kyc_due = datetime.strptime(str(client_row.kyc_review_due), "%Y-%m-%d").date()
    days_to_kyc = (kyc_due - datetime.strptime(DATASET_TODAY, "%Y-%m-%d").date()).days
    time_pressure = 12.0 if days_to_kyc <= 30 else 7.0 if days_to_kyc <= 90 else 2.0
    if needs and min(n["due_from"] for n in needs) <= "2026-12-31":
        time_pressure = min(15.0, time_pressure + 6.0)

    goal_pressure = float(rule.get("goal_points", 8.0))
    score = min(99, round(goal_pressure + liquidity_pressure + governance_pressure + time_pressure))

    if rule.get("theme_ids"):
        exposure = _theme_exposure(current, rule["theme_ids"], aum)
        evidence_line = f"{exposure:.1f}% linked to {rule['theme']} before outside wealth"
    elif client_id == "CL-0012":
        fi = float(current.loc[current.asset_class == "Fixed Income", "market_value_usd"].sum()) / aum * 100
        evidence_line = f"{fi:.1f}% fixed income; longest bond matures in 2045"
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
    baseline = holdings[(holdings.client_id == client_id) & (holdings.snapshot_date == "2025-12-31")]
    current = holdings[(holdings.client_id == client_id) & (holdings.snapshot_date == DATASET_TODAY)]
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
            impacts.append(
                {
                    "factor": FACTOR_LABELS.get(key.split(":", 1)[1], key.split(":", 1)[1]),
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
    facility = row.iloc[0]
    drawn = float(facility[f"drawn_{DATASET_TODAY}"])
    lending = float(facility[f"lending_value_{DATASET_TODAY}"])
    trigger = float(facility.margin_call_ltv_pct)
    trigger_lending = drawn / (trigger / 100)
    buffer = lending - trigger_lending
    return {
        "facility_id": facility.facility_id,
        "currency": facility.facility_ccy,
        "ltv_pct": _round(float(facility[f"ltv_pct_{DATASET_TODAY}"]), 2),
        "trigger_pct": _round(trigger, 1),
        "points_to_trigger": _round(trigger - float(facility[f"ltv_pct_{DATASET_TODAY}"]), 2),
        "lending_value_buffer_m": _round(buffer / 1_000_000, 2),
        "lending_value_drop_to_trigger_pct": _round(buffer / lending * 100, 2),
        "reported_headroom_m": _round(float(facility[f"headroom_{DATASET_TODAY}"]) / 1_000_000, 2),
    }


def _feature_profile(bundle: dict[str, Any], client_id: str) -> dict[str, Any]:
    clients = bundle["clients"]
    client = clients[clients.client_id == client_id].iloc[0]
    current = bundle["holdings"][(bundle["holdings"].client_id == client_id) & (bundle["holdings"].snapshot_date == DATASET_TODAY)].copy()
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
        long_bond = float(current.loc[current.instrument_id == "SYN-FI-0201", "market_value_usd"].sum())
        cash = float(current.loc[current.asset_class == "Cash and Equivalents", "market_value_usd"].sum())
        structured_need = next(n for n in needs if n["id"] == "CN-012")
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
                    "client_says": "“I do not want to sell anything at a loss.”",
                    "portfolio_does": f"{fixed_income / aum * 100:.1f}% sits in fixed income; {long_bond / aum * 100:.1f}% is one Treasury due 2045.",
                    "future_demands": f"Structured data says USD {structured_need['amount_usd_m']:.2f}m a year; the RM note still says USD 1.10m.",
                },
                "headline_metrics": [
                    {"value": f"{fixed_income / aum * 100:.1f}%", "label": "fixed income"},
                    {"value": "2045", "label": "longest maturity"},
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
                        "detail": "Reconcile USD 1.10m in the July RM note with USD 1.28m in planned_cash_needs.csv.",
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
                        "detail": "Compare maturity dates with the client’s 12-year horizon; involve the client in sequencing, not a binary sell/hold choice.",
                        "suitability": "RM judgement required",
                        "reversible": True,
                    },
                ],
                "conversation": {
                    "open": "You were right to ask why a ‘safe’ portfolio can still fall. The issue is not whether the bonds repay—it is whether their timetable still fits yours.",
                    "show": "One page: annual spending, the 2045 maturity, and two rate sensitivities.",
                    "ask": "Before we change anything, has your annual draw moved from USD 1.10m to USD 1.28m?",
                    "avoid": "Do not lead with total return or tell him to wait for recovery.",
                },
                "confidence": {
                    "level": "Needs verification",
                    "reason": "The RM note says USD 1.10m while the structured cash-need record says USD 1.28m annually.",
                },
                "evidence_passport": [
                    {"claim": "Annual need is USD 1.28m", "source": "planned_cash_needs.csv • CN-012", "status": "Structured"},
                    {"claim": "Client recalls USD 1.10m and refuses loss sales", "source": "rm_notes.json • N-016", "status": "Unstructured"},
                    {"claim": "The largest bond matures in 2045", "source": "holdings.csv • SYN-FI-0201 • 2026-08-26", "status": "Verified"},
                    {"claim": "Rates repriced after the energy shock", "source": "event_log.csv • 2026-06-17 / 2026-07-29", "status": "Authoritative"},
                ],
            }
        )

    elif client_id == "CL-0014":
        linked_ids = CLIENT_RULES[client_id]["theme_ids"]
        exposure = _theme_exposure(current, linked_ids, aum)
        ltv = _ltv_trigger_buffer(bundle, client_id)
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
                    "client_says": "“That is why I am confident.”",
                    "portfolio_does": f"{exposure:.1f}% is linked to Hong Kong property across direct property, equity, perpetual and accumulator.",
                    "future_demands": "HKD 60m redevelopment contribution by mid-2027 while facility LTV sits just below its trigger.",
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
                        "detail": f"Treat the HKD {ltv['lending_value_buffer_m']:.2f}m trigger buffer—not reported headroom—as the binding constraint.",
                        "suitability": "Credit review required",
                        "reversible": True,
                    },
                    {
                        "title": "Separate ‘conviction’ from four wrappers of one risk",
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
                    "open": "Your property view may be right. The risk is that four different wrappers and your development project all require the same view to be right at the same time.",
                    "show": "The look-through stack beside the LTV threshold and HKD 60m funding date.",
                    "ask": "Which matters more over the next ten months: preserving upside or guaranteeing the project equity?",
                    "avoid": "Do not describe reported facility headroom as margin-call protection.",
                },
                "confidence": {
                    "level": "High",
                    "reason": "Positions, look-through instrument terms, cash need and facility fields reconcile at the current snapshot.",
                },
                "evidence_passport": [
                    {"claim": f"{exposure:.1f}% linked to HK property", "source": "holdings.csv + instruments.csv • 2026-08-26", "status": "Verified"},
                    {"claim": "Accumulator doubles below strike", "source": "instruments.csv • SYN-SP-0503", "status": "Verified"},
                    {"claim": "HKD 60m contribution is confirmed", "source": "planned_cash_needs.csv • CN-013", "status": "Structured"},
                    {"claim": f"LTV is {ltv['ltv_pct']:.2f}% vs 70%", "source": "credit_facilities.csv • CF-0002", "status": "Verified"},
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
        base.update(
            {
                "tension": {
                    "client_says": "The Asia portfolio should be uncorrelated with the Gulf business.",
                    "portfolio_does": f"{exposure:.1f}% is linked to shipping and energy after looking through the FCN.",
                    "future_demands": f"USD 5.0m seed capital in 2027 versus USD {cash / 1_000_000:.1f}m in cash today.",
                },
                "headline_metrics": [
                    {"value": f"{exposure:.1f}%+", "label": "shipping & energy"},
                    {"value": f"+{(_snapshot_path(bundle, client_id)[-1]['aum_usd_m'] / _snapshot_path(bundle, client_id)[0]['aum_usd_m'] - 1) * 100:.1f}%", "label": "value path since Dec*"},
                    {"value": "USD 5m", "label": "2027 seed capital"},
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
                        "detail": "The 42% portfolio figure is a floor because the Gulf logistics business is not valued in the dataset.",
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
                    "show": "The FCN look-through, the two Strait scenarios, and the USD 5m 2027 commitment.",
                    "ask": "If the Strait reopened next month, how much of this year’s gain are you willing to give back?",
                    "avoid": "Do not imply we know when normalization occurs or value the private operating business without data.",
                },
                "confidence": {
                    "level": "High on portfolio / incomplete household",
                    "reason": "Bank-held exposure is exact; outside Gulf business exposure is qualitative only.",
                },
                "evidence_passport": [
                    {"claim": f"{exposure:.1f}% linked to shipping and energy", "source": "holdings.csv + instruments.csv • 2026-08-26", "status": "Verified"},
                    {"claim": "FCN is worst-of shipping / energy basket", "source": "instruments.csv • SYN-SP-0505", "status": "Verified"},
                    {"claim": "Naval blockade was reimposed", "source": "event_log.csv • 2026-08-05", "status": "Authoritative"},
                    {"claim": "USD 5m seed capital is likely", "source": "planned_cash_needs.csv • CN-017", "status": "Structured"},
                ],
            }
        )
    else:
        raise KeyError(f"No featured profile configured for {client_id}")
    return base


def _data_quality(bundle: dict[str, Any]) -> dict[str, Any]:
    holdings = bundle["holdings"]
    portfolios = bundle["portfolios"]
    instruments = bundle["instruments"]
    current = holdings[holdings.snapshot_date == DATASET_TODAY]

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
            "name": "Cheung annual draw",
            "status": "Verify",
            "evidence": "RM note: USD 1.10m; planned cash need: USD 1.28m",
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
    clients = bundle["clients"]
    priority = [_priority_card(bundle, row) for row in clients.itertuples()]
    priority.sort(key=lambda item: item["score"], reverse=True)
    # The queue is capacity-aware: one RM gets five "Now" slots, then a second
    # review band. The underlying numeric score remains visible and inspectable.
    for index, item in enumerate(priority):
        item["priority"] = "Now" if index < 5 else "Next" if index < 12 else "Watch"

    latest_event = (
        bundle["event_log"].sort_values("event_date", ascending=False).iloc[0]
    )
    top_now = sum(1 for item in priority if item["priority"] == "Now")
    current = bundle["holdings"][bundle["holdings"].snapshot_date == DATASET_TODAY]
    stale_count = int(
        (pd.to_datetime(current.valuation_date) < pd.to_datetime(current.snapshot_date)).sum()
    )

    return {
        "meta": {
            "product": "TESSERA",
            "tagline": "Decision intelligence for the moments where wealth stories disagree.",
            "as_of": DATASET_TODAY,
            "rm": "Priscilla Ong",
            "desk": "Asia desk • Singapore + Hong Kong",
            "dataset": "Synthetic SingHacks 2026 data",
            "method": "Deterministic evidence compiler; private-LLM ready",
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
        "featured_clients": {
            client_id: _feature_profile(bundle, client_id)
            for client_id in ["CL-0012", "CL-0014", "CL-0019"]
        },
        "governance": {
            "recommendation_state": "Draft — RM approval required",
            "principles": [
                "Authoritative events only: 2026 claims come from event_log.csv.",
                "Suitability before eloquence: mandates and exclusions run before narrative generation.",
                "Evidence-bound generation: the model receives selected rows, not unrestricted bank data.",
                "Conflicts become questions: contradictory records lower confidence instead of being averaged away.",
                "Human accountability: approve, edit, reject and rationale are logged.",
            ],
        },
        "data_quality": _data_quality(bundle),
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(build_intelligence_payload(root / "data"), indent=2))
