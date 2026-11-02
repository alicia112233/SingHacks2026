"""Describe every client as a vector of named numbers, then compare them.

Each dimension is calculated by code from data the bank already holds, so the
vector never needs an outside model and every value can be explained. Vectors
are client data (C3 to C4): they stay inside TESSERA and are never sent to a
model. Similarity is a measure of how alike two books look, not a prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tessera.contradictions import GATED_TIERS, RISK_ASSET_CLASSES, THEMES, _intent, _link, _lookthrough, _matches


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    group: str
    unit: str  # share (0 to 1), ratio, score, years or points (signed share)


THEME_LABELS = tuple(dict.fromkeys(theme.label for theme in THEMES))
ASSET_CLASSES = (
    ("Equity", "Equity"),
    ("Fixed Income", "Fixed income"),
    ("Structured Products", "Structured products"),
    ("Alternatives", "Alternatives"),
    ("Commodities", "Commodities"),
    ("Cash and Equivalents", "Cash"),
)

FEATURES: tuple[Feature, ...] = (
    *(Feature(f"theme:{label}", label.capitalize(), "Exposure, looked through", "share") for label in THEME_LABELS),
    *(Feature(f"asset:{name}", label, "Portfolio build", "share") for name, label in ASSET_CLASSES),
    Feature("currency_mismatch", "Held outside base currency", "Portfolio build", "share"),
    Feature("daily_liquid", "Sellable daily", "Liquidity", "share"),
    Feature("gated", "Gated or illiquid", "Liquidity", "share"),
    Feature("ltv_to_trigger", "Loan against its margin-call level", "Obligations", "share"),
    Feature("cash_need_cover", "Cash due in 24 months against daily-liquid assets", "Obligations", "ratio"),
    Feature("uncalled_share", "Uncalled fund commitments", "Obligations", "share"),
    Feature("risk_tolerance", "Risk tolerance score", "Stated profile", "score"),
    Feature("horizon_years", "Investment horizon", "Stated profile", "years"),
    Feature("risk_gap", "Risk assets above target", "Stated profile", "points"),
)
KEYS = [feature.key for feature in FEATURES]
BY_KEY = {feature.key: feature for feature in FEATURES}

NEED_WINDOW_DAYS = 730
SIMILAR_COUNT = 3


def _raw_vector(
    client: Any,
    current: pd.DataFrame,
    instruments: pd.DataFrame,
    facility: pd.Series | None,
    uncalled_usd: float,
    needs: list[dict[str, Any]],
    snapshot: str,
) -> dict[str, float]:
    aum = float(current.market_value_usd.sum())
    if not aum:
        return {key: 0.0 for key in KEYS}
    values: dict[str, float] = {}
    lookthrough = _lookthrough(current, instruments)
    held = current.groupby("instrument_id").market_value_usd.sum()
    for label in THEME_LABELS:
        themes = [theme for theme in THEMES if theme.label == label]
        hit = [iid for iid, holding in lookthrough.items() if any(_matches(theme, holding) for theme in themes)]
        values[f"theme:{label}"] = float(held.reindex(hit).sum()) / aum
    by_class = current.groupby("asset_class").market_value_usd.sum()
    for name, _ in ASSET_CLASSES:
        values[f"asset:{name}"] = float(by_class.get(name, 0.0)) / aum
    values["currency_mismatch"] = float(current.loc[current.instrument_ccy != client.base_currency, "market_value_usd"].sum()) / aum

    daily = float(current.loc[current.liquidity_tier == "Daily", "market_value_usd"].sum())
    values["daily_liquid"] = daily / aum
    values["gated"] = float(current.loc[current.liquidity_tier.isin(GATED_TIERS), "market_value_usd"].sum()) / aum

    if facility is not None and f"ltv_pct_{snapshot}" in facility.index:
        values["ltv_to_trigger"] = float(facility[f"ltv_pct_{snapshot}"]) / float(facility.margin_call_ltv_pct)
    else:
        values["ltv_to_trigger"] = 0.0
    start = pd.Timestamp(snapshot)
    due = sum(
        need["amount_usd_m"] * 1_000_000
        for need in needs
        if pd.Timestamp(need["due_from"]) <= start + pd.Timedelta(days=NEED_WINDOW_DAYS)
        and pd.Timestamp(need["due_to"] or need["due_from"]) >= start
    )
    values["cash_need_cover"] = due / daily if daily else (float(due > 0) * 10.0)
    values["uncalled_share"] = uncalled_usd / aum

    tolerance = float(client.risk_tolerance_score)
    values["risk_tolerance"] = tolerance
    values["horizon_years"] = float(client.investment_horizon_years)
    risk_share = float(current.loc[current.asset_class.isin(RISK_ASSET_CLASSES), "market_value_usd"].sum()) / aum
    # Same target the urgency score uses, so the two never disagree.
    values["risk_gap"] = risk_share - (0.10 + tolerance * 0.07)
    return values


def _scaled(raw: pd.DataFrame) -> pd.DataFrame:
    """Rank each feature across the book, centre it, and weight each group equally.

    Ranks stop one very large position (or a huge cash ratio) from swamping
    every other dimension. Group weights stop a group with many dimensions,
    like exposures, from outvoting a group with few.
    """

    ranked = raw.rank(pct=True, method="average")
    centred = ranked - ranked.mean()
    sizes = pd.Series([BY_KEY[key].group for key in raw.columns]).value_counts()
    weights = np.array([1 / np.sqrt(sizes[BY_KEY[key].group]) for key in raw.columns])
    return centred * weights


def _cosine(matrix: pd.DataFrame) -> pd.DataFrame:
    norms = np.linalg.norm(matrix.values, axis=1)
    norms[norms == 0] = 1.0
    unit = matrix.values / norms[:, None]
    return pd.DataFrame(unit @ unit.T, index=matrix.index, columns=matrix.index)


def _shared(a: str, b: str, raw: pd.DataFrame, scaled: pd.DataFrame) -> list[dict[str, Any]]:
    """The dimensions where both clients sit above the book average, strongest first."""

    both = scaled.loc[[a, b]]
    keys = [key for key in raw.columns if (both[key] > 0).all() and raw.loc[[a, b], key].abs().min() > 0]
    keys.sort(key=lambda key: float(both[key].min()), reverse=True)
    return [
        {"key": key, "label": BY_KEY[key].label, "unit": BY_KEY[key].unit, "a": _value(raw.at[a, key]), "b": _value(raw.at[b, key])}
        for key in keys[:3]
    ]


def _value(number: float) -> float:
    return round(float(number), 4)


def _map(scaled: pd.DataFrame) -> tuple[dict[str, dict[str, float]], dict[str, list[str]]]:
    """Project the book onto its two strongest directions, for a 2D map."""

    values = scaled.values - scaled.values.mean(axis=0)
    _, _, components = np.linalg.svd(values, full_matrices=False)
    coords = values @ components[:2].T
    span = np.abs(coords).max(axis=0)
    span[span == 0] = 1.0
    coords = coords / span
    axes = {}
    for index, axis in enumerate(("x", "y")):
        order = np.argsort(components[index])
        axes[axis] = {
            "low": [BY_KEY[scaled.columns[i]].label for i in order[:2]],
            "high": [BY_KEY[scaled.columns[i]].label for i in order[::-1][:2]],
        }
    points = {cid: {"x": round(float(x), 3), "y": round(float(y), 3)} for cid, (x, y) in zip(scaled.index, coords)}
    return points, axes


def build_client_vectors(bundle: dict[str, Any], needs_by_client: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    clients = bundle["clients"].set_index("client_id")
    holdings, instruments = bundle["holdings"], bundle["instruments"]
    facilities = bundle["credit_facilities"].set_index("client_id")
    uncalled = bundle["commitments"].groupby("client_id").uncalled.sum()
    snapshots = sorted(holdings.snapshot_date.unique())
    as_of = snapshots[-1]

    def raw_at(snapshot: str) -> pd.DataFrame:
        current = holdings[holdings.snapshot_date == snapshot]
        rows = {}
        for cid, client in clients.iterrows():
            rows[cid] = _raw_vector(
                client,
                current[current.client_id == cid],
                instruments,
                facilities.loc[cid] if cid in facilities.index else None,
                float(uncalled.get(cid, 0.0)),
                needs_by_client.get(cid, []),
                snapshot,
            )
        return pd.DataFrame.from_dict(rows, orient="index")[KEYS]

    history = {snapshot: raw_at(snapshot) for snapshot in snapshots}
    raw = history[as_of]
    scaled = _scaled(raw)
    similarity = _cosine(scaled)
    points, axes = _map(scaled)

    result: dict[str, Any] = {}
    for cid, client in clients.iterrows():
        ranked = similarity.loc[cid].drop(cid).sort_values(ascending=False).head(SIMILAR_COUNT)
        _, intended, retained, _ = _intent(client)
        avoid = [theme for theme in intended if theme not in retained]
        gap = None
        if avoid:
            gap = []
            for snapshot in snapshots:
                current = holdings[(holdings.snapshot_date == snapshot) & (holdings.client_id == cid)]
                aum = float(current.market_value_usd.sum())
                link = _link(avoid, current, aum, _lookthrough(current, instruments)) if aum else None
                gap.append({"date": snapshot, "pct": link["exposure_pct"] if link else 0.0})
        first, last = history[snapshots[0]].loc[cid], raw.loc[cid]
        moves = (last - first).abs()
        moves = moves[[key for key in KEYS if BY_KEY[key].unit == "share"]].sort_values(ascending=False)
        result[cid] = {
            "values": {key: _value(raw.at[cid, key]) for key in KEYS},
            "similar": [
                {
                    "client_id": other,
                    "name": str(clients.at[other, "client_name"]),
                    "similarity": round(float(score), 2),
                    "shared": _shared(cid, other, raw, scaled),
                }
                for other, score in ranked.items()
            ],
            "goal_gap": gap,
            "goal_themes": " and ".join(dict.fromkeys(theme.label for theme in avoid)) or None,
            "biggest_moves": [
                {"key": key, "label": BY_KEY[key].label, "from": _value(first[key]), "to": _value(last[key])}
                for key in moves.index[:3]
                if moves[key] >= 0.01
            ],
            "map": points[cid],
        }
    return {
        "as_of": as_of,
        "snapshots": snapshots,
        "method": "Named features calculated in-house from the client record. Each feature is ranked across the book, groups are weighted equally, and similarity is cosine. Similarity, not prediction; never sent to any model.",
        "features": [{"key": f.key, "label": f.label, "group": f.group, "unit": f.unit} for f in FEATURES],
        "axes": axes,
        "clients": result,
    }
