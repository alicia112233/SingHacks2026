# TESSERA — Wealth Decision Intelligence

TESSERA is a governance-first Relationship Manager copilot that detects where a client's stated intent, bank-held portfolio, future obligations, and policy constraints disagree. It uses the five dated portfolio snapshots as a timeline, grounds every 2026 event claim in `event_log.csv`, looks through structured products, rehearses transparent counterfactuals, and turns the result into a client conversation the RM can approve, edit, or reject.

The core idea is simple: **the next best conversation often hides inside a contradiction, not a performance alert**.

## Run the demo

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

The demo is intentionally dependency-light: Python, pandas, and a browser. The analytical API is recalculated from the source files on each request.

## Suggested three-minute demo

1. **Today** — show the capacity-aware decision queue across Priscilla's 20-client / 24-portfolio book.
2. **Lau Chi Ming** — show how four wrappers form a 49.0% Hong Kong property exposure, then compare the reported HKD 25.56m facility headroom with the actual HKD 0.71m lending-value buffer to the 70% margin trigger.
3. **Abdullah Al-Mansoori** — look through the FCN to reveal at least 42.1% shipping/energy exposure, despite the client's diversification objective, and rehearse the Strait-reopening case.
4. **Cheung Kwok Wing** — reframe a 66.6% bond allocation around life horizon and spending, then open the evidence passport where USD 1.10m in the RM note conflicts with USD 1.28m in the structured cash-needs record.
5. **Evidence ledger** — show that suitability, event authority, data lag, uncertainty, and RM approval are part of the product workflow rather than footnotes.

## What is implemented

- Full-book, client-level priority scoring across all 20 clients
- Five-snapshot value paths with explicit “not performance” treatment
- Cross-portfolio aggregation and structured-product look-through
- Mandate band, concentration, sustainability-exclusion, facility, liquidity, and data-quality checks
- Three deep decision rooms with evidence-backed narrative briefs
- Scenario sensitivities with visible assumptions and no fabricated probabilities
- Approve / edit interactions recorded in a local in-memory decision ledger
- Evidence passports tied to file names, record IDs, instruments, and dates
- Responsive-enough desktop UI designed for a 16:9 demo screen

## Key findings surfaced by the prototype

- **Lau Chi Ming:** 49.0% of the bank-held portfolio is tied to Hong Kong property across direct property, issuer equity, perpetual debt, and an accumulator. Facility LTV is 69.41% against a 70% trigger; the lending-value cushion to the trigger is only about HKD 0.71m.
- **Abdullah Al-Mansoori:** at least 42.1% is tied to shipping and energy after looking through the FCN, before counting his Gulf logistics business. An illustrative Strait-reopening normalization shock produces a −6.3% portfolio sensitivity.
- **Cheung Kwok Wing:** 66.6% is fixed income and 20.8% is one Treasury due 2045. His stated aversion to selling at a loss conflicts with lifetime spending needs; the annual draw also differs between the latest RM note and `planned_cash_needs.csv`.

All figures use the synthetic challenge data as of 26 August 2026. Scenario shocks are transparent sensitivities, not forecasts or investment advice.

## Architecture

```text
Bank data snapshots + RM notes
            ↓
As-of joins and data-quality gates
            ↓
Mandate / concentration / event-authority policy compiler
            ↓
Purpose-limited evidence bundle
            ↓
Deterministic narrative prototype (bank-hosted LLM in production)
            ↓
RM approve / edit / reject + audit ledger
```

The prototype does not send data to any external model. In production, the evidence bundle—not unrestricted client data—would be passed to a private, bank-hosted model with role-based access, encryption, retention controls, and full decision logging.

## Code map

- `app.py` — dependency-light local API and static-file server
- `tessera/engine.py` — joins, checks, ranking, scenarios, evidence passports, and deterministic narrative compiler
- `web/` — interactive RM workbench
- `tests/test_engine.py` — analytical and governance regression tests
- `data/` — original synthetic challenge data, unchanged

## Verify

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

## Prototype boundaries

- Value paths include trades, withdrawals, and FX; they are deliberately not presented as investment performance.
- Scenario shocks are illustrative and carry no probability.
- Outside wealth and operating businesses are qualitative unless the dataset provides a value, so look-through percentages are described as floors.
- The recommendation layer drafts options for an RM; it never places trades or presents itself as autonomous advice.

This project is an unofficial SingHacks 2026 concept built from synthetic data.
