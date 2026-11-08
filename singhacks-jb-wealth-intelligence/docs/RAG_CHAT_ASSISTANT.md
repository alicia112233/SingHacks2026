# RAG evidence assistant

TESSERA's assistant is designed for internal Relationship Manager preparation.
It answers questions about one selected client at a time and returns the source
passages used for every answer. It cannot approve recommendations or place
trades.

## Retrieval design

Each request follows a constrained hybrid path:

1. The deterministic intelligence payload is converted into small factual
   chunks for profile, portfolio, currency, cash need, credit, concentration,
   position change, scenario, recommendation, RM-note and event evidence.
2. A local BM25-style retriever ranks those chunks. This path is always
   available and requires no network or model credentials.
3. When Chroma is configured, client-scoped semantic results are fetched with
   the same as-of control used by recommendation evaluation.
4. A conservative lexical relevance gate rejects unrelated evidence; reciprocal-rank
   fusion combines the remaining passages and limits the packet to six chunks.
   AUM, allocation, credit metrics and risk-profile questions use their structured
   source types, preventing an RM note or news assertion from replacing those records.
5. Liquidity summaries combine structured cash balances and dated cash needs into
   complete sentences, with a cash-versus-needs comparison when all amounts are
   available. Cash estimates use the displayed AUM and allocation, so they are
   approximate. Daily-liquid investments are distinguished from uninvested cash;
   the comparison does not establish current payment status or a funding plan.
   Other answers use source passages in separate paragraphs. The optional model
   selects up to three citation IDs using a strict JSON contract. Free-form model
   sentences never enter the answer. Invalid selections and gateway failures fall
   back to local extracts.
6. With no relevant evidence, the API returns `mode=insufficient_evidence` with no
   citations. It does not substitute a generic portfolio summary.

The client ID is validated against the current RM book before retrieval.
Semantic queries enforce `client_id = selected client OR GLOBAL` and the corpus
identifier. Returned metadata is rechecked even if a database ignores its query
filter: wrong-client rows, wrong corpora, unknown source types and client notes
incorrectly labelled GLOBAL are discarded. Undated/invalidly dated notes and
events are discarded; future-dated controlled sources are excluded in both paths.
Explicit requests for another client ID/name are refused before retrieval.

## Optional model generation

Structured liquidity summaries and source passages work without a model. To opt into model selection of those
extracts through the existing Vercel AI Gateway integration, configure:

```text
TESSERA_CHAT_ENABLED=true
TESSERA_CHAT_MODEL=openai/gpt-5.4
AI_GATEWAY_API_KEY=replace-me
```

On Vercel, `VERCEL_OIDC_TOKEN` can be used instead of `AI_GATEWAY_API_KEY`.
The model receives only the current question and selected evidence chunks.
Request history remains accepted for API compatibility but is not forwarded to
the model or used as evidence: it is client-controlled and can belong to another
client. Follow-up questions should restate their subject. The model returns
`{"citations":[1],"insufficient":false}` or an empty selection with
`insufficient=true`; extra keys, duplicate/unknown/non-integer citations and
free-form prose are rejected. The server renders the original passages and labels
recorded evidence, calculated assessments and external reports separately.

The chat displays readable paragraphs with inline citation buttons. Original
source excerpts and provenance stay in a collapsed sources section; selecting a
citation opens and focuses its source. Read-aloud reads all answer paragraphs.

This constrains unsupported generated prose; it does not establish that the
source itself is true, complete, current or applicable to the question. Relevance
is a conservative heuristic, not a semantic entailment proof. Obvious instruction
patterns in evidence are quarantined, but this is not a complete injection detector.

## External news and source reliability

Yahoo Finance, CNBC, The Business Times and Google News searches feed the news
register. Register status `approved` means relevance admission, not fact checking.
Every new capture stores the publisher, article URL, feed URL, original publication
time, first retrieval time, captured-headline SHA-256 and verification status.
Missing publication dates stay missing; they are never changed to today's date.
Repeated ingestion can enrich legacy provenance while preserving its first capture time.

