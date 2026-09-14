# RAG evidence assistant

TESSERA's assistant is designed for internal Relationship Manager preparation.
It answers questions about one selected client at a time and returns the source
passages used for every answer. It cannot approve recommendations or place
trades.

## Retrieval design

Each request follows a resilient hybrid path:

1. The deterministic intelligence payload is converted into small factual
   chunks for profile, portfolio, currency, cash need, credit, concentration,
   position change, scenario, recommendation, RM-note and event evidence.
2. A local BM25-style retriever ranks those chunks. This path is always
   available and requires no network or model credentials.
3. When Chroma is configured, client-scoped semantic results are fetched with
   the same as-of control used by recommendation evaluation.
4. Reciprocal-rank fusion combines local and semantic results, de-duplicates
   exact source passages and limits the generation packet to six chunks.
5. The answer and its numbered sources are returned together. If model
   generation is unavailable or produces invalid citations, the API falls back
   to an extractive, cited answer.

The client ID is validated against the current RM book before retrieval.
Semantic queries enforce `client_id = selected client OR GLOBAL` and the corpus
identifier. Future-dated notes and events are excluded from semantic results.

## Optional model generation

Source-grounded extractive answers are enabled by default. To opt into concise
model-written answers through Vercel AI Gateway, configure:

```text
TESSERA_CHAT_ENABLED=true
TESSERA_CHAT_MODEL=openai/gpt-5.4
AI_GATEWAY_API_KEY=replace-me
```

On Vercel, `VERCEL_OIDC_TOKEN` can be used instead of `AI_GATEWAY_API_KEY`.
The model receives only the selected evidence chunks and the last six short
conversation messages. Instructions require factual citations, treat retrieved
text as untrusted data, prohibit return forecasts and trade recommendations,
and preserve RM approval and suitability controls.

## Audio behavior

Voice input uses the browser's Web Speech Recognition implementation. Read-aloud
uses browser speech synthesis. TESSERA does not upload or persist raw audio.
Browser/platform speech services may process audio according to their own
policies, so a production bank rollout should replace this with an approved
private transcription and text-to-speech service where required.

Voice recognition support varies by browser. Text chat remains fully usable
when recognition is unavailable.

## Evaluation recommendations

Before production use, create a versioned question set containing answerable,
unanswerable, adversarial and cross-client-leakage cases. Track retrieval recall
at K, citation precision, groundedness, refusal accuracy and latency separately.
Do not use answer style or a single aggregate score as a substitute for these
controls.
