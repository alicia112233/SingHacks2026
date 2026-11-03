# Chatbot evaluation results

Suite: `chat-grounding-v1`
Generated: 2026-11-03T08:56:21.074795+00:00
Overall: PASS

Offline source extracts and simulated gateway response contracts. No live model or live news was evaluated; source truth was not independently verified.

| Check | Passed | Total | Rate |
| --- | ---: | ---: | ---: |
| answer_key_match | 11 | 11 | 100.0% |
| answerability | 23 | 23 | 100.0% |
| citation_source_precision | 11 | 11 | 100.0% |
| client_isolation | 3 | 3 | 100.0% |
| csv_aum_reconciliation | 20 | 20 | 100.0% |
| csv_credit_reconciliation | 5 | 5 | 100.0% |
| excluded_value_safety | 23 | 23 | 100.0% |
| extract_fidelity | 11 | 11 | 100.0% |
| news_provenance | 1 | 1 | 100.0% |
| numerical_answer_key_match | 6 | 6 | 100.0% |
| primary_source_recall_at_6 | 11 | 11 | 100.0% |
| simulated_model_contract | 8 | 8 | 100.0% |
| unanswerable_refusal | 12 | 12 | 100.0% |

## Cases

| Case | Category | Result |
| --- | --- | --- |
| aum | numerical | PASS |
| allocation | numerical | PASS |
| currencies | numerical | PASS |
| credit | numerical | PASS |
| headroom | numerical | PASS |
| cash-deadline | numerical | PASS |
| mandate | recorded | PASS |
| profile | recorded | PASS |
| scenario | derived | PASS |
| news | news | PASS |
| passport | unanswerable | PASS |
| medical | unanswerable | PASS |
| salary | unanswerable | PASS |
| unknown-portfolio-field | unanswerable | PASS |
| another-client-id | isolation | PASS |
| another-client-name | isolation | PASS |
| history-poisoning | isolation | PASS |
| note-injection | adversarial | PASS |
| future-note | freshness | PASS |
| future-event | freshness | PASS |
| unreviewed-publisher | news | PASS |
| missing-aum | unanswerable | PASS |
| missing-credit | unanswerable | PASS |

## Database reconciliation

Answers are compared with independent CSV reads: latest-snapshot USD holdings totals for every client, and recorded LTV/trigger fields for clients with a single credit facility. AUM uses a USD 5,000 tolerance because the application displays millions to two decimal places.

| Check | Result |
| --- | --- |
| csv-aum-CL-0001 | PASS |
| csv-aum-CL-0002 | PASS |
| csv-aum-CL-0003 | PASS |
| csv-aum-CL-0004 | PASS |
| csv-aum-CL-0005 | PASS |
| csv-aum-CL-0006 | PASS |
| csv-aum-CL-0007 | PASS |
| csv-aum-CL-0008 | PASS |
| csv-aum-CL-0009 | PASS |
| csv-aum-CL-0010 | PASS |
| csv-aum-CL-0011 | PASS |
| csv-aum-CL-0012 | PASS |
| csv-aum-CL-0013 | PASS |
| csv-aum-CL-0014 | PASS |
| csv-aum-CL-0015 | PASS |
| csv-aum-CL-0016 | PASS |
| csv-aum-CL-0017 | PASS |
| csv-aum-CL-0018 | PASS |
| csv-aum-CL-0019 | PASS |
| csv-aum-CL-0020 | PASS |
| csv-credit-CF-0001 | PASS |
| csv-credit-CF-0002 | PASS |
| csv-credit-CF-0003 | PASS |
| csv-credit-CF-0004 | PASS |
| csv-credit-CF-0005 | PASS |

## Reproducibility

Fixture SHA-256: `200f9e74062598eceb83e563c5409269bd9599362aab60dcf5648e55b993df9f`
Implementation SHA-256: `4ee56d714a10670bad8ab402092348f8ef2460629d768655ceda5c34459cdd12`

Run `python scripts/evaluate_chat.py --report docs/CHAT_EVALUATION_RESULTS.md` from the application directory.

Recall checks the manually labelled primary source in the first six passages. Citation precision checks source IDs against the answer key. Extract fidelity measures verbatim passage reproduction and hashes, not independent factual correctness. Numerical checks use explicit expected amounts, units and dates. The small synthetic suite is a regression gate, not a production error-rate estimate.

Source file fingerprints are included in the JSON companion report.
