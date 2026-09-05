# TESSERA — three-minute pitch + live demo

The timed pitch ends on slide 6. Slides A1-A3 are Q&A backups only. Target pace: calm, 125-135 words per minute. Do not rush the Abdullah demo.

## 0:00-0:14 — Slide 1: The portfolio report is not the story

“Twenty clients, twenty-four portfolios, and more evidence than one Relationship Manager can review before markets open. A portfolio report can be perfectly accurate and still miss the conversation that matters. TESSERA finds that conversation.”

**Delivery:** Pause after “perfectly accurate.” Point once to the live product screenshot.

## 0:14-0:38 — Slide 2: The unique advantage

“TESSERA is not another market-alert copilot. First, it ranks contradictions between client intent and portfolio reality. Second, it looks through wrappers, collateral and outside-business context to reconnect fragmented risk. Third, it grounds every statement in controlled, source-labelled evidence. We calculate first, retrieve only relevant context, generate last—and the RM decides.”

**Emphasise:** The moat is the governed decision workflow, not a chat interface.

## 0:38-1:00 — Slide 3: The RM-controlled intelligence loop

“The core facts and suitability checks remain deterministic. We have also implemented an optional Chroma retrieval layer and prepared 154 controlled passages from notes, events, mandates and instruments. Retrieval is client-scoped, date-guarded and feature-gated until credentials and data-residency approval are in place. It can improve recall; it cannot rewrite the facts or override a hard stop.”

## 1:00-1:24 — Slide 4: Why Abdullah

“Abdullah asked us to diversify away from Gulf shipping. Yet after looking through his structured product, at least 42.1% of his bank-held portfolio is linked to shipping and energy—and his operating business shares the same conditions. He also needs five million US dollars for a Singapore family office, against 2.4 million in cash. His recent gains make this contradiction easy to miss.”

## 1:24-2:24 — Live demo: turn evidence into an RM decision

Open: `https://singhacks-jb-wealth-intelligence.vercel.app/clients/CL-0019`

1. **Review queue:** Open Abdullah from the ranked book. Say: “This is ranked by decision gap, not by yesterday’s price move.”
2. **Decision room:** Point to **Client says / Portfolio does / Upcoming constraint**. Say: “This is the contradiction in one screen.”
3. **Scenario:** Toggle **Strait reopens** and **Blockade worsens**. Say: “These are transparent sensitivities, not forecasts and not probabilities.”
4. **Evidence passport:** Open the supporting evidence. Point out the FCN look-through, source record and as-of date. If semantic evidence is disabled, say: “The deterministic evidence path remains fully available; Chroma is an optional recall layer.”
5. **RM action:** End on: “Ring-fence the seed capital and map the 2.6-million-dollar cash gap.” Approve or edit the action to show that the RM—not the model—owns the decision.

**If the demo fails:** Stay on slide 4. Explain the 42.1% look-through and the two scenario bars, then say: “The failure changes the interface, not the evidence chain.” Move directly to slide 5.

## 2:24-2:45 — Slide 5: What is live, and what full scale requires

“This is live on Vercel, not mocked in slides: eleven datasets, the full client book, 154 prepared passages, an append-only decision path and 38 passing tests. At bank scale, we replace file adapters with read-only bank connectors, add SSO and book-level entitlements, version policy as code, refresh on events, and continuously monitor traceability, overrides and drift.”

## 2:45-3:00 — Slide 6: Close and ask

“TESSERA makes the portfolio defensible, the future discussable and the RM indispensable. Our ask is a 30-day shadow pilot with one desk and real RM decisions. We measure time saved, traceability and override quality—then scale only what the evidence supports.”

Stop. Make eye contact. Invite questions.

## Likely Q&A

### What is genuinely unique?

Most copilots begin with a prompt. TESSERA begins with a governed decision gap: client intent × look-through risk × future needs × policy. Deterministic calculations establish the facts; scoped retrieval adds relevant institutional context; every output carries an evidence passport and remains subject to RM approval.

### Why Chroma?

It provides lightweight semantic retrieval for notes, controlled events, mandate rules and instrument references. The production contract is strict: client or GLOBAL metadata scope, portfolio as-of filtering, source labels, explicit embeddings and graceful fallback. Chroma is supplementary memory—not the calculation engine or source of truth.

### Is Chroma active in production?

The integration and 154-document corpus are implemented and tested. Production retrieval remains deliberately disabled until Chroma credentials, region choice and data-governance approval are configured. The deterministic workflow continues normally when retrieval is unavailable.

### Can this operate inside a bank?

The full-scale design adds private networking, SSO/RBAC, book-level entitlements, encrypted secrets, read-only source connectors, maker-checker policy approval, immutable lineage, retention controls, observability and model-risk evaluation. Real client data should not enter the current US/EU Chroma Cloud setup without data-residency and compliance approval; a bank-controlled deployment remains an option.

### How would you roll it out?

1. **Shadow mode:** Compare TESSERA’s review queue with real RM decisions; no client-facing output.
2. **Assisted workflow:** Let RMs use evidence passports, scenarios and editable conversation briefs.
3. **Approved automation:** Automate only validated low-risk steps after compliance, security and model-risk sign-off.

### What would you measure?

- Time from book open to first high-value client review.
- Percentage of recommendations with complete, current evidence lineage.
- RM approve/edit/reject rates and the reasons for overrides.
- False-negative reviews discovered by RMs.
- Data conflicts surfaced before client contact.
- Retrieval relevance, fallback rate, latency and cost.
- Downstream client engagement and action completion—without treating short-term returns as proof of recommendation quality.

### Why Lau?

Four wrappers create 49.0% property exposure; HKD 60 million is due; and the apparent HKD 25.56 million lending headroom becomes only HKD 0.71 million of cushion to the 70% trigger.

### Why Cheung?

Conflicting USD 1.10 million and USD 1.28 million draw records reduce confidence and become the first client question. TESSERA refuses to fabricate a convenient answer.

## Before hand-in

- Rehearse once with a visible three-minute timer.
- Confirm the live Abdullah URL and `/health` endpoint on the presentation network.
- Grant judges repository access, or replace the repository field with a public review URL.
- Supply the required real team photograph and member names. The improved deck currently uses that panel for the pilot scorecard because no verified team image was available.
