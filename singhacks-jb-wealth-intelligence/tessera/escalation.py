"""Escalate a client when live news could break their portfolio, not just nudge it.

Urgency points stay bounded so ordinary news cannot dominate the queue. This
module is the separate lane for a bad day: it applies an illustrative downside
stress to the holdings a headline touches and escalates the client when the
result crosses a hard line (portfolio loss, margin-call trigger or a funding
gap). Stresses are sensitivities, not forecasts, and the RM confirms whether
the headline really applies.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


# Headline pattern, holding terms it reaches, and the illustrative downside
# shock applied to those holdings for a Severe headline.
NEWS_TOPICS: tuple[tuple[str, str, tuple[str, ...], float], ...] = (
    ("energy", r"\b(?:oil|crude|petroleum|energy|natural gas|lng)\b", ("energy", "coal"), 0.15),
    ("shipping", r"\b(?:shipping|tanker|freight|logistics|vessels?)\b", ("shipping", "logistics"), 0.18),
    ("gold", r"\b(?:gold|bullion)\b", ("gold", "xau"), 0.10),
    ("technology", r"\b(?:ai|technology|tech|semiconductor|chip|cloud)\b", ("technology", "semiconductor", "cloud"), 0.15),
    ("healthcare", r"\b(?:healthcare|pharma|biotech)\b", ("health care", "pharma"), 0.12),
    ("property", r"\b(?:property|real estate|reit|housing)\b", ("real estate", "property", "reit"), 0.15),
    ("rates", r"\b(?:rate|rates|yield|yields|fed|treasury|bond|bonds|inflation|central bank|credit)\b", ("fixed income", "credit", "bond", "treasury"), 0.05),
)
SEVERITY_FACTOR = {"Severe": 1.0, "High": 0.5, "Medium": 0.25, "Low": 0.1}

# Hard lines. Crossing any of them escalates regardless of urgency score.
PORTFOLIO_LOSS_PCT = 5.0
FUNDING_WINDOW_DAYS = 365


def _holding_text(current: pd.DataFrame, instruments: pd.DataFrame) -> pd.Series:
    refs = instruments.set_index("instrument_id")
    return current.instrument_id.map(
        lambda i: " ".join(str(refs.at[i, field]) for field in ("instrument_name", "sector", "underlying_reference")).lower()
    )


def _shocks(headline: str, severity: str, texts: pd.Series) -> tuple[pd.Series, list[str]]:
    """Per-holding downside shock for one headline, and the topics it hit."""

    factor = SEVERITY_FACTOR.get(severity, 0.15)
    shock = pd.Series(0.0, index=texts.index)
    topics = []
    for name, pattern, terms, base in NEWS_TOPICS:
        if re.search(pattern, headline, re.I):
            hit = texts.map(lambda text: any(term in text for term in terms))
            if hit.any():
                topics.append(name)
                shock = shock.where(~hit | (shock >= base * factor), base * factor)
    return shock, topics


def assess(
    current: pd.DataFrame,
    instruments: pd.DataFrame,
    events: pd.DataFrame,
    as_of: str,
    needs: list[dict[str, Any]],
    ltv: dict[str, Any] | None,
    collateral_portfolio_id: str | None,
) -> dict[str, Any] | None:
    """Return the most serious escalation triggered by post-snapshot live news."""

    aum = float(current.market_value_usd.sum())
    if not aum or "source_type" not in events:
        return None
    news = events[(events.source_type == "live_news") & (events.event_date.astype(str) >= as_of)]
    if news.empty:
        return None
    texts = _holding_text(current, instruments)
    daily_mask = current.liquidity_tier == "Daily"
    daily = float(current.loc[daily_mask, "market_value_usd"].sum())
    horizon = (pd.Timestamp(as_of) + pd.Timedelta(days=FUNDING_WINDOW_DAYS)).date().isoformat()
    due_soon = sum(
        n["amount_usd_m"] * 1_000_000 for n in needs if n["due_from"] <= horizon and n["certainty"] != "Aspirational"
    )
    collateral = current[current.portfolio_id == collateral_portfolio_id] if collateral_portfolio_id else current.iloc[0:0]
    collateral_value = float(collateral.lending_value_base.sum()) if not collateral.empty else 0.0

    found = []
    for event in news.itertuples():
        shock, topics = _shocks(str(event.description), str(event.severity), texts)
        if not topics:
            continue
        loss = current.market_value_usd * shock
        loss_pct = float(loss.sum()) / aum * 100
        base = {
            "headline": str(event.description),
            "date": str(event.event_date),
            "severity": str(event.severity),
            "source_url": getattr(event, "source", None) if isinstance(getattr(event, "source", None), str) else None,
            "topics": topics,
            "stress_loss_pct": round(loss_pct, 1),
        }
        if ltv and collateral_value:
            drop_pct = float((collateral.lending_value_base * shock.loc[collateral.index]).sum()) / collateral_value * 100
            cushion = float(ltv["lending_value_drop_to_trigger_pct"])
            if drop_pct >= cushion:
                found.append((3, drop_pct, {
                    **base,
                    "kind": "margin_call",
                    "reason": f"Stressed lending value falls {drop_pct:.1f}% against a {cushion:.1f}% cushion to the margin-call trigger",
                }))
        stressed_daily = daily - float(loss[daily_mask].sum())
        if due_soon and due_soon <= daily and due_soon > stressed_daily:
            found.append((2, loss_pct, {
                **base,
                "kind": "funding_gap",
                "reason": f"Stressed daily-liquid assets of USD {stressed_daily / 1e6:.1f}m no longer cover USD {due_soon / 1e6:.1f}m due within 12 months",
            }))
        if loss_pct >= PORTFOLIO_LOSS_PCT:
            found.append((1, loss_pct, {
                **base,
                "kind": "portfolio_loss",
                "reason": f"Downside stress of {loss_pct:.1f}% of bank-held assets on holdings this headline touches",
            }))
    if not found:
        return None
    return max(found, key=lambda item: (item[0], item[1]))[2]
