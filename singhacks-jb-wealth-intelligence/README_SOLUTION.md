# TESSERA — Wealth Decision Intelligence

TESSERA is an internal advisory workspace that helps Relationship Managers decide which client situations need attention, prepare the supporting analysis and record the resulting decision.

It is rules-first and evidence-bound. Portfolio records, client objectives, cash needs, mandate limits, credit facilities and approved market events are joined by effective date. The resulting review points remain traceable to their source records.

## Business problem

Traditional portfolio tools report valuations, performance and allocation. The Relationship Manager still has to determine whether the portfolio fits the client’s stated objectives, upcoming obligations and policy constraints.

TESSERA adds an operational review layer:

1. Rank client reviews by objective, liquidity, governance and time pressure.
2. Show the facts behind the ranking.
3. Test transparent portfolio sensitivities.
4. Prepare reversible actions subject to suitability review.
5. Record whether the RM approved, revised, dismissed or reopened each action.

## Implemented product workflows

### Daily review queue

Every client and portfolio in the current source records is evaluated. Capacity bands separate immediate work from follow-up:

- **Now** uses red for today’s limited review capacity.
- **Next** uses amber for near-term preparation.
- **Watch** uses teal for monitored cases.

The numeric score and underlying reason remain visible. Every queue item opens a complete client review; there are no inactive client links.

### Client review room

Every client receives:

- bank-held AUM and key portfolio metrics;
- the client objective, current portfolio position and next constraint;
- an interactive value history with YTD, 6M and 3M controls;
- relevant events from the controlled register;
- two current-position scenario sensitivities;
- suitability-qualified actions and a conversation brief; and
- an evidence passport linked to source files and dates.

Each proposed action also carries a recommendation confidence score. The score
measures evidence and control support rather than expected return, is capped
while analytical validation is sensitivity-only, and never replaces RM
approval. See [`docs/RECOMMENDATION_RISK_RUBRIC.md`](docs/RECOMMENDATION_RISK_RUBRIC.md)
for weights, hard stops, confidence caps and the production model contract.

Chart labels use a consistent `Mon YYYY` format. The application-wide data date is derived from the latest holding snapshot, and each chart point can be selected with a mouse or keyboard to show its exact value and change from the previous observed snapshot.

### Scenario Studio

Scenario Studio is a dedicated route at `/scenario-studio`. It supports every client, not a preselected case only. The RM can:

- switch clients;
- compare documented downside and recovery cases;
- scale each shock from 50% to 150%;
- see factor-level and total portfolio effects update immediately; and
- move directly into the corresponding client review.

Scenarios are sensitivities, not forecasts. The screen explicitly identifies calculation scope and excluded second-order effects.

### Action decisions and audit trail

Actions can be edited, approved, dismissed or restored. Each event is posted to `/api/decisions`. The effective state is reconstructed from the latest event for each recommendation, while the complete history remains available in the Evidence Ledger.

The local server persists these events to `runtime/decisions.json`. Vercel deployments use the same API contract with the append-only PostgreSQL store configured by `DATABASE_URL`; no production decision depends on ephemeral function storage.

## Application routes

| Route | Purpose |
| --- | --- |
| `/` | Daily book review |
| `/clients/{client_id}` | Copyable client review link |
| `/scenario-studio?client={client_id}` | Scenario workspace |
| `/evidence-ledger` | Controls, data fitness and decision history |
| `/api/intelligence` | Current analytics payload; recalculated when a source file changes |
| `/api/decisions` | Decision history and effective state |
| `/api/evaluations` | On-demand deterministic, predictive-readiness and independent-judge panel |
| `/health` | Service health |

Unknown extensionless paths return the application shell so browser refreshes on client and studio routes do not fail. Missing static assets still return a genuine 404. Browser favicon requests return 204 rather than polluting service logs with a false error.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

For a hosted deployment, follow [`DEPLOYMENT.md`](DEPLOYMENT.md). The repository includes Vercel routing, Python function entry points and PostgreSQL-backed decision persistence.

## Verify

```bash
python -m unittest discover -s tests -v
node --check web/app.js
python -m json.tool vercel.json
```

The test suite covers analytical controls, full-book profile availability, decision-ledger durability, application-route fallback, health and favicon handling.

## Architecture

```text
Position, client, mandate, credit and event records
                         ↓
              Effective-date joins
                         ↓
       Data-quality and suitability controls
                         ↓
       Purpose-limited review evidence set
                         ↓
       Deterministic metrics and summaries
                         ↓
        Relationship Manager review action
                         ↓
           Append-only decision ledger
```

External model judges are disabled by default. When explicitly enabled, they receive a purpose-limited evidence packet without client name, client ID or raw RM notes. Their scores cannot override a deterministic hard stop or raise the deterministic score, and RM approval remains mandatory. A bank rollout should use approved private endpoints and its data-processing controls.

## Production integration path

The service can run locally or on Vercel. A controlled bank rollout would replace the bundled source adapters while retaining the workflow and API contracts:

- **Identity and access:** SSO, role-based book access, maker-checker controls and session policy.
- **Data:** read-only connectors to positions, mandates, CRM, credit and approved market-event systems; lineage IDs retained in every evidence record.
- **Persistence:** the hosted decision API already uses PostgreSQL; production governance still needs database migrations, versioned recommendations, retention policy and recovery procedures.
- **Processing:** scheduled book scoring plus event-driven refresh when positions, facilities or client records change.
- **Controls:** suitability rules as versioned policy, with effective dates and approval ownership.
- **Security:** encryption in transit and at rest, field-level access controls, private networking and secrets management.
- **Operations:** structured logs, metrics, alerts, health checks, backup, recovery and service-level objectives.
- **Change management:** model/rule validation, regression packs, user acceptance, compliance sign-off and phased desk rollout.

## Data scope and limitations

The bundled records are controlled non-production data. Scenario results cover current bank-held positions and direct first-order shocks. They exclude unrecorded outside wealth, tax outcomes, liquidity costs and second-order market effects unless a source record explicitly supplies them.

Portfolio value paths include market movement, trades, withdrawals and currency translation, so they are not labelled as investment performance. Conflicting records remain visible and lower confidence instead of being silently averaged.
