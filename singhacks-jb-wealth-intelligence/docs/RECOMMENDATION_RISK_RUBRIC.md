# TESSERA Recommendation Risk Rubric

## Purpose

This rubric validates an LLM-drafted investment recommendation before it reaches a Relationship Manager (RM). It publishes a **Recommendation Confidence Score (0-100)** that answers:

> How well is this recommendation supported by current evidence, suitability controls, analytical validation and an accountable human review process?

The score is **not** a probability of positive return, a forecast accuracy percentage or permission to trade. Every recommendation remains a draft until the RM approves, edits or dismisses it.

## Two-layer validation

```text
Controlled client, product and signal data
                    |
          Deterministic hard stops
                    |
          LLM drafts recommendation
                    |
      Predictive / analytical validator
                    |
       Confidence score + reasons
                    |
        RM approve / edit / dismiss
                    |
        Append-only decision ledger
```

1. **Model validation** checks whether the recommendation is directionally and materially supported by an independent analytical model. TESSERA currently uses transparent portfolio sensitivities. Because these are not calibrated predictions, this layer is marked `Provisional` and confidence is capped at 84.
2. **Human validation** requires the RM to inspect the evidence, confirm suitability and record a decision with rationale. The LLM cannot waive this control or place a trade.

### Independent LLM judge panel

An on-demand panel may run the same purpose-limited evidence packet through
models from different providers. Each judge separately scores customer fit,
product fit and signal support and lists unsupported claims, conflicts and RM
checks. The panel score is the lower of the deterministic score and the median
completed-judge score. A spread above 20 points caps the result at 69; any judge
`block` verdict caps it at 49. A judge can lower or challenge the recommendation
but can never bypass a deterministic hard stop or raise the deterministic score.

External judges are disabled by default and receive no client name, client ID or
raw RM notes when enabled. Their outputs are opinions, not a predictive
probability and not an approval.

## Score composition

| Dimension | Weight | What is tested | Primary TESSERA sources |
|---|---:|---|---|
| Evidence and lineage | 25 | Each material claim resolves to a source record and effective date; conflicting evidence is visible | `holdings.csv`, `instruments.csv`, `transactions.csv`, `rm_notes.json` |
| Suitability and policy | 25 | Risk profile, objective, horizon, liquidity, mandate bands, exclusions, concentration, service model and KYC | `clients.csv`, `portfolios.csv`, `mandates.csv` |
| Predictive / analytical corroboration | 20 | Independent model direction, magnitude, scenario coverage, stability and calibration | Holdings, price history, `market_context.csv`; future model outcome table |
| Signal relevance | 15 | The signal is authoritative, timely, exposure-linked and material to this client | `event_log.csv`, `market_context.csv`, cash needs, commitments, facilities |
| Freshness and data quality | 10 | Completeness, reference integrity, reconciliation, valuation age and conflicting updates | All effective-date records |
| Actionability and reversibility | 5 | Clear action, suitability condition, owner, decision point and reversibility | Recommendation payload and decision ledger |

`raw score = sum of dimension points`

`published score = 0 when blocked; otherwise min(raw score, all applicable confidence caps)`

The UI must show the total, dimension scores, applied caps, blockers, source dates and rubric version. A score without its reasons is not publishable.

## Decision bands

| Score | Band | RM use |
|---:|---|---|
| 85-100 | Strong support | RM may approve after final suitability review |
| 70-84 | Review ready | Supported for RM review; approval remains mandatory |
| 50-69 | Verify first | RM must resolve flagged inputs before using the recommendation |
| 0-49 | Blocked | Do not publish or discuss as a recommendation |

The current sensitivity-only implementation cannot enter `Strong support`; 84 is its maximum.

## Hard stops

Any hard stop sets the score to zero and prevents publication:

- no current position snapshot, client objective or risk profile;
- orphaned portfolio or instrument references;
- proposed action has no suitability condition;
- proposed action is not explicitly reversible;
- unresolved binding mandate exclusion or product eligibility failure;
- the recommendation contains a number, instrument, event or client fact that cannot be resolved to the evidence set;
- the LLM proposes a trade, guarantee, fabricated probability or claim outside the approved product universe;
- required KYC, sanctions, PEP or jurisdiction control is failed or unavailable.

The first four controls are implemented in the current demo. The remaining controls are required before production deployment.

## Confidence caps

Caps prevent a high average from hiding one important weakness:

