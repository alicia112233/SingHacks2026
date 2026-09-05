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

## 3. Deploy

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
domain. Do not run `vercel deploy --prod` until the account supports protection
for all deployments or the application has its own production identity and
authorization layer.

## 4. Verify the deployment

Replace the host below with the production domain:

```powershell
curl.exe https://your-domain.example/health
curl.exe https://your-domain.example/api/intelligence
curl.exe https://your-domain.example/api/decisions
```

The health response must report `decision_storage` as `configured`. In the UI,
open a client, dismiss an action, refresh the page, restore it, and confirm both
events appear in the Evidence Ledger.

## Production controls

The bundled records are controlled non-production data. Before connecting real
client information, add identity, per-book authorization, environment-specific
databases, retention rules, backups, monitoring, and deployment protection.
Vercel authentication alone does not implement application-level book access.
