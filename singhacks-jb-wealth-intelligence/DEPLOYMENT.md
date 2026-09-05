# Deploy TESSERA to Vercel

The repository is configured as a static frontend plus Python Vercel Functions.
The calculation inputs remain bundled read-only source records. Decision events
use PostgreSQL in hosted environments because a serverless filesystem is not a
durable ledger.

## 1. Create the Vercel project

Push the repository to a Git provider, import it in Vercel, and use these project
settings:

| Setting | Value |
| --- | --- |
| Root Directory | `singhacks-jb-wealth-intelligence` |
| Framework Preset | Other |
| Build Command | Leave empty |
| Output Directory | `web` (the Python entrypoint also serves these protected assets) |

The Python entrypoint serves the application shell, static assets and API behind
the same protection boundary. It preserves `/clients/{id}`, `/scenario-studio`,
`/evidence-ledger`, and `/health` on direct navigation and refresh.

## 2. Add durable decision storage

In the Vercel project, open **Storage**, create or connect a PostgreSQL provider,
and make its pooled connection string available as `DATABASE_URL` in Production,
Preview, and Development.

The decision function creates the append-only `tessera_decision_events` table and
its lookup index on first use. The database user therefore needs `CREATE TABLE`,
`CREATE INDEX`, `SELECT`, and `INSERT` permissions for the selected schema. For a
more restricted production role, deploy the table separately and grant the
runtime user only `SELECT` and `INSERT` afterward.

Do not put the connection string in source control. `.env` and `.env.local` are
ignored; `.env.example` contains only the variable shape.

## 3. Add optional Chroma Cloud retrieval

Follow [`docs/CHROMA_CLOUD.md`](docs/CHROMA_CLOUD.md) to create a database,
index the controlled corpus, and add the Chroma variables to Vercel. Chroma is
failure-isolated and off by default; the deterministic intelligence API remains
available when semantic retrieval is disabled or temporarily unavailable.

## 4. Deploy from `main`

For this repository, connect the Vercel project to
`alicia112233/SingHacks2026`, set **Production Branch** to `main`, and retain the
Root Directory shown above. A push to `main` then creates a production
deployment, while other branches create previews.

This repository is private and the project currently uses Vercel Hobby. On that
combination, Vercel only deploys commits whose author is the Hobby team owner.
Commits from another collaborator are marked `BLOCKED`; either have the owner
merge/re-author the production commit or move to a Pro team and add each
committer as a member.

### Manual preview deployment

### Optional independent model judges

The multi-provider judge panel is off by default. To enable it, configure these
Vercel environment variables:

```text
TESSERA_EXTERNAL_JUDGES_ENABLED=true
TESSERA_JUDGE_MODELS=openai/gpt-5.4,anthropic/claude-sonnet-4.6,google/gemini-3.7-flash
```

`TESSERA_JUDGE_MODELS` accepts up to three comma-separated AI Gateway model
IDs. You can replace Sonnet with `anthropic/claude-opus-4.6`, or configure both
Claude models if same-vendor comparison is intentional.

Use Vercel AI Gateway OIDC in the hosted function or add `AI_GATEWAY_API_KEY`.
Create a static key on the Vercel AI Gateway API Keys page; this is a gateway
key, not an OpenAI, Anthropic or Google provider key. For local `python app.py`
runs, copy `.env.example` to `.env.local`; the local server loads that file at
startup. Alternatively, `vercel env pull .env.local` supplies a short-lived
`VERCEL_OIDC_TOKEN`.
Review the configured models against the live AI Gateway model catalogue before
deployment. The evaluator sends a purpose-limited packet without client name,
client ID or raw RM notes. For real banking data, enable this only after privacy,
model-risk and vendor approvals.

From this directory:

```powershell
vercel.cmd login
vercel.cmd link
vercel.cmd env pull .env.local
vercel.cmd dev
vercel.cmd deploy --target preview
```

On Windows, `vercel.cmd` avoids PowerShell script-execution-policy errors that can
prevent `vercel.ps1` from starting. Deploy the source directory so Python binary
packages are built on Vercel's Linux runtime. Do not upload output from a local
`vercel build --prebuilt` created on Windows.

### Protected access

The project uses Vercel Authentication with Standard Protection. Use a preview
deployment URL while working with controlled records. Anonymous requests should
redirect to Vercel sign-in, and only team members or explicitly granted viewers
should receive access.

On a Hobby account, Standard Protection does not protect the canonical production
domain. The bundled records are synthetic, but real client data still requires
application identity and authorization before production use.

## 5. Verify the deployment

Replace the host below with the production domain:

```powershell
curl.exe https://your-domain.example/health
curl.exe https://your-domain.example/api/intelligence
curl.exe https://your-domain.example/api/decisions
```

The health response must report `decision_storage` as `configured`. If Chroma is
enabled, it must also report `vector_search` as `configured`. In the UI,
open a client, dismiss an action, refresh the page, restore it, and confirm both
events appear in the Evidence Ledger.

Open a recommendation confidence badge and run the model panel. Confirm that
the deterministic score always acts as a ceiling, predictive probability is
shown as unavailable until calibrated, and each configured provider returns an
independent result.

## Production controls

The bundled records are controlled non-production data. Before connecting real
client information, add identity, per-book authorization, environment-specific
databases, retention rules, backups, monitoring, and deployment protection.
Vercel authentication alone does not implement application-level book access.
