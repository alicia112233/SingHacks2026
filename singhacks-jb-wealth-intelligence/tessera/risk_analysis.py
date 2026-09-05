"""Small, illustrative risk-prioritisation rules. Not portfolio suitability advice."""
from dataclasses import dataclass
from itertools import groupby
from math import isfinite
from statistics import mean

import pandas as pd


@dataclass(frozen=True)
class RiskThresholds:
    # Inclusive upper bounds for scores 1 through 4; above the last bound is 5.
    cash_share: tuple = (0.01, 0.03, 0.05, 0.10)
    daily_liquid_share: tuple = (0.20, 0.40, 0.60, 0.80)
    tolerance: tuple = (2, 4, 6, 8)
    horizon_years: tuple = (1, 3, 5, 10)
    # Lower LTV/trigger is better. 92% reuses the existing urgency warning boundary.
    debt_proximity: tuple = (0.25, 0.50, 0.75, 0.92)


DEFAULT_THRESHOLDS = RiskThresholds()


def numeric(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def band(value, bounds):
    return 1 + sum(value > boundary for boundary in bounds)


def analyse_client(bundle, client, as_of, rules=DEFAULT_THRESHOLDS):
    """Assess only available evidence; a missing dimension withholds the overall."""
    current = bundle['holdings']
    current = current[(current.client_id == client.client_id) & (current.snapshot_date == as_of)]
    capacity_factors = []
    explanation = []
    values = current.market_value_usd.map(numeric)
    if not current.empty and values.notna().all() and (values >= 0).all() and values.sum() > 0:
        total = float(values.sum())
        if isfinite(total) and current.asset_class.notna().all():
            cash = float(values[current.asset_class == 'Cash and Equivalents'].sum()) / total
            capacity_factors.append(band(cash, rules.cash_share))
            explanation.append(f'Bank-held cash buffer {cash:.1%}')
        if isfinite(total) and current.liquidity_tier.notna().all():
            liquid = float(values[current.liquidity_tier == 'Daily'].sum()) / total
            capacity_factors.append(band(liquid, rules.daily_liquid_share))
            explanation.append(f'daily-liquid assets {liquid:.1%}')
    facilities = bundle['credit_facilities']
    facilities = facilities[facilities.client_id == client.client_id]
    proximities = []
    for facility in facilities.to_dict('records'):
        ltv = numeric(facility.get(f'ltv_pct_{as_of}'))
        trigger = numeric(facility.get('margin_call_ltv_pct'))
        if ltv is not None and ltv >= 0 and trigger is not None and trigger > 0:
            proximities.append(ltv / trigger)
    if proximities and len(proximities) == len(facilities):
        worst = max(proximities)
        # At the existing 92% warning threshold, use the lowest debt capacity band.
        debt_score = 5 - sum(worst >= boundary for boundary in rules.debt_proximity)
        capacity_factors.append(debt_score)
        explanation.append(f'highest recorded LTV is {worst:.1%} of its margin-call trigger')
    capacity = round(mean(capacity_factors), 1) if capacity_factors else None

    recorded = numeric(getattr(client, 'risk_tolerance_score', None))
    tolerance = band(recorded, rules.tolerance) if recorded is not None and 1 <= recorded <= 10 else None
    if tolerance is not None:
        explanation.append(f'recorded tolerance {recorded:g}/10')

    years = numeric(getattr(client, 'investment_horizon_years', None))
    if years is not None and years >= 0:
        explanation.append(f'stated horizon {years:g} years')
    else:
        years = None
        needs = bundle['planned_cash_needs']
        needs = needs[(needs.client_id == client.client_id) & (needs.certainty == 'Confirmed') & (needs.recurrence == 'One-off')]
        dates = pd.to_datetime(needs.due_from, errors='coerce').dropna()
        if not dates.empty:
            target = dates.min()
            years = max(0, (target - pd.Timestamp(as_of)).days / 365.25)
            explanation.append(f'earliest confirmed one-off funding date {target.date()}')
    horizon = band(years, rules.horizon_years) if years is not None else None
    dimensions = {'capacity': capacity, 'tolerance': tolerance, 'horizon': horizon}
    overall = mean(dimensions.values()) if all(v is not None for v in dimensions.values()) else None
    missing = [name for name, value in dimensions.items() if value is None]
    text = '; '.join(explanation) + '.' if explanation else 'No assessable customer inputs.'
    text += ' Capacity is a bank-held estimate; income stability and complete household debt are unavailable.'
    if missing:
        text += ' Insufficient data: ' + ', '.join(missing) + '.'
    return {**dimensions, 'overall': overall, 'explanation': text}


def order_by_urgency(customers):
    """Stable urgency sort; reorder a tied group only when EVERY risk is complete."""
    ordered = []
    for _, group in groupby(sorted(customers, key=lambda c: c['score'], reverse=True), key=lambda c: c['score']):
        tied = list(group)
        if all(numeric(c.get('risk_analysis', {}).get('overall')) is not None for c in tied):
            tied.sort(key=lambda c: c['risk_analysis']['overall'])
        ordered.extend(tied)
    return ordered
