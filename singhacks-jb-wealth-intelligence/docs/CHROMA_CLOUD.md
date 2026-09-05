# Chroma Cloud semantic evidence

TESSERA uses Chroma only for purpose-limited retrieval of narrative evidence.
Portfolio values, risk calculations, mandate checks and hard stops remain in the
deterministic engine.

## Cost and deployment model

Chroma Cloud's Starter plan has no monthly base fee and includes initial free
credits, but it is usage-based rather than permanently unlimited-free. Configure
a usage limit in Chroma before enabling retrieval. The thin `chromadb-client`
package connects from Vercel without running a database inside the function.

Chroma Cloud currently offers US and EU database regions. This repository uses
synthetic demonstration records. Do not upload real client information until the
chosen region, vendor terms, retention, encryption and access controls have been
approved for the intended banking use case.

## 1. Create the cloud database

1. Sign in at <https://trychroma.com> and create a Starter database named
   `tessera`.
2. Select the database region deliberately. The default US endpoint is
   `api.trychroma.com`; the EU endpoint appears in the dashboard's Connect panel.
3. Create a database-scoped API key.
4. Copy `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE`, and (for a
   non-default region) `CHROMA_HOST` from the Connect panel.

## 2. Configure and seed locally

Add the credentials to `.env.local`, never to a committed file:

```text
TESSERA_RETRIEVAL_ENABLED=true
CHROMA_API_KEY=replace-me
CHROMA_TENANT=replace-me
CHROMA_DATABASE=tessera
CHROMA_HOST=api.trychroma.com
CHROMA_COLLECTION=tessera-knowledge-v1
TESSERA_EMBEDDING_MODEL=openai/text-embedding-3-small
```

The indexer also requires either `AI_GATEWAY_API_KEY` or a current
`VERCEL_OIDC_TOKEN` to generate embeddings. Then run:

```powershell
pip install -r requirements.txt
python scripts\index_chroma.py --dry-run
python scripts\index_chroma.py
```

The command upserts stable document IDs and prunes stale records. Re-run it when
the controlled RM notes, event register, mandates or instrument reference data
changes. It does not index holdings, valuations, client names or portfolio
calculations.

## 3. Configure Vercel

Add the following as encrypted variables for Production and Preview in the
Vercel project:

```text
CHROMA_API_KEY
CHROMA_TENANT
CHROMA_DATABASE
```

Add these non-secret settings:

```text
TESSERA_RETRIEVAL_ENABLED=true
CHROMA_HOST=api.trychroma.com
CHROMA_COLLECTION=tessera-knowledge-v1
TESSERA_EMBEDDING_MODEL=openai/text-embedding-3-small
```

Vercel supplies `VERCEL_OIDC_TOKEN` at runtime, so a separate AI Gateway key is
not required in production. Redeploy after changing environment variables.

## 4. Verify

`GET /health` should return `"vector_search": "configured"`. In the UI, open a
recommendation, run the model panel, and confirm that **Chroma semantic evidence**
shows `ready` with source-labelled passages. An `empty` result usually means the
indexing command has not been run. `unavailable` means the deterministic engine
continued safely while the remote dependency failed.

Retrieval always filters to the selected `client_id` plus `GLOBAL` controlled
records and excludes sources dated after the portfolio snapshot. This filter is
defence in depth, not a substitute for application identity and authorization.