| Condition | Maximum score |
|---|---:|
| No calibrated predictive outcome model or back-test | 84 |
| Material outside wealth or operating-business exposure is unrecorded | 79 |
| Source conflict or an RM note changes an amount without quantifying it | 59 |
| Critical stale price, missing product term or incomplete look-through | 49 |
| Any hard stop | 0 |

The lowest applicable cap wins. Expected quarterly private-market valuation lag reduces the freshness dimension but is not automatically a hard stop unless the proposed action depends on a current executable value.

## Dataset-specific tests

### Client and suitability signals

- Compare `risk_profile`, `risk_tolerance_score`, `investment_horizon_years`, `liquidity_needs` and `objectives` to the proposed action.
- Use `tax_domicile`, not residence alone, for tax-sensitive wording.
- Flag overdue or soon-due `kyc_review_due` before advice.
- Treat RM notes as context, not unquestioned truth. A conflict with structured data becomes an RM question and score cap.

### Product and portfolio tests

- Aggregate exposure across every client portfolio; do not treat custody assets as mandate-managed.
- Apply mandate bands only to non-custody portfolios.
- Apply `max_single_position_pct` only where `concentration_limit_applies = Y`.
- Enforce `sustainability_excluded = Y` for sustainable mandates.
- Look through structured products using `underlying_reference` before measuring concentration or signal relevance.
- Test sellability using `liquidity_tier`, not asset class labels.
- Reconcile significant position movements to `transactions.csv` before attributing them to markets.

### Liquidity and credit tests

- Match dated `planned_cash_needs.csv` and `commitments.csv` to assets actually available by the due date.
- Convert currencies with the correct market convention and effective date.
- Calculate LTV from drawn amount divided by haircut-adjusted lending value.
- Compare to `margin_call_ltv_pct`; do not describe reported headroom as margin-call protection.

### Market and event signals

- Market-event claims must exist in the controlled `event_log.csv`.
- Link an event's `primary_transmission` to actual holdings or look-through underlyings.
- Require time relevance and material exposure; a severe global event is not automatically relevant to every client.
- Use scenario results as sensitivities unless a calibrated probability model exists. Never convert a scenario into a forecast through wording.

## Predictive-model validation contract

For production, the independent model should return this minimum record for each recommendation:

```json
{
  "model_version": "portfolio-risk-2026-09",
  "as_of": "2026-08-26",
  "target": "risk_event_within_horizon",
  "horizon_days": 90,
  "probability": 0.63,
  "direction_agrees": true,
  "materiality_agrees": true,
  "out_of_distribution": false,
  "calibration_segment": "advisory-balanced-asia",
  "backtest": {
    "sample_size": 850,
    "brier_score": 0.14,
    "expected_calibration_error": 0.04,
    "as_of": "2026-06-30"
  }
}
```

The predictive dimension should award points for:

- direction agreement between recommendation and model: 0-5;
- materiality agreement and sensitivity coverage: 0-5;
- probability calibration on an out-of-time holdout: 0-5;
- stability, drift and out-of-distribution checks: 0-3;
- adequate sample size and segment coverage: 0-2.

Model disagreement does not let the LLM choose the more convenient answer. It routes the case to `Verify first`; out-of-distribution input or failed drift limits should block model-derived claims.

## Human-in-the-loop checklist

Before approval, the RM confirms:

1. The recommendation matches the client's latest objective, risk tolerance and decision horizon.
2. Material outside assets, liabilities and recent client instructions have been considered.
3. Product eligibility, mandate, concentration, liquidity, credit and jurisdiction conditions are satisfied.
4. All numbers and named events open to their evidence records and dates.
5. Scenario language is presented as sensitivity, not certainty.
6. The proposed action is understandable, reversible and appropriate for the account's service model.
7. Any edit and the approval or dismissal rationale are recorded in the decision ledger.

## Calibration and monitoring

Store the rubric version, component scores, model version, LLM prompt/model version, RM decision and subsequent outcome. Monitor monthly by desk and recommendation type:

- RM approval, edit and dismissal rates by confidence band;
- unsupported-claim rate and source-resolution failures;
- override rate, with reason codes;
- adverse suitability or compliance findings;
- model calibration, drift and out-of-distribution rate;
- realised risk-event rate by predicted probability band;
- score distribution by client segment to detect unfair or systematic under-confidence.

Thresholds should be recalibrated only on out-of-time outcomes with Compliance, Model Risk and Front Office approval. Do not tune the score merely to increase RM approvals.

## Current implementation status

The API attaches `risk_validation` to every recommendation and the client review displays its score and detail. The Evidence & Governance view publishes rubric weights and bands. Current limitations are deliberately visible:

