# TESSERA application

TESSERA turns portfolio, client, mandate, credit and market-event records into a prioritised Relationship Manager workflow. It is built to support an accountable human decision, not to place trades or obscure the source of a recommendation.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

Run this application server rather than `python -m http.server`; the latter can
serve the frontend but will return 404 for `/api/evaluations` and the other API
routes. Restart `python app.py` after pulling route changes.

To enable the optional multi-provider model panel locally, copy `.env.example`
to `.env.local`, set `TESSERA_EXTERNAL_JUDGES_ENABLED=true`, and add either a
Vercel AI Gateway key as `AI_GATEWAY_API_KEY` or a current
`VERCEL_OIDC_TOKEN`. The default panel uses OpenAI, Claude Sonnet, and Gemini;
edit the comma-separated `TESSERA_JUDGE_MODELS` value to use other supported
models such as Claude Opus.

## Main routes

- `/` — daily book review
- `/clients/{client_id}` — client review room
- `/scenario-studio` — adjustable portfolio scenarios
- `/evidence-ledger` — controls, data fitness and decision history
- `/health` — service health

## Verification

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

See [`README_SOLUTION.md`](README_SOLUTION.md) for the product workflow, architecture, API behavior, control model and production integration path.

The bundled records are controlled non-production data. They are not investment advice and are not authorised for client use.

## Risk Analysis

The client view shows capacity, tolerance, horizon and their arithmetic average on a 1-5 scale. Lower overall means earlier attention **only within equal urgency**. Urgency values are unchanged. If any customer in an equal-urgency group has a missing dimension, the entire group's original order is preserved. Missing scores display "Insufficient data". This is a prioritisation indicator, not portfolio suitability advice.

Simple illustrative thresholds live in `tessera/risk_analysis.py` (`RiskThresholds`). Capacity averages available bank-held cash-buffer, daily-liquidity and recorded debt bands. Cash share upper bounds are 1%, 3%, 5%, 10%; daily-liquid share bounds are 20%, 40%, 60%, 80% (scores 1-5). Recorded debt uses the highest LTV/margin-call-trigger ratio: below 25%, 50%, 75%, 92%, then at least 92% (scores 5-1); 92% reuses the existing urgency warning boundary. An absent facility is omitted, never assumed to mean zero household debt. Capacity is rounded to one decimal before averaging dimensions; overall remains unrounded for tie-breaking and displays one decimal.

Existing tolerance scores 1-2, 3-4, 5-6, 7-8, 9-10 map to 1-5. Stated horizons up to 1, 3, 5, 10 and above 10 years map to 1-5; missing horizons fall back to the earliest confirmed one-off cash-need date. Stated horizons take precedence over individual goals. No inference uses age or risky holdings. Income stability, complete household liabilities, outside wealth and unencumbered cash are unavailable, so capacity is explicitly a limited bank-held estimate. It does not claim that daily-tradable assets are safe assets. No customer data is added.
