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
