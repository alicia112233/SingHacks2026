const state = {
  data: null,
  currentClient: "CL-0012",
  currentScenario: 0,
  decisionLog: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function titleCaseDate(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", timeZone: "UTC",
  }).toUpperCase();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2300);
}

function showView(name, clientId) {
  $$(".view").forEach((view) => { view.hidden = true; });
  $$(".nav-item").forEach((item) => item.classList.remove("active"));
  if (name === "book") {
    $("#book-view").hidden = false;
    $("#page-title").textContent = "Today’s decision brief";
    $('.nav-item[data-view="book"]').classList.add("active");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (name === "client") {
    state.currentClient = clientId || state.currentClient;
    state.currentScenario = 0;
    renderClient(state.currentClient);
    $("#client-view").hidden = false;
    $("#page-title").textContent = "Client decision room";
    $('.nav-item[data-view="client"]').classList.add("active");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else {
    $("#governance-view").hidden = false;
    $("#page-title").textContent = "Evidence & governance";
    $('.nav-item[data-view="governance"]').classList.add("active");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function openModal(html) {
  $("#modal-content").innerHTML = html;
  $("#modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeModal() {
  $("#modal").hidden = true;
  document.body.style.overflow = "";
}

function renderBook() {
  const { book, market_signal: signal, featured_clients: featured } = state.data;
  const queue = book.priority_queue.slice(0, 7);
  $("#book-view").innerHTML = `
    <div class="hero-grid">
      <article class="hero-panel">
        <span class="section-kicker">MORNING SIGNAL ROOM</span>
        <h1>${book.conversations_now} client stories contain a decision gap worth opening now.</h1>
        <p>TESSERA ranks contradictions—not volatility—so performance noise does not outrank a life goal, a liquidity deadline, or a governance constraint.</p>
        <div class="hero-stats">
          <div><strong>${book.client_count}</strong><small>clients monitored</small></div>
          <div><strong>$${book.aum_usd_m}m</strong><small>book AUM</small></div>
          <div><strong>${book.portfolio_count}</strong><small>portfolios joined</small></div>
          <div><strong>${book.stale_valuations}</strong><small>lagged marks surfaced</small></div>
        </div>
      </article>
      <aside class="signal-panel">
        <div class="signal-header"><span class="section-kicker">AUTHORITATIVE EVENT</span><span class="severity">${esc(signal.severity)}</span></div>
        <h2>${esc(signal.description)}</h2>
        <p><strong>Transmission:</strong> ${esc(signal.transmission)}</p>
        <span class="source-line">${esc(signal.source)}</span>
      </aside>
    </div>

    <div class="section-head">
      <div><span class="section-kicker">DECISION QUEUE</span><h2>Call order is explainable, not mysterious.</h2></div>
      <p>Score = goal tension + liquidity pressure + mandate / credit pressure + time. Open a deep decision room where available.</p>
    </div>
    <div class="queue">
      <div class="queue-head"><span>Score</span><span>Client</span><span>Why now</span><span>Next RM move</span><span></span></div>
      ${queue.map((item) => `
        <div class="queue-row">
          <div class="score-ring" style="--score:${item.score}"><b>${item.score}</b></div>
          <div class="client-cell"><strong>${esc(item.client_name)}</strong><span>${esc(item.client_id)} · ${esc(item.booking_centre)} · $${item.aum_usd_m}m</span></div>
          <div class="cell-copy"><strong>${esc(item.tension)}</strong><span>${esc(item.evidence)}${item.ltv ? ` · ${esc(item.ltv)}` : ""}</span></div>
          <div class="cell-copy"><span class="priority-chip">${esc(item.priority)}</span><span>${esc(item.next_step)}</span></div>
          <button class="open-client" data-open-client="${esc(item.client_id)}" aria-label="Open ${esc(item.client_name)}">↗</button>
        </div>`).join("")}
    </div>

    <div class="section-head">
      <div><span class="section-kicker">DEEP DEMO</span><h2>Three clients, three kinds of contradiction.</h2></div>
      <p>Each room moves from what happened → what could happen → what the RM should consider saying or doing next.</p>
    </div>
    <div class="featured-grid">
      ${Object.values(featured).map((client) => `
        <button class="featured-card" data-open-client="${esc(client.client_id)}">
          <small>${esc(client.client_id)} · ${esc(client.risk_profile)}</small>
          <h3>${esc(client.name)}</h3>
          <p>${esc(client.tension.portfolio_does)} ${esc(client.tension.future_demands)}</p>
          <b>↗</b>
        </button>`).join("")}
    </div>
  `;
}

function pathChart(points) {
  const w = 700, h = 130, padX = 28, padY = 24;
  const values = points.map((p) => p.aum_usd_m);
  const min = Math.min(...values), max = Math.max(...values);
  const spread = Math.max(max - min, max * 0.04);
  const coords = points.map((p, i) => ({
    x: padX + (i * (w - padX * 2) / (points.length - 1)),
    y: padY + ((max - p.aum_usd_m) / spread) * (h - padY * 2),
    ...p,
  }));
  const line = coords.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
  const area = `${line} L${coords.at(-1).x},${h} L${coords[0].x},${h} Z`;
  return `
    <div class="path-chart">
      <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Portfolio value path">
        <defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#2d5c56" stop-opacity=".18"/><stop offset="1" stop-color="#2d5c56" stop-opacity="0"/></linearGradient></defs>
        <path d="${area}" fill="url(#area)"/><path d="${line}" fill="none" stroke="#2d5c56" stroke-width="2.5"/>
        ${coords.map((p) => `<circle cx="${p.x}" cy="${p.y}" r="5" fill="#f4f0e7" stroke="#b78f50" stroke-width="3"/><text x="${p.x}" y="${p.y - 14}" text-anchor="middle" fill="#17201e" font-size="10" font-weight="700">$${p.aum_usd_m.toFixed(1)}m</text>`).join("")}
      </svg>
      <div class="path-labels">${points.map((p) => `<span>${titleCaseDate(p.date).replace(" 2026", "").replace(" 2025", "")}</span>`).join("")}</div>
    </div>`;
}

function scenarioHTML(client, index) {
  const scenario = client.scenarios[index];
  const impact = scenario.portfolio_impact_pct;
  const positive = impact > 0;
  const maxImpact = Math.max(0.01, ...scenario.factors.map((f) => Math.abs(f.impact_usd_m ?? f.shock_pct ?? 0)));
  return `
    <div class="scenario-lead">
      <div><h4>${esc(scenario.name)}</h4><p>${esc(scenario.description)}</p></div>
      <div class="impact-number ${positive ? "positive" : ""}"><strong>${impact > 0 ? "+" : ""}${impact}%</strong><small>${scenario.portfolio_impact_usd_m == null ? "LENDING VALUE TO TRIGGER" : `${scenario.portfolio_impact_usd_m > 0 ? "+" : ""}$${scenario.portfolio_impact_usd_m}m ILLUSTRATIVE`}</small></div>
    </div>
    <div class="factor-bars">
      ${scenario.factors.map((factor) => {
        const measure = factor.impact_usd_m ?? factor.shock_pct;
        const width = Math.max(8, Math.abs(measure) / maxImpact * 100);
        return `<div class="factor-row"><span>${esc(factor.factor)}</span><div class="bar-track"><div class="bar-fill ${measure > 0 ? "positive" : ""}" style="width:${width}%"></div></div><b>${factor.impact_usd_m == null ? `${factor.shock_pct}%` : `${factor.impact_usd_m > 0 ? "+" : ""}$${factor.impact_usd_m}m`}</b></div>`;
      }).join("")}
    </div>`;
}

function renderClient(clientId) {
  const client = state.data.featured_clients[clientId];
  if (!client) {
    const card = state.data.book.priority_queue.find((item) => item.client_id === clientId);
    showToast(`${card.client_name}: ranked evidence available; deep demo is configured for three featured clients.`);
    return;
  }
  state.currentClient = clientId;
  $("#client-view").innerHTML = `
    <div class="client-hero">
      <div>
        <button class="back-link" data-back-book>← Back to decision queue</button>
        <h1>${esc(client.name)}</h1>
        <p>${esc(client.life_stage)} · ${esc(client.source_of_wealth)}</p>
      </div>
      <div>
        <div class="profile-tags"><span>${esc(client.risk_profile)}</span><span>${esc(client.reporting_language)}</span><span>${esc(client.booking_centre)}</span></div>
        <div class="client-aum"><strong>$${client.aum_usd_m}m</strong><small>CURRENT BANK-HELD AUM</small></div>
      </div>
    </div>
    <div class="metric-rail">${client.headline_metrics.map((m) => `<div><strong>${esc(m.value)}</strong><span>${esc(m.label)}</span></div>`).join("")}</div>
    <div class="tension-map">
      <div class="tension-item"><small>CLIENT SAYS</small><p>${esc(client.tension.client_says)}</p></div>
      <div class="tension-item"><small>PORTFOLIO DOES</small><p>${esc(client.tension.portfolio_does)}</p></div>
      <div class="tension-item"><small>FUTURE DEMANDS</small><p>${esc(client.tension.future_demands)}</p></div>
    </div>

    <div class="analysis-grid">
      <section class="panel">
        <div class="panel-title"><h3>What changed through time</h3><small>FIVE OBSERVED SNAPSHOTS · USD CONVERTED</small></div>
        ${pathChart(client.snapshot_path)}
        <p class="chart-note">* Value path is not performance: it includes market movement, trades, withdrawals and FX translation. Position deltas are used as investigation leads, not attribution claims.</p>
      </section>
      <aside class="panel">
        <div class="panel-title"><h3>Controlled event trail</h3><small>EVENT_LOG.CSV ONLY</small></div>
        <div class="events-list">${client.linked_events.slice(-3).map((event) => `<div class="event-item"><small>${titleCaseDate(event.date)} · ${esc(event.severity)}</small><p>${esc(event.description)}</p><span>${esc(event.transmission)}</span></div>`).join("")}</div>
      </aside>
    </div>

    <section class="panel scenario-panel">
      <aside class="scenario-sidebar">
        <span class="section-kicker">WHAT COULD HAPPEN</span>
        <h3>Counterfactual studio</h3>
        ${client.scenarios.map((scenario, index) => `<button class="scenario-selector ${index === state.currentScenario ? "active" : ""}" data-scenario="${index}">${esc(scenario.name)}</button>`).join("")}
      </aside>
      <div class="scenario-output" id="scenario-output">${scenarioHTML(client, state.currentScenario)}</div>
    </section>

    <div class="decision-grid">
      <section class="panel">
        <div class="panel-title"><h3>Actions worth considering</h3><small>DRAFT · RM DECIDES</small></div>
        ${client.recommendations.map((rec, index) => `<article class="recommendation"><h4>${index + 1}. ${esc(rec.title)}</h4><p>${esc(rec.detail)}</p><footer><span class="suitability">${esc(rec.suitability)}</span><div><button class="action-button" data-decision="Edit" data-index="${index}">Edit</button> <button class="action-button approve" data-decision="Approve" data-index="${index}">Approve</button></div></footer></article>`).join("")}
      </section>
      <aside class="panel conversation-card">
        <div class="panel-title"><h3>Conversation brief</h3><small>${esc(client.confidence.level)}</small></div>
        <div class="talk-line"><small>OPEN WITH</small><p>${esc(client.conversation.open)}</p></div>
        <div class="talk-line"><small>SHOW</small><p>${esc(client.conversation.show)}</p></div>
        <div class="talk-line"><small>ASK</small><p>${esc(client.conversation.ask)}</p></div>
        <div class="talk-line"><small>AVOID</small><p>${esc(client.conversation.avoid)}</p></div>
        <button class="evidence-button" data-evidence>Open evidence passport →</button>
      </aside>
    </div>`;
}

function renderGovernance() {
  const { governance, data_quality: quality } = state.data;
  const nodes = [
    ["01", "Bank records", "Five snapshots, portfolios, facilities, needs and RM notes"],
    ["02", "Temporal joins", "As-of-safe views; stale marks carried visibly"],
    ["03", "Policy compiler", "Mandates, exclusions, concentration and event authority"],
    ["04", "Evidence bundle", "Minimum rows needed for one defensible claim"],
    ["05", "Private model", "Narrative and scenario explanation inside bank boundary"],
    ["06", "RM decision", "Approve, edit, reject and rationale in the ledger"],
  ];
  $("#governance-view").innerHTML = `
    <section class="governance-hero"><span class="section-kicker">TRUST BY CONSTRUCTION</span><h1>The model may write the sentence. It cannot choose its own facts.</h1><p>TESSERA compiles a purpose-limited evidence bundle before generation, treats the event log as authoritative, runs suitability checks first, and preserves the RM as the accountable decision-maker.</p></section>
    <section class="architecture"><div class="panel-title"><h3>Deployable bank architecture</h3><small>ZERO PUBLIC-LLM DATA EGRESS</small></div><div class="architecture-flow">${nodes.map((n) => `<div class="architecture-node"><b>${n[0]}</b><strong>${n[1]}</strong><span>${n[2]}</span></div>`).join("")}</div></section>
    <div class="governance-grid">
      <section class="panel"><div class="panel-title"><h3>Five non-negotiables</h3><small>${esc(governance.recommendation_state)}</small></div><div class="principle-list">${governance.principles.map((p, i) => `<div class="principle-item"><b>${i + 1}</b><p>${esc(p)}</p></div>`).join("")}</div></section>
      <section class="panel"><div class="panel-title"><h3>Data fitness before advice</h3><small>${esc(quality.overall)}</small></div><div class="quality-list">${quality.checks.map((q) => `<div class="quality-item"><div><strong>${esc(q.name)}</strong><span>${esc(q.evidence)}</span></div><b class="quality-status ${esc(q.status)}">${esc(q.status)}</b></div>`).join("")}</div></section>
    </div>`;
}

function showEvidence(client) {
  openModal(`<span class="section-kicker">EVIDENCE PASSPORT</span><h2>${esc(client.name)}</h2><p>${esc(client.confidence.reason)} Every row below travels with the draft and remains inspectable during approval.</p>${client.evidence_passport.map((item) => `<div class="passport-row"><header><strong>${esc(item.claim)}</strong><b>${esc(item.status)}</b></header><p>${esc(item.source)}</p></div>`).join("")}`);
}

function showMethod() {
  openModal(`<span class="section-kicker">GENERATION METHOD</span><h2>Evidence first. Language second.</h2><p>This prototype uses deterministic rules so the hackathon output is fully reproducible. In deployment, only the bounded evidence bundle would be sent to a bank-hosted model.</p><div class="method-steps"><div class="method-step"><b>01 · JOIN AS OF TIME</b><p>Five dated holding snapshots are never collapsed into one static portfolio.</p></div><div class="method-step"><b>02 · DETECT A DECISION GAP</b><p>Client goals, notes, holdings, look-through references, cash needs, mandates and facilities are compared.</p></div><div class="method-step"><b>03 · APPLY GOVERNANCE</b><p>Authoritative event sourcing, mandate checks, lag flags and confidence downgrades happen before narrative.</p></div><div class="method-step"><b>04 · GENERATE A DRAFT</b><p>The output is a conversation and reversible options, not an autonomous trade instruction.</p></div><div class="method-step"><b>05 · RECORD THE HUMAN DECISION</b><p>The RM approves, edits or rejects; the evidence and rationale remain attached.</p></div></div>`);
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const nav = event.target.closest("[data-view]");
    if (nav) showView(nav.dataset.view, nav.dataset.client);
    const open = event.target.closest("[data-open-client]");
    if (open) showView("client", open.dataset.openClient);
    if (event.target.closest("[data-back-book]")) showView("book");
    const scenario = event.target.closest("[data-scenario]");
    if (scenario) {
      state.currentScenario = Number(scenario.dataset.scenario);
      $$(".scenario-selector").forEach((button, index) => button.classList.toggle("active", index === state.currentScenario));
      $("#scenario-output").innerHTML = scenarioHTML(state.data.featured_clients[state.currentClient], state.currentScenario);
    }
    const decision = event.target.closest("[data-decision]");
    if (decision) {
      const client = state.data.featured_clients[state.currentClient];
      const record = { client: client.client_id, action: decision.dataset.decision, recommendation: Number(decision.dataset.index), at: new Date().toISOString() };
      state.decisionLog.push(record);
      showToast(`${record.action} recorded in the evidence ledger (demo state).`);
    }
    if (event.target.closest("[data-evidence]")) showEvidence(state.data.featured_clients[state.currentClient]);
    if (event.target.closest("[data-close-modal]")) closeModal();
  });
  $("#method-button").addEventListener("click", showMethod);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModal(); });
}

async function init() {
  try {
    const response = await fetch("/api/intelligence");
    if (!response.ok) throw new Error(`API ${response.status}`);
    state.data = await response.json();
    $("#as-of").textContent = titleCaseDate(state.data.meta.as_of);
    $("#now-count").textContent = state.data.book.conversations_now;
    renderBook();
    renderGovernance();
    bindEvents();
    $("#loading").remove();
    $("#app").hidden = false;
    const params = new URLSearchParams(window.location.search);
    const requestedClient = params.get("client");
    const requestedView = params.get("view");
    if (requestedClient) showView("client", requestedClient);
    else if (requestedView === "governance") showView("governance");
  } catch (error) {
    $("#loading").innerHTML = `<p>Could not load the evidence bundle: ${esc(error.message)}</p>`;
  }
}

init();
