# Cloud backend status

Verified on 3 November 2026 (Singapore).

## Live deployment

- Application: https://singhacks-jb-wealth-intelligence.vercel.app
- Vercel project: `singhacks-jb-wealth-intelligence`, team `alicia112233s-projects`.
- Deployment: `dpl_6EnjXTRxuch7iZio6HViVwYdE5WJ`, production, READY.
- The initial manual deployment used the working tree based on `6aa38d6`.
  Source, tests and deployment documentation are versioned together; cloud
  credentials are configured separately in Vercel environment settings.
- The staged production build was checked before assigning the live domain.

## Durable cloud data

The existing Neon PostgreSQL database now contains:

| Data | Verified state |
| --- | --- |
| Decision and review ledger | 29 records: 2 existing cloud records plus 27 imported local records |
| Shared live-news register | 133 events |
| Controlled source and generated files | 19 files, each verified by SHA-256 readback |
| Analytical output | Current complete intelligence and review snapshots |
| Hosted chat output | Actual staged API response read back and compared with PostgreSQL |
| Alert state | Durable PostgreSQL table ready; no Telegram credentials configured |

`tessera_backend_outputs` holds server-only files, snapshots and chat responses.
Decision events remain in the existing append-only ledger tables. The importer
preserved IDs, evidence versions and timestamps; a second import created zero
duplicate decisions. Source files remain bundled in the cloud deployment and
also have database copies.

News reads use the shared database on each worker. A temporary JSON mirror is
only used by the calculation engine. Local `.env.local` now selects
`TESSERA_STORAGE_BACKEND=postgresql`, effective after restarting the local server
with the project dependencies installed.

## Semantic evidence retrieval

All 154 controlled evidence documents were indexed into the existing Chroma
Cloud collection `tessera-knowledge-v1`; none were deleted. Exact document
readback matched all 154 source documents, and a scoped semantic query returned
six results.

The user explicitly approved copying the four existing local connection settings
into this Vercel project. `AI_GATEWAY_API_KEY`, `CHROMA_API_KEY`, `CHROMA_TENANT`
and `CHROMA_DATABASE` are now Secret variables scoped to Production and Preview.
The collection, host, embedding model and retrieval-enabled setting are configured
for both environments. No credential values were displayed or committed. The new
production build passed hosted checks and was promoted. Source-grounded extractive
answers remain enabled; the optional model-generation flag was not changed.

## Verification

- Full regression suite before pushing the source: 164 tests passed.
- After the local cloud-storage wiring: all 20 application/API tests passed.
- Cloud-output tests: all 8 passed, including cold-worker reloads, cache
  invalidation, merged news, chat persistence and unavailable-storage health.
- Python compilation and browser JavaScript syntax checks passed.
- Live `/health`: HTTP 200, `backend_output_storage=available`,
  `market_news_storage=postgresql`, `decision_storage=configured`,
  `vector_search=configured`.
- Hosted `/api/chat`: semantic retrieval ready, hybrid retrieval used, six
  semantic passages retrieved and three source citations returned. The actual
  response was read back from PostgreSQL; all 29 decision records were retained.
- Live `/api/review`: HTTP 200, 20 clients and 29 ledger records.
- Vercel's runtime-log connector did not return usable logs; no claim is made
  about a complete runtime error-log scan.

For future imports and report exports, see [deployment setup](../DEPLOYMENT.md).
`python scripts/sync_cloud_outputs.py --inventory` refreshes the local metadata
inventory without downloading file contents.
