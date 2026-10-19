# TESSERA application

TESSERA turns portfolio, client, mandate, credit and market-event records into a prioritised Relationship Manager workflow. It is built to support an accountable human decision, not to place trades or obscure the source of a recommendation.

For the feature overview and repository layout, see the [project README](../README.md).

## Quick start

```bash
python -m pip install -r requirements.txt
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

Chroma Cloud retrieves source-labelled semantic evidence from controlled RM
notes, events, mandates and instrument references. Retrieved excerpts are not
sent to external judges: their packet contains only allowlisted numeric fields
and controlled categories. Retrieval can support the evidence chat assistant.
Exact portfolio and suitability calculations remain deterministic. See
[`docs/CHROMA_CLOUD.md`](docs/CHROMA_CLOUD.md) for indexing and setup.

The global **Ask TESSERA** assistant supports client-scoped questions with
numbered source citations, microphone dictation and browser read-aloud. It works
without cloud credentials using local factual retrieval, and can optionally
combine Chroma semantic results with model-written answers. See
[`docs/RAG_CHAT_ASSISTANT.md`](docs/RAG_CHAT_ASSISTANT.md). Its API endpoint is
`POST /api/chat`.

The template enables `TESSERA_RETRIEVAL_ENABLED`. Set it to `false` when
running without Chroma configuration. Core calculations and local factual chat
need no cloud credentials.

## Telegram alerts

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env.local` to enable
outbound alerts. With credentials configured, the local server starts its
monitor automatically unless `TESSERA_URGENCY_MONITOR_ENABLED=false`.
Defaults are an hourly scan, an urgency threshold of 80/100, and a 24-hour
reminder interval. Escalation and acknowledgement state are persisted.
See `.env.example` for policy settings and [deployment setup](DEPLOYMENT.md)
for hosted scheduling. Configuring credentials enables real message delivery.

## Main routes

- `/` — daily book review
- `/clients/{client_id}` — client review room
- `/market-events` — all controlled and relevant live market events, with source links, calendar filters, severity/source filters, and newest/oldest sorting
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

## Live market news

Each website load first renders the current `/api/review` response, then calls
`POST /api/market-news/refresh` in the background. This fetches Yahoo Finance, CNBC, The Business Times, and the
existing Google News RSS searches. These feeds do not need API keys. Set
`TESSERA_LIVE_NEWS_ENABLED=false` to disable live news, or set
`TESSERA_NEWS_FEEDS` to a comma-separated list of approved RSS URLs.
If the feeds are unavailable, the dashboard loads its last available intelligence.
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

The default sources are Yahoo Finance, CNBC, The Business Times, and the
existing Google News market searches. Source links open
the original article. Local approved events persist in `runtime/live_events.json`;
hosted events use temporary instance storage and are returned directly to the
loading website. Durable hosted news history requires a shared event store.

## Risk Analysis

The client view shows capacity, tolerance, horizon and their arithmetic average on a 1-5 scale. The backend uses lower overall risk as a tie-breaker **within equal urgency**. The browser then sorts by review completion, follow-up tier, deadline and urgency; this can change that backend order. Urgency values are unchanged. If any customer in an equal-urgency group has a missing dimension, the entire group's original order is preserved. Missing scores display "Insufficient data". This is a prioritisation indicator, not portfolio suitability advice.

Simple illustrative thresholds live in `tessera/risk_analysis.py` (`RiskThresholds`). Capacity averages available bank-held cash-buffer, daily-liquidity and recorded debt bands. Cash share upper bounds are 1%, 3%, 5%, 10%; daily-liquid share bounds are 20%, 40%, 60%, 80% (scores 1-5). Recorded debt uses the highest LTV/margin-call-trigger ratio: below 25%, 50%, 75%, 92%, then at least 92% (scores 5-1); 92% reuses the existing urgency warning boundary. An absent facility is omitted, never assumed to mean zero household debt. Capacity is rounded to one decimal before averaging dimensions; overall remains unrounded for tie-breaking and displays one decimal.

Existing tolerance scores 1-2, 3-4, 5-6, 7-8, 9-10 map to 1-5. Stated horizons up to 1, 3, 5, 10 and above 10 years map to 1-5; missing horizons fall back to the earliest confirmed one-off cash-need date. Stated horizons take precedence over individual goals. No inference uses age or risky holdings. Income stability, complete household liabilities, outside wealth and unencumbered cash are unavailable, so capacity is explicitly a limited bank-held estimate. It does not claim that daily-tradable assets are safe assets. No customer data is added.


### Demo boundary

TESSERA currently supports `TESSERA_MODE=demo` only (the default). Setting any
other mode rejects intelligence preparation and its dependent review operations.
This is a deployment boundary, not authentication: anyone who can reach the demo
can access its controlled sample data. Do not load real client records or expose
it as a production service. Production requires authenticated identities,
client-level authorization and a separate security review.

Review writes and model evaluations require durable decision storage. API clients
must send the recommendation's `id` as `recommendation_id` and its current `version`.
See [the risk rubric](docs/RECOMMENDATION_RISK_RUBRIC.md) for edit, panel and legacy
ledger behavior. Hosted ledger schema changes are additive; they are created on
first use by the existing schema setup path.


### Reliability checks

Run `python -m unittest discover -s tests -q` from the application directory.
Notification lifecycle and concurrency tests are included in standard discovery;
they use mocked delivery. Browser logic checks use the existing Node runtime.

News refresh and notification delivery have separate results. A notification
failure returns `urgency_alerts.status = "unavailable"` without discarding refreshed
intelligence. The browser loads actions and decisions together from `/api/review`
and ignores superseded responses. Automatic HTTP retries apply only to reads.

Follow-up deadlines retain their hour and Singapore timezone. They are derived
from the controlled snapshot date, not a newly agreed client appointment; an old
snapshot can therefore show an overdue follow-up. The countdown uses the current
clock and refreshes every minute.

Alert storage lives in `tessera/alert_store.py`; lifecycle and delivery rules live
in `tessera/notifications.py`. Scans and acknowledgements serialize updates per
local store or per client in Postgres. This prevents concurrent duplicate sends,
but cannot guarantee exactly-once delivery if Telegram accepts a message and the
process or database fails before the state is saved. Local JSON storage remains
intended for a single server process; live Postgres delivery needs deployment QA.
