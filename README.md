# TESSERA

**Know what needs attention. See the evidence. Decide what comes next.**

TESSERA helps wealth-management Relationship Managers prepare for client reviews. It brings client needs, portfolio exposure, market events and supporting records into one workspace, with a prioritised queue and an accountable decision history.

A client may have an upcoming cash need, limited liquid assets and a portfolio exception to resolve. TESSERA brings those signals together: inspect the funding position, examine the relevant constraint, explore a scenario and review the proposed follow-up. Each action has its own evidence and assessment, so the RM can see what supports it and what still needs checking.

Built for SingHacks using controlled, non-production records. The application supports human review and does not place trades.

## Walk through a client review

| Step | What you do | What TESSERA provides |
| --- | --- | --- |
| Prioritise | Open the daily book review | Now, Next and Watch queues with urgency drivers |
| Investigate | Open a client review room | Portfolio history, cash needs, mandate exceptions and source evidence |
| Explore | Adjust assumptions in Scenario Studio | Transparent portfolio sensitivities |
| Evaluate | Inspect an action's risk rubric | Dimension scores, evidence, confidence caps and blockers |
| Decide | Approve, edit, dismiss or restore | Version checks, approval gates and an append-only decision history |
| Follow up | Review outstanding urgency | Optional Telegram alerts, reminders and escalation |

The **Ask TESSERA** assistant answers client-scoped questions with source citations. Local factual retrieval works without cloud credentials; semantic retrieval and model-written answers are optional. Dictation and read-aloud depend on browser support.

The **Market Events** register brings controlled events and exposure-relevant RSS headlines together, with source links and date filters. A relevant headline can trigger a review; it is not an instruction to trade.

## What the scores mean

Three measures answer different questions:

| Measure | Question it supports |
| --- | --- |
| Client urgency, out of 100 | Which client review needs attention first? |
| Recommendation confidence, out of 100 | How well is this particular action supported? |
| Client risk indicators, on a 1-5 scale | What do the available records say about capacity, tolerance and horizon? |

These are not probabilities of a positive return. Recommendation assessments use each action's evidence and constraints; equal scores remain possible. The current analytical layer uses illustrative sensitivities rather than calibrated forecasts, so recommendation confidence is capped at 84/100.

## Run locally

From the repository root, with Python available:

```powershell
cd singhacks-jb-wealth-intelligence
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000**. On macOS or Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

Use the application server, not a static file server: review actions need its API. Restart after backend changes. Append `--port 8000` to use another port.

The core demo needs no cloud credentials. Live RSS news is enabled by default and needs network access. For optional integrations, copy `.env.example` to `.env.local` inside the application directory. Never commit credentials. The template enables Chroma retrieval; set `TESSERA_RETRIEVAL_ENABLED=false` if you are not configuring Chroma.

## How review controls work

Deterministic code calculates portfolio measures, validates evidence and applies approval gates. Optional external model judges can challenge or lower an assessment, but cannot override a hard stop or raise the deterministic score. Their restricted evidence packet excludes client names and raw notes; they cannot validate withheld narrative.

Recommendation IDs and evidence versions reject stale decisions. Material edits require reassessment, and saved model-panel restrictions survive reloads. Approving an action records a decision; it does not automatically reduce evidence-based urgency.

See the [Recommendation Risk Rubric](singhacks-jb-wealth-intelligence/docs/RECOMMENDATION_RISK_RUBRIC.md).

## Development

The browser interface uses HTML, CSS and JavaScript. Python handles analysis and review services, with pandas for tabular data, a local HTTP server for development and Flask for the hosted API. Hosted ledgers use PostgreSQL; Chroma is an optional semantic retrieval integration. Dependencies are listed in the application's `requirements.txt`.

### Project structure

Application paths are under `singhacks-jb-wealth-intelligence/`.

| Path | Purpose |
| --- | --- |
| `app.py` | Local HTTP server and optional alert monitor |
| `api/index.py` | Hosted Flask API |
| `web/` | Browser interface and styles |
| `tessera/` | Analysis, evidence validation, review state, storage and integrations |
| `data/` | Controlled source records |
| `runtime/` | Local generated state and ledgers |
| `tests/` | Regression tests |
| `docs/` | Rubric and integration guides |

### Verification

From the application directory, using the environment with dependencies installed:

```powershell
python -m unittest discover -s tests -v
node --check web/app.js
```

Node is needed for the JavaScript syntax check. Notification tests use mocked delivery. Tests do not establish live Telegram delivery, external-model behaviour or hosted PostgreSQL correctness; those need separate deployment checks.

## Hosting and limitations

Vercel hosting uses the Python API and PostgreSQL-backed ledgers. Hosted review writes require `DATABASE_URL`; local JSON storage is intended for one server process. See [deployment setup](singhacks-jb-wealth-intelligence/DEPLOYMENT.md).

Only `TESSERA_MODE=demo` is supported. Other modes reject intelligence preparation and dependent review operations. This is not authentication: anyone who can reach the demo can access its sample data. Real client use requires authenticated identities, client-level authorisation and a separate security review.

Follow-up deadlines come from the controlled snapshot and may already be overdue. Hosted news history needs a shared store to be durable. Alert locking prevents concurrent duplicate sends, but a crash after Telegram accepts a message and before state is saved can still cause a repeat.

## Documentation

- [Application setup and operating notes](singhacks-jb-wealth-intelligence/README.md)
- [Product model](SOLUTION.md)
- [Architecture and workflow](singhacks-jb-wealth-intelligence/README_SOLUTION.md)
- [Recommendation Risk Rubric](singhacks-jb-wealth-intelligence/docs/RECOMMENDATION_RISK_RUBRIC.md)
- [Evidence chat assistant](singhacks-jb-wealth-intelligence/docs/RAG_CHAT_ASSISTANT.md)
- [Chroma Cloud setup](singhacks-jb-wealth-intelligence/docs/CHROMA_CLOUD.md)
