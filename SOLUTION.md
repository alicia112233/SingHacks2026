# TESSERA product solution

TESSERA is an internal wealth-advisory workspace for Relationship Managers. It brings portfolio history, client objectives, future cash requirements, mandate controls, credit exposure and approved market events into one review process.

The product is designed around a practical operating question: which client reviews need attention today, what evidence supports that priority, and what decision did the Relationship Manager make?

## What the product delivers

- A full-book review queue with distinct **Now**, **Next** and **Watch** priorities.
- A review room for every client in the book, including portfolio history, controls, scenarios, evidence and conversation preparation.
- An interactive portfolio-value chart with YTD, 6M and 3M time frames and month/year labels.
- A dedicated Scenario Studio with client selection and adjustable, transparent stress assumptions.
- Approve, edit, dismiss and restore workflows backed by a persistent decision ledger.
- Direct, copyable routes for client reviews, Scenario Studio and the evidence ledger.
- Traceable evidence and data-quality checks that remain visible to the accountable RM.

## Operating model

```text
Bank records and approved market events
                  ↓
       Effective-date data joins
                  ↓
   Data-quality and suitability checks
                  ↓
       Prioritised RM review queue
                  ↓
   Client review and scenario analysis
                  ↓
Approve / edit / dismiss + audit record
```

Calculations and review summaries are deterministic. An optional bank-hosted language service can refine approved wording later, but it is not allowed to select source facts, bypass suitability controls or place trades.

## Run locally

```bash
cd singhacks-jb-wealth-intelligence
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`. Product and implementation details are in [`README_SOLUTION.md`](singhacks-jb-wealth-intelligence/README_SOLUTION.md).