Chat evidence additionally requires a valid publication date, no future publication
date and an HTTPS article/publisher domain allowed by `tessera/source_policy.py`.
Google News items require an allowed original publisher URL from the feed, not just
a trusted-looking display name. Unknown publishers remain visible in the register
but cannot be used as chatbot evidence. Legacy aggregator items without provenance
remain excluded until refreshed with that metadata. Domain admission is not
independent corroboration, publisher authentication, or full-article verification.

The chat citation retains the original URL, publisher, publication/retrieval times,
source ID, source date, evidence kind and excerpt SHA-256. The UI shows an external
report label and a safe source link. News chunks do not present keyword-derived
severity or transmission labels as statements made by the publisher. News dates
do not change the separate holdings snapshot date. Captured passages are RSS
headlines/summaries, not the complete article. The source hash detects differences
between captured texts; it does not prove authenticity or provide immutable storage.

## Conversation history

The assistant saves a separate conversation for each RM name and client ID in
browser local storage, including message text, answer labels and source citations.
Switching the client selector or opening another client review restores that
client's conversation. History also survives closing the panel and refreshing
the page in the same browser and site. It does not sync across browsers or devices.
The full transcript is retained; requests still send only the last six messages
for API compatibility, and the model does not use that history as evidence.

**Delete conversation** opens a centred TESSERA popup over a dimmed page, naming the client,
with Cancel focused by default. Cancel or Escape keeps the conversation; only
the explicit Delete conversation button removes it. Switching clients or closing
chat dismisses the confirmation. Deletion removes only the selected
client's saved browser history. It also stops audio, clears the input and cancels
any pending reply for that conversation so it cannot reappear after deletion.
Replies arriving after a client switch remain attached to their original client.
Deleting this browser history does not remove the separate server-side chat
output records described in the deployment guide.

If browser storage is unavailable or full, conversations remain available in
memory during the session and the assistant shows a storage warning. A failed
storage deletion is reported rather than claimed as a successful saved deletion.

## Audio behavior

Voice input uses the browser's Web Speech Recognition implementation. Read-aloud
uses browser speech synthesis, preferring a recognised female English voice at
1.25× speed. Available voices depend on the browser and operating system; when
no recognised female English voice is available, playback uses an available
English voice or the browser default. Voice loading is cancelled when switching
clients or closing the panel. TESSERA does not upload or persist raw audio.
Browser/platform speech services may process audio according to their own
policies, so a production bank rollout should replace this with an approved
private transcription and text-to-speech service where required.

Voice recognition support varies by browser. Text chat remains fully usable
when recognition is unavailable.

## Repeatable evaluation

From the application directory:

```powershell
python scripts/evaluate_chat.py --report docs/CHAT_EVALUATION_RESULTS.md
```

The command writes Markdown and JSON reports and exits nonzero on a failed check.
It uses no credentials, never loads `.env.local` and makes no external requests.

`evals/chat_grounding.v1.json` contains a frozen synthetic source snapshot with
24 manually labelled questions covering numeric facts, liquidity summaries, recorded facts, derived
scenarios, missing records, conflicting narrative amounts, prompt injection,
future dates, unknown publishers, poisoned history and other-client requests.
Eight simulated gateway completions exercise the real selection validator.
Independent CSV reads also reconcile answers against the latest holdings totals
for all 20 clients and recorded credit LTV/trigger values for five single-facility
clients. AUM tolerates USD 5,000 rounding because the application displays two
decimal places in millions. Other source fields are not exhaustively reconciled.

Reports separate primary-source recall at six, citation-source precision, source
excerpt integrity, extract fidelity for passage answers, paragraph citations for
structured summaries, numerical answer-key matches, answerability/refusal, client isolation,
news provenance, CSV reconciliation and simulated-model contract checks. They
include fixture, implementation and source-file fingerprints. Extract fidelity
measures faithful copying, not independent source truth. This small suite is a
regression gate, not a production hallucination-rate estimate or a live-model audit.

The `Evaluate chatbot evidence` GitHub Actions workflow runs the offline scorecard
and focused tests on app changes and uploads both report formats. It takes effect
when committed and pushed. Add reviewed cases whenever sources or models change;
use a separate held-out real-question set and authorized live-model run before
claiming model-quality rates. Assess source correctness/corrections, freshness,
conflicts, operational latency and human review separately; these are not certified
by this offline report. No model or external-source verification score is implied.
