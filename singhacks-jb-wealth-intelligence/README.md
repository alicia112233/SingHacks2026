# TESSERA application

TESSERA turns portfolio, client, mandate, credit and market-event records into a prioritised Relationship Manager workflow. It is built to support an accountable human decision, not to place trades or obscure the source of a recommendation.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

Run this application server rather than `python -m http.server`; the latter can
serve the frontend but will return 404 for `/api/evaluations` and the other API
routes. Restart `python app.py` after pulling route changes.

To enable the optional multi-provider model panel locally, copy `.env.example`
to `.env.local`, set `TESSERA_EXTERNAL_JUDGES_ENABLED=true`, and add either a
Vercel AI Gateway key as `AI_GATEWAY_API_KEY` or a current
`VERCEL_OIDC_TOKEN`. The default panel uses OpenAI, Claude Sonnet, and Gemini;
edit the comma-separated `TESSERA_JUDGE_MODELS` value to use other supported
models such as Claude Opus.

Chroma Cloud can supplement that panel with source-labelled semantic evidence
from controlled RM notes, events, mandates and instrument references. It uses a
thin cloud client and explicit Vercel AI Gateway embeddings; exact portfolio and
suitability calculations remain deterministic. See
[`docs/CHROMA_CLOUD.md`](docs/CHROMA_CLOUD.md) for setup, indexing, cost and
deployment instructions.

The global **Ask TESSERA** assistant supports client-scoped questions with
numbered source citations, microphone dictation and browser read-aloud. It works
without cloud credentials using local factual retrieval, and can optionally
combine Chroma semantic results with model-written answers. See
[`docs/RAG_CHAT_ASSISTANT.md`](docs/RAG_CHAT_ASSISTANT.md). Its API endpoint is
`POST /api/chat`.

## Main routes

- `/` — daily book review
- `/clients/{client_id}` — client review room
- `/market-events` — all controlled and relevant live market events, with source links and calendar filters
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

## Optional live market news

Enable live RSS polling with:

```text
TESSERA_LIVE_NEWS_ENABLED=true
TESSERA_NEWS_INTERVAL_SECONDS=21600
```

The local server polls in the background every six hours, or you can call
`POST /api/market-news/refresh` manually.
Only exposure-relevant headlines pass the deterministic filter; unrelated
stories are discarded and repeated stories are deduplicated. Approved signals
are stored separately in `runtime/live_events.json` and merged into the next
intelligence calculation. Matching clients receive bounded market-event
pressure of 2, 5 or 8 points for Medium, High or Severe signals. This is a
review trigger, not an investment forecast or an automatic trade instruction.

The dashboard's latest-event panel links to `/market-events`. Relationship
Managers can filter the event register with `From` and `To` calendar fields,
clear the range, and open the original RSS source for live-news records.
Controlled CSV events remain source-labelled but do not have external links.

## Risk Analysis

The client view shows capacity, tolerance, horizon and their arithmetic average on a 1-5 scale. Lower overall means earlier attention **only within equal urgency**. Urgency values are unchanged. If any customer in an equal-urgency group has a missing dimension, the entire group's original order is preserved. Missing scores display "Insufficient data". This is a prioritisation indicator, not portfolio suitability advice.

Simple illustrative thresholds live in `tessera/risk_analysis.py` (`RiskThresholds`). Capacity averages available bank-held cash-buffer, daily-liquidity and recorded debt bands. Cash share upper bounds are 1%, 3%, 5%, 10%; daily-liquid share bounds are 20%, 40%, 60%, 80% (scores 1-5). Recorded debt uses the highest LTV/margin-call-trigger ratio: below 25%, 50%, 75%, 92%, then at least 92% (scores 5-1); 92% reuses the existing urgency warning boundary. An absent facility is omitted, never assumed to mean zero household debt. Capacity is rounded to one decimal before averaging dimensions; overall remains unrounded for tie-breaking and displays one decimal.

Existing tolerance scores 1-2, 3-4, 5-6, 7-8, 9-10 map to 1-5. Stated horizons up to 1, 3, 5, 10 and above 10 years map to 1-5; missing horizons fall back to the earliest confirmed one-off cash-need date. Stated horizons take precedence over individual goals. No inference uses age or risky holdings. Income stability, complete household liabilities, outside wealth and unencumbered cash are unavailable, so capacity is explicitly a limited bank-held estimate. It does not claim that daily-tradable assets are safe assets. No customer data is added.