- analytical validation is based on deterministic scenario sensitivities, not predictive probabilities;
- no historical outcome labels or formal back-test are bundled;
- selected production hard stops (product eligibility, sanctions, jurisdiction and claim-level LLM entailment) still require bank source systems;
- RM approval remains mandatory for every band.


## Version 1.1: action-specific demo assessment

Actions carry explicit assessment kinds, independent of title and list order.
`tessera/recommendation_validation.py` declares the evidence groups, pending
controls, analytical method and outside-wealth relevance for each kind.

- Evidence: 25 times the fraction of required action input groups present.
  This is input coverage, not certification of every narrative claim.
- Suitability: start at 25, withhold 3 for each pending action control and each
  missing input group. A missing suitability condition still triggers a hard stop.
- Analytical support: only relevant diagnostics earn points. Credit diagnostics
  earn up to 10; mandate findings 8; snapshot deltas 4 with 6 reserved for completed
  transaction attribution; dated liabilities 3 with 7 reserved for a tested funding
  plan; look-through 5; scenario discussion up to 10; duration discussion up to 4.
  Calibration, stability and outcome coverage remain unimplemented and earn 0/10.
- Signal relevance: fraction of required action signal groups present, worth up
  to 15. Profile/context availability alone is not a market signal. Timing and
  materiality still need RM confirmation.
- Freshness: the existing 10/7/4 portfolio valuation rule remains shared.
- Actionability: reversibility earns 2; condition, wording and explicit decision
  date earn 1 each. A liability date does not count as an agreed action date.

These are provisional demo heuristics, not calibrated investment-success scores.
Equal scores are allowed. The 84 cap remains universal; the 79 outside-wealth cap
applies only to actions whose assessment contract depends on household wealth.
Source-conflict caps apply to liability/funding and broader client-review actions,
not unrelated bank transaction or mandate diagnostics.

Numeric claims resolve to typed values with source keys, fields and snapshot dates.
Mandate findings carry numeric min/max limits; currency quantities retain their
currency and scale. Numbers embedded in exact source-backed instrument names are
not reinterpreted as quantitative claims. The validator does not parse JSON text.
Unsupported quantities still produce a zero score. This is not full semantic
entailment: non-numeric assertions and changes in action intent need RM review.

Blocked drafts are separated into Needs correction, with reasons and no approval.
Saved revisions are rechecked against the current original action evidence on
ledger reads and approval. They do not waive other hard stops, and both decision
APIs reject blocked or missing validation. The ledger retains the original draft
and edit notes. Changing an action's intent requires a newly assessed action, not
merely passing the numeric check.


## Version 1.2: approval and persistence boundary

An edit cannot inherit an assessment of different wording. Only case, whitespace
and typographic dash changes preserve the original assessment. Other edits remain
saved drafts with a zero published score until the original source-backed wording
is restored or a source-backed alternative is selected. This deterministic demo
does not claim to assess arbitrary free-text intent.

Range claims require ordered min/max fields from one mandate. Movement amounts
are restricted to the named holding. Edited wording also has to match the assessed
template, so swapping a subject, currency, quantity or condition cannot reuse the
old score.

Actions have stable IDs. Evidence versions cover the controlled source contents;
requests carry both the action ID and version. Alternatives and panel results are
append-only ledger events, restored after cache rebuilds and restarts. Local mode
uses the JSON ledger in one server process. Hosted storage uses a JSONB review-event
table alongside the existing decision table; existing records are preserved.
Checks and appends are serialized using a local lock or a database transaction lock.
Legacy approvals stay in the audit trail but require fresh approval under the
versioned contract. Unmatched legacy action titles are not applied to other actions.

Completed panel scores cap the published score and the server approval gate.
A block cannot be cleared by a skipped, failed or more favourable retry on the same
version. Changed evidence requires a completed review of the new version before
approval. A missing durable ledger fails closed for evaluation and decision writes.

External judges receive only allowlisted numeric metrics and the controlled action
category. Names, IDs, free-text objectives, action wording, source references,
evidence passports and retrieval excerpts are withheld. The panel therefore checks
structured evidence only; it cannot certify the omitted wording or personal fit.
Local evidence remains visible to the RM. External providers remain opt-in.

Approval records workflow progress; it does not prove a trade, funding transfer or
risk reduction occurred. Portfolio urgency remains evidence-based and uses the
same source score in the browser and notification service. Review completion is
labelled separately from risk resolution.
