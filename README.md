# TESSERA

TESSERA is an internal wealth-advisory workspace for Relationship Managers. It prioritises client reviews, brings the supporting evidence into one place, provides transparent portfolio sensitivities and records the RM’s decision.

The working application is in [`singhacks-jb-wealth-intelligence/`](singhacks-jb-wealth-intelligence/).

## Run the application

```bash
cd singhacks-jb-wealth-intelligence
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

## Deploy to Vercel

The application now includes Vercel Python Functions, SPA route rewrites and a
PostgreSQL-backed hosted decision ledger. Follow the project-specific
[`DEPLOYMENT.md`](singhacks-jb-wealth-intelligence/DEPLOYMENT.md). A pooled
`DATABASE_URL` is required for approve, edit, dismiss and restore actions in a
hosted environment.

## Product capabilities

- Full-book Now, Next and Watch review queue.
- Complete review rooms for every client in the current source records.
- Interactive YTD, 6M and 3M portfolio-value charts.
- Dedicated Scenario Studio with adjustable assumptions.
- Evidence passports and data-quality controls.
- Persistent approve, edit, dismiss and restore workflow.
- Append-only decision history in the Evidence Ledger.
- Direct routes that remain valid on browser refresh.

Read [`SOLUTION.md`](SOLUTION.md) for the product model and [`README_SOLUTION.md`](singhacks-jb-wealth-intelligence/README_SOLUTION.md) for implementation and rollout details.

The bundled records are controlled non-production data. They are not investment advice and are not authorised for client use.
