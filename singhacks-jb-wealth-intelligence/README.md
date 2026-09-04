# TESSERA application

TESSERA turns portfolio, client, mandate, credit and market-event records into a prioritised Relationship Manager workflow. It is built to support an accountable human decision, not to place trades or obscure the source of a recommendation.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

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
