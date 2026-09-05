const state = {
  data: null,
  decisions: { records: [], effective: {} },
  currentView: "book",
  currentClient: null,
  currentScenario: 0,
  studioClient: null,
  studioScenario: 0,
  studioScale: 100,
  chartRange: "YTD",
  dismissedListOpen: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function fullDate(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", timeZone: "UTC",
  }).toUpperCase();
}

function monthYear(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    month: "short", year: "numeric", timeZone: "UTC",
  });
}

function recordedDate(iso) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function profiles() {
  return state.data.client_profiles || state.data.featured_clients;
}

function showToast(message, tone = "default") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
}

function routeFor(name, clientId) {
  if (name === "client") return `/clients/${encodeURIComponent(clientId)}`;
  if (name === "scenario") return `/scenario-studio?client=${encodeURIComponent(clientId || state.studioClient)}`;
  if (name === "governance") return "/evidence-ledger";
  return "/";
}

function initials(name) {
  return String(name || "RM").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function showView(name, clientId, updateHistory = true) {
  const availableViews = ["book", "client", "scenario", "governance"];
  const nextView = availableViews.includes(name) ? name : "book";
  $$(".view").forEach((view) => { view.hidden = true; });
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === nextView));

  if (nextView === "client") {
    state.currentClient = profiles()[clientId] ? clientId : state.currentClient;
    state.currentScenario = 0;
    renderClient(state.currentClient);
    $("#client-view").hidden = false;
    $("#page-title").textContent = "Client review";
  } else if (nextView === "scenario") {
    state.studioClient = profiles()[clientId] ? clientId : state.studioClient;
    state.studioScenario = 0;
    state.studioScale = 100;
    renderScenarioStudio();
    $("#scenario-view").hidden = false;
    $("#page-title").textContent = "Scenario studio";
  } else if (nextView === "governance") {
    renderGovernance();
    $("#governance-view").hidden = false;
    $("#page-title").textContent = "Evidence & governance";
  } else {
    renderBook();
    $("#book-view").hidden = false;
    $("#page-title").textContent = "Today’s review queue";
  }

  state.currentView = nextView;
  if (updateHistory) history.pushState({ view: nextView, clientId }, "", routeFor(nextView, clientId));
 // Update scroll handling here:
  if (nextView === "client") {
    state.lastScrollY = window.scrollY; // Save position before switching
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (nextView === "book" && state.lastScrollY !== undefined) {
    window.scrollTo({ top: state.lastScrollY, behavior: "instant" }); // Restore position
  } else {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function applyRoute() {
  const path = window.location.pathname;
  const params = new URLSearchParams(window.location.search);
  if (path.startsWith("/clients/")) {
    showView("client", decodeURIComponent(path.split("/").filter(Boolean)[1] || ""), false);
  } else if (path === "/scenario-studio") {
    showView("scenario", params.get("client") || state.studioClient, false);
  } else if (path === "/evidence-ledger") {
    showView("governance", null, false);
  } else {
    showView("book", null, false);
  }
}

function openModal(html, variant = "default") {
  state.modalReturnFocus = document.activeElement;
  $("#modal-content").innerHTML = html;
  $("#modal").dataset.variant = variant;
  const title = $("#modal-content h2");
  if (title) title.id = "modal-title";
  $("#modal").hidden = false;
  document.body.style.overflow = "hidden";
  window.setTimeout(() => ($("#modal-content input, #modal-content textarea") || $(".modal-close"))?.focus(), 0);
}

function closeModal() {
  if ($("#modal").hidden) return;
  $("#modal").hidden = true;
  delete $("#modal").dataset.variant;
  document.body.style.overflow = "";
  state.modalReturnFocus?.focus?.();
  state.modalReturnFocus = null;
}

function isClientReviewComplete(clientId) {
  const client = profiles()[clientId];
  if (!client?.recommendations?.length) return false;
  return client.recommendations.every((_, index) => {
    const action = decisionFor(clientId, index)?.action;
    return action === "approved" || action === "dismissed";
  });
}

function conversationsRequiringAttention() {
  return state.data.book.priority_queue.filter(
    (item) => item.priority === "Now" && !isClientReviewComplete(item.client_id),
  ).length;
}

function updateTodayCount() {
  $("#now-count").textContent = conversationsRequiringAttention();
}

function followUpLabel(item) {
  if (item.complete) return "No action required";
  if (item.priority === "Now") return "Immediate";
  if (item.priority === "Next") return "In next 2 days";
  return item.priority;
}

function renderBook() {
  const { book, market_signal: signal, featured_clients: featured } = state.data;
  const queue = book.priority_queue.slice(0, 7).map((item) => ({
    ...item,
    complete: isClientReviewComplete(item.client_id),
  })).sort((left, right) => Number(left.complete) - Number(right.complete));
  const attentionCount = conversationsRequiringAttention();
  updateTodayCount();
  $("#book-view").innerHTML = `
    <div class="hero-grid">
      <article class="hero-panel">
        <span class="section-kicker">DAILY BOOK REVIEW</span>
        <h1>${attentionCount} client review${attentionCount === 1 ? "" : "s"} require RM attention today.</h1>
        <p>Priorities combine client objectives, liquidity timing, mandate limits, credit exposure and record quality. Every score can be traced to its source records.</p>
        <div class="hero-stats">
          <div><strong>${book.client_count}</strong><small>clients monitored</small></div>
          <div><strong>$${book.aum_usd_m}m</strong><small>book AUM</small></div>
          <div><strong>${book.portfolio_count}</strong><small>portfolios reviewed</small></div>
          <div><strong>${book.stale_valuations}</strong><small>lagged marks flagged</small></div>
        </div>
      </article>
      <aside class="signal-panel">
        <div class="signal-header"><span class="section-kicker">LATEST MARKET EVENT</span><span class="severity">${esc(signal.severity)}</span></div>
        <h2>${esc(signal.description)}</h2>
        <p><strong>Portfolio channel:</strong> ${esc(signal.transmission)}</p>
        <span class="source-line">Controlled event register · ${fullDate(signal.date)}</span>
      </aside>
    </div>

    <div class="section-head">
      <div><span class="section-kicker">REVIEW QUEUE</span><h2>Prioritised client follow-up</h2></div>
      <p>Immediate items require today’s attention; items due in the next 2 days should be prepared once the immediate queue is cleared.</p>
    </div>
    <div class="queue">
      <div class="queue-head"><span>Score</span><span>Client</span><span>Reason for review</span><span>RM follow-up</span><span></span></div>
      ${queue.map((item) => `
        <a class="queue-row priority-${item.priority.toLowerCase()}" href="${routeFor("client", item.client_id)}" data-open-client="${esc(item.client_id)}" aria-label="Open client review for ${esc(item.client_name)}">
          <div class="score-ring" style="--score:${item.score}"><b>${item.score}</b></div>
          <div class="client-cell"><strong>${esc(item.client_name)}</strong><span>${esc(item.client_id)} · ${esc(item.booking_centre)} · $${item.aum_usd_m}m</span></div>
          <div class="cell-copy"><strong>${esc(item.tension)}</strong><span>${esc(item.evidence)}${item.ltv ? ` · ${esc(item.ltv)}` : ""}</span></div>
    <div class="cell-copy"><span class="priority-chip ${item.complete ? "done" : item.priority.toLowerCase()}">${esc(followUpLabel(item))}</span><span>${esc(item.complete ? "All actions recorded" : item.next_step)}</span></div>
          <span class="queue-row-arrow" aria-hidden="true">↗</span>
        </a>`).join("")}
    </div>

    <div class="section-head">
      <div><span class="section-kicker">PRIORITY CASES</span><h2>Reviews needing deeper preparation</h2></div>
      <p>Each case brings portfolio history, scenario sensitivities, suitability controls and an accountable decision record into one workflow.</p>
    </div>
    <div class="featured-grid">
      ${Object.values(featured).map((client) => `
        <button class="featured-card" data-open-client="${esc(client.client_id)}">
          <small>${esc(client.client_id)} · ${esc(client.risk_profile)}</small>
          <h3>${esc(client.name)}</h3>
          <p>${esc(client.tension.portfolio_does)} ${esc(client.tension.future_demands)}</p>
          <b>↗</b>
        </button>`).join("")}
    </div>`;
}

function rangePoints(points, range) {
  if (range === "3M") return points.slice(-2);
  if (range === "6M") return points.slice(-4);
  return points;
}

function pathChart(client, range = state.chartRange) {
  const points = rangePoints(client.snapshot_path, range);
  const w = 700, h = 150, padX = 48, padTop = 24, padBottom = 30;
  const values = points.map((point) => point.aum_usd_m);
  const min = Math.min(...values), max = Math.max(...values);
  const spread = Math.max(max - min, max * 0.04);
  const graphHeight = h - padTop - padBottom;
  const coords = points.map((point, index) => ({
    x: padX + (index * (w - padX * 2) / Math.max(points.length - 1, 1)),
    y: padTop + ((max - point.aum_usd_m) / spread) * graphHeight,
    change: index ? point.aum_usd_m - points[index - 1].aum_usd_m : 0,
    ...point,
  }));
  const line = coords.map((point, index) => `${index ? "L" : "M"}${point.x},${point.y}`).join(" ");
  const area = `${line} L${coords.at(-1).x},${h - padBottom + 5} L${coords[0].x},${h - padBottom + 5} Z`;
  const latest = coords.at(-1);
  const gradientId = `area-${client.client_id}`;
  return `
    <div class="chart-toolbar" aria-label="Chart time frame">
      <span>Time frame</span>
      <div class="segmented-control">${["YTD", "6M", "3M"].map((value) => `<button class="${value === range ? "active" : ""}" data-chart-range="${value}" aria-pressed="${value === range}">${value}</button>`).join("")}</div>
    </div>
    <div class="path-chart">
      <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Portfolio value history for ${esc(client.name)}">
        <defs><linearGradient id="${gradientId}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#2d5c56" stop-opacity=".2"/><stop offset="1" stop-color="#2d5c56" stop-opacity="0"/></linearGradient></defs>
        <line x1="${padX}" y1="${padTop}" x2="${w - padX}" y2="${padTop}" class="chart-grid"/>
        <line x1="${padX}" y1="${h - padBottom}" x2="${w - padX}" y2="${h - padBottom}" class="chart-grid"/>
        <path d="${area}" fill="url(#${gradientId})"/><path d="${line}" class="chart-line"/>
        ${coords.map((point, index) => `<g class="chart-point ${index === coords.length - 1 ? "selected" : ""}" tabindex="0" role="button" data-chart-point data-date="${esc(point.date)}" data-value="${point.aum_usd_m}" data-change="${point.change.toFixed(2)}" aria-label="${monthYear(point.date)}, portfolio value $${point.aum_usd_m.toFixed(2)} million"><circle class="chart-hit" cx="${point.x}" cy="${point.y}" r="14"/><circle class="chart-dot" cx="${point.x}" cy="${point.y}" r="5"/><text x="${point.x}" y="${point.y - 14}" text-anchor="middle">$${point.aum_usd_m.toFixed(1)}m</text></g>`).join("")}
      </svg>
      <div class="path-labels" style="--points:${points.length}">${points.map((point) => `<span>${monthYear(point.date)}</span>`).join("")}</div>
    </div>
    <div class="chart-readout" aria-live="polite"><strong>${monthYear(latest.date)} · $${latest.aum_usd_m.toFixed(2)}m</strong><span>${latest.change === 0 ? "Starting snapshot" : `${latest.change > 0 ? "+" : ""}$${latest.change.toFixed(2)}m from previous snapshot`}</span></div>`;
}

function scaled(value, scale) {
  return value == null ? null : Math.round(value * scale) / 100;
}

function scenarioHTML(client, index, scale = 100, adjustable = false) {
  const scenario = client.scenarios[index];
  const impact = scaled(scenario.portfolio_impact_pct, scale);
  const impactUsd = scaled(scenario.portfolio_impact_usd_m, scale);
  const positive = impact > 0;
  const measures = scenario.factors.map((factor) => scaled(factor.impact_usd_m ?? factor.shock_pct, scale));
  const maxImpact = Math.max(0.01, ...measures.map((value) => Math.abs(value || 0)));
  return `
    ${adjustable ? `<div class="scenario-scale"><div><strong>Assumption scale</strong><span>Apply ${scale}% of the documented shock</span></div><input type="range" min="50" max="150" step="25" value="${scale}" data-scenario-scale aria-label="Assumption scale"/><output>${scale}%</output></div>` : ""}
    <div class="scenario-lead">
      <div><h4>${esc(scenario.name)}</h4><p>${esc(scenario.description)}</p></div>
      <div class="impact-number ${positive ? "positive" : ""}"><strong>${impact > 0 ? "+" : ""}${impact.toFixed(1)}%</strong><small>${impactUsd == null ? "LENDING VALUE TO TRIGGER" : `${impactUsd > 0 ? "+" : ""}$${impactUsd.toFixed(2)}m PORTFOLIO IMPACT`}</small></div>
    </div>
    <div class="factor-bars">
      ${scenario.factors.map((factor, factorIndex) => {
        const measure = measures[factorIndex];
        const width = Math.max(8, Math.abs(measure || 0) / maxImpact * 100);
        const shock = scaled(factor.shock_pct, scale);
        return `<div class="factor-row"><span>${esc(factor.factor)}</span><div class="bar-track"><div class="bar-fill ${measure > 0 ? "positive" : ""}" style="width:${width}%"></div></div><b>${factor.impact_usd_m == null ? `${shock.toFixed(1)}%` : `${measure > 0 ? "+" : ""}$${measure.toFixed(2)}m`}</b></div>`;
      }).join("")}
    </div>`;
}

function decisionFor(clientId, index) {
  return state.decisions.effective[`${clientId}:${index}`] || null;
}

function recommendationHTML(client, recommendation, index) {
  const decision = decisionFor(client.client_id, index);
  const detail = decision?.action === "edited" && decision.note ? decision.note : recommendation.detail;
  const status = decision?.action || "pending";
  const validation = recommendation.risk_validation;
  const approvalBlocked = validation && (validation.band === "Blocked" || validation.blockers?.length);
  return `<article class="recommendation" data-recommendation="${index}">
    <header><h4>${index + 1}. ${esc(recommendation.title)}</h4><div class="recommendation-badges">${validation ? `<button class="confidence-chip ${validation.band.toLowerCase().replaceAll(" ", "-")}" data-risk-index="${index}" aria-label="Open confidence rubric for ${esc(recommendation.title)}"><b>${validation.score}</b><span>${esc(validation.band)}</span></button>` : ""}${status !== "pending" ? `<span class="decision-status ${status}">${esc(status)}</span>` : ""}</div></header>
    <p>${esc(detail)}</p>
    ${recommendationRationaleHTML(recommendation)}
    <footer><span class="suitability">${esc(recommendation.suitability)}</span><div class="recommendation-actions">
      <button class="action-button" data-decision="edit" data-index="${index}">Edit</button>
      ${status === "approved" ? `<button class="action-button" data-decision="pending" data-index="${index}">Reopen</button>` : approvalBlocked ? `<span class="action-tooltip" data-tooltip="Resolve hard-stop controls before approval" tabindex="0"><button class="action-button" disabled aria-label="Approval blocked">Blocked</button></span>` : `<button class="action-button approve" data-decision="approved" data-index="${index}">Approve</button>`}
      <button class="action-button dismiss" data-decision="dismissed" data-index="${index}">Dismiss</button>
    </div></footer>
  </article>`;
}

function recommendationRationaleHTML(recommendation) {
  const rationale = recommendation.decision_rationale;
  if (!rationale) return "";
  const evidence = rationale.supporting_evidence || [];
  const checks = rationale.rm_checks || [];
  return `<details class="action-rationale">
    <summary><span>Why this action</span><small>View rationale and evidence</small></summary>
    <div class="rationale-body">
      <p class="rationale-summary">${esc(rationale.summary)}</p>
      <div class="rationale-section"><strong>Trigger</strong><p>${esc(rationale.trigger)}</p></div>
      ${evidence.length ? `<div class="rationale-section"><strong>Evidence used</strong><div class="rationale-evidence">${evidence.map((item) => `<div><span>${esc(item.claim)}</span><small>${esc(item.source)} · ${esc(item.status)}</small></div>`).join("")}</div></div>` : ""}
      ${checks.length ? `<div class="rationale-section"><strong>RM checks before action</strong><ul>${checks.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>` : ""}
      <p class="rationale-method">${esc(rationale.method)}</p>
    </div>
  </details>`;
}

function recommendationsHTML(client) {
  const active = [], dismissed = [];
  client.recommendations.forEach((recommendation, index) => {
    const entry = { recommendation, index };
    if (decisionFor(client.client_id, index)?.action === "dismissed") dismissed.push(entry);
    else active.push(entry);
  });
  const dismissedOpen = state.dismissedListOpen && dismissed.length > 0;
  state.dismissedListOpen = false;
  return `${active.length ? active.map(({ recommendation, index }) => recommendationHTML(client, recommendation, index)).join("") : `<div class="empty-state"><strong>No actions in the active list</strong><span>Restore a dismissed action below or return to the review queue.</span></div>`}
    ${dismissed.length ? `<details class="dismissed-list"${dismissedOpen ? " open" : ""}><summary>${dismissed.length} dismissed action${dismissed.length > 1 ? "s" : ""}</summary>${dismissed.map(({ recommendation, index }) => `<div class="dismissed-row"><div><strong>${esc(recommendation.title)}</strong><span>${esc(decisionFor(client.client_id, index)?.note || "Dismissed from the active review")}</span></div><button class="action-button" data-decision="pending" data-index="${index}">Restore</button></div>`).join("")}</details>` : ""}`;
}

function riskAnalysisHTML(risk = {}) {
  risk = risk || {};
  const score = value => typeof value === "number" && Number.isFinite(value) ? `${Number(value.toFixed(1))}/5` : "Insufficient data";
  return `<section class="panel risk-analysis">
    <div class="panel-title"><h3>Risk Appetite</h3></div>
    <div class="risk-analysis-scores">${["capacity", "tolerance", "horizon", "overall"].map(key => `<div><span>${key[0].toUpperCase() + key.slice(1)}:</span> <strong>${score(risk[key])}</strong></div>`).join("")}</div>
    <p>${esc(risk.explanation || "Insufficient data. Risk analysis is unavailable in the current customer record.")}</p>
  </section>`;
}

function renderClient(clientId) {
  const client = profiles()[clientId];
  if (!client) return;
  state.currentClient = clientId;
  $("#client-view").innerHTML = `
    <div class="client-hero">
      <div><button class="back-link" data-back-book>← Back to review queue</button><h1>${esc(client.name)}</h1><p>${esc(client.life_stage)} · ${esc(client.source_of_wealth)}</p></div>
      <div><div class="profile-tags"><span>${esc(client.risk_profile)}</span><span>${esc(client.reporting_language)}</span><span>${esc(client.booking_centre)}</span></div><div class="client-aum"><strong>$${client.aum_usd_m}m</strong><small>CURRENT BANK-HELD AUM</small></div></div>
    </div>
    <div class="metric-rail">${client.headline_metrics.map((metric) => `<div><strong>${esc(metric.value)}</strong><span>${esc(metric.label)}</span></div>`).join("")}</div>
    ${riskAnalysisHTML(client.risk_analysis)}
    <div class="tension-map">
      <div class="tension-item"><small>CLIENT POSITION</small><p>${esc(client.tension.client_says)}</p></div>
      <div class="tension-item"><small>PORTFOLIO POSITION</small><p>${esc(client.tension.portfolio_does)}</p></div>
      <div class="tension-item"><small>UPCOMING CONSTRAINT</small><p>${esc(client.tension.future_demands)}</p></div>
    </div>

    <div class="analysis-grid">
      <section class="panel">
        <div class="panel-title"><h3>Portfolio value history</h3><small>OBSERVED SNAPSHOTS · USD CONVERTED</small></div>
        <div id="chart-panel-body">${pathChart(client)}</div>
        <p class="chart-note">Value includes market movement, transactions, withdrawals and currency translation. Select a point for the exact snapshot value and period change.</p>
      </section>
      <aside class="panel">
        <div class="panel-title"><h3>Relevant market events</h3><small>CONTROLLED EVENT REGISTER</small></div>
        <div class="events-list">${client.linked_events.length ? client.linked_events.slice(-3).map((event) => `<div class="event-item"><small>${fullDate(event.date)} · ${esc(event.severity)}</small><p>${esc(event.description)}</p><span>${esc(event.transmission)}</span></div>`).join("") : `<div class="empty-state"><strong>No directly linked events</strong><span>The review is based on portfolio, mandate and client records.</span></div>`}</div>
      </aside>
    </div>

    <section class="panel scenario-panel">
      <aside class="scenario-sidebar"><span class="section-kicker">SCENARIO ANALYSIS</span><h3>Test the portfolio</h3>${client.scenarios.map((scenario, index) => `<button class="scenario-selector ${index === state.currentScenario ? "active" : ""}" data-client-scenario="${index}">${esc(scenario.name)}</button>`).join("")}<button class="scenario-studio-link" data-open-studio="${esc(client.client_id)}">Open full scenario studio →</button></aside>
      <div class="scenario-output" id="client-scenario-output">${scenarioHTML(client, state.currentScenario)}</div>
    </section>

    <div class="decision-grid">
      <section class="panel"><div class="panel-title"><h3>Actions worth considering</h3><small>RM REVIEW REQUIRED</small></div><div id="recommendations-list">${recommendationsHTML(client)}</div></section>
      <aside class="panel conversation-card"><div class="panel-title"><h3>Conversation brief</h3><small>${esc(client.confidence.level)}</small></div><div class="talk-line"><small>OPEN WITH</small><p>${esc(client.conversation.open)}</p></div><div class="talk-line"><small>SHOW</small><p>${esc(client.conversation.show)}</p></div><div class="talk-line"><small>ASK</small><p>${esc(client.conversation.ask)}</p></div><div class="talk-line"><small>AVOID</small><p>${esc(client.conversation.avoid)}</p></div><button class="evidence-button" data-evidence>Open evidence passport →</button></aside>
    </div>`;
}

function renderScenarioStudio() {
  const allProfiles = profiles();
  const client = allProfiles[state.studioClient] || Object.values(allProfiles)[0];
  state.studioClient = client.client_id;
  state.studioScenario = Math.min(state.studioScenario, client.scenarios.length - 1);
  $("#scenario-view").innerHTML = `
    <section class="studio-hero">
      <div><span class="section-kicker">PORTFOLIO SENSITIVITY</span><h1>Scenario studio</h1><p>Adjust documented market shocks and review their direct effect on current bank-held positions. Results are sensitivities, not forecasts.</p></div>
      <label class="client-select"><span>Client</span><select data-studio-client>${Object.values(allProfiles).map((profile) => `<option value="${esc(profile.client_id)}" ${profile.client_id === client.client_id ? "selected" : ""}>${esc(profile.name)} · ${esc(profile.client_id)}</option>`).join("")}</select></label>
    </section>
    <div class="studio-grid">
      <aside class="studio-cases"><span class="section-kicker">SCENARIOS</span>${client.scenarios.map((scenario, index) => `<button class="studio-case ${index === state.studioScenario ? "active" : ""}" data-studio-scenario="${index}"><strong>${esc(scenario.name)}</strong><span>${scenario.portfolio_impact_pct > 0 ? "+" : ""}${scenario.portfolio_impact_pct.toFixed(1)}% at 100%</span></button>`).join("")}<button class="small-button open-room" data-open-client="${esc(client.client_id)}">Open client review</button></aside>
      <section class="panel studio-output"><div class="panel-title"><h3>${esc(client.name)}</h3><small>$${client.aum_usd_m}m CURRENT AUM</small></div><div id="studio-scenario-output">${scenarioHTML(client, state.studioScenario, state.studioScale, true)}</div><div class="scenario-footnote"><strong>Calculation scope</strong><span>Current positions only. Outside assets, tax, liquidity and second-order effects require separate review.</span></div></section>
    </div>`;
}

function renderDecisionLedger() {
  const records = [...state.decisions.records].reverse().slice(0, 12);
  if (!records.length) return `<div class="empty-state ledger-empty"><strong>No decisions recorded</strong><span>Approvals, edits and dismissals from client reviews will appear here.</span></div>`;
  return `<div class="ledger-list">${records.map((record) => `<article class="ledger-row"><span class="decision-status ${esc(record.action)}">${esc(record.action)}</span><div><strong>${esc(record.recommendation_title)}</strong><p>${esc(record.client_name)} · ${esc(record.actor)} · ${recordedDate(record.recorded_at)}</p>${record.note ? `<small>${esc(record.note)}</small>` : ""}</div></article>`).join("")}</div>`;
}

function renderGovernance() {
  const { governance, data_quality: quality } = state.data;
  const rubric = governance.confidence_rubric;
  const nodes = [
    ["01", "Bank records", "Dated positions, portfolios, facilities, needs and RM notes"],
    ["02", "Temporal joins", "As-of views preserve valuation dates and surface stale marks"],
    ["03", "Deterministic gate", "Mandates, exclusions, concentration and source integrity"],
    ["04", "Three data lenses", "Customer, product and signal evidence stay separately visible"],
    ["05", "Independent panel", "Predictive readiness and opt-in judges from different providers"],
    ["06", "RM decision", "Action taken is required before approval and retained in the ledger"],
  ];
  $("#governance-view").innerHTML = `
    <section class="governance-hero"><span class="section-kicker">CONTROLLED BY DESIGN</span><h1>Every review point has an owner, a source and a recorded outcome.</h1><p>TESSERA separates deterministic controls, predictive probability readiness and independent model opinions. Relationship Managers remain accountable for the action taken and the rationale behind it.</p></section>
    <section class="architecture"><div class="panel-title"><h3>Operating architecture</h3><small>EXTERNAL JUDGES ARE PURPOSE-LIMITED AND OPT-IN</small></div><div class="architecture-flow">${nodes.map((node) => `<div class="architecture-node"><b>${node[0]}</b><strong>${node[1]}</strong><span>${node[2]}</span></div>`).join("")}</div></section>
    <div class="governance-grid"><section class="panel"><div class="panel-title"><h3>Control framework</h3><small>${esc(governance.recommendation_state)}</small></div><div class="principle-list">${governance.principles.map((principle, index) => `<div class="principle-item"><b>${index + 1}</b><p>${esc(principle)}</p></div>`).join("")}</div></section><section class="panel"><div class="panel-title"><h3>Data fitness before advice</h3><small>${esc(quality.overall)}</small></div><div class="quality-list">${quality.checks.map((item) => `<div class="quality-item"><div><strong>${esc(item.name)}</strong><span>${esc(item.evidence)}</span></div><b class="quality-status ${esc(item.status)}">${esc(item.status)}</b></div>`).join("")}</div></section></div>
    ${rubric ? `<section class="panel confidence-rubric"><div class="panel-title"><div><h3>Recommendation confidence rubric</h3><p>${esc(rubric.meaning)}</p></div><small>VERSION ${esc(rubric.version)} · ${esc(rubric.calibration)}</small></div><div class="rubric-layout"><div class="rubric-weights">${rubric.weights.map((item) => `<div><span>${esc(item.name)}</span><b>${item.weight} pts</b></div>`).join("")}</div><div class="rubric-bands">${rubric.bands.map((item) => `<div><b>${esc(item.range)}</b><strong>${esc(item.label)}</strong><span>${esc(item.action)}</span></div>`).join("")}</div></div></section>` : ""}
    <section class="panel decision-ledger"><div class="panel-title"><h3>Decision ledger</h3><small>${state.decisions.records.length} RECORDED EVENT${state.decisions.records.length === 1 ? "" : "S"}</small></div>${renderDecisionLedger()}</section>`;
}

function showEvidence(client) {
  openModal(`<span class="section-kicker">EVIDENCE PASSPORT</span><h2>${esc(client.name)}</h2><p>${esc(client.confidence.reason)} Each review point remains linked to the record used to support it.</p>${client.evidence_passport.map((item) => `<div class="passport-row"><header><strong>${esc(item.claim)}</strong><b>${esc(item.status)}</b></header><p>${esc(item.source)}</p></div>`).join("")}`);
}

function showRiskValidation(client, index) {
  const recommendation = client.recommendations[index];
  const validation = recommendation.risk_validation;
  if (!validation) return;
  openModal(`<span class="section-kicker">RECOMMENDATION RISK RUBRIC</span><h2>${esc(recommendation.title)}</h2><div class="validation-summary"><strong>${validation.score}/100</strong><div><b>${esc(validation.band)}</b><span>${esc(validation.disposition)}</span></div></div><p>${esc(validation.score_meaning)} Residual hallucination risk: ${esc(validation.residual_hallucination_risk)}.</p><div class="validation-layers"><div><small>DETERMINISTIC VALIDATION</small><b>${esc(validation.model_validation.status)}</b><span>${esc(validation.model_validation.reason)}</span></div><div><small>HUMAN VALIDATION</small><b>${esc(validation.human_validation.status)}</b><span>${esc(validation.human_validation.owner)}: ${esc(validation.human_validation.decision)}</span></div></div><div class="dimension-list">${validation.dimensions.map((item) => `<div class="dimension-row"><div><strong>${esc(item.name)}</strong><span>${esc(item.reason)}</span></div><b>${item.score}/${item.max}</b></div>`).join("")}</div>${validation.caps.length ? `<div class="validation-flags"><strong>Applied confidence caps</strong>${validation.caps.map((item) => `<span>Maximum ${item.value}: ${esc(item.reason)}</span>`).join("")}</div>` : ""}${validation.blockers.length ? `<div class="validation-flags blocked"><strong>Hard stops</strong>${validation.blockers.map((item) => `<span>${esc(item)}</span>`).join("")}</div>` : ""}<div id="evaluation-panel" class="evaluation-panel evaluation-launch"><div><strong>Independent evaluation panel</strong><span>Compare deterministic controls, predictive probability readiness and judges from different model providers.</span></div><button class="action-button approve" data-run-evaluation="${index}">Run model panel</button></div>`, "risk");
}

function judgeFailureMessage(judge) {
  const message = String(judge.reason || judge.error || "Judge unavailable");
  if (/unterminated string|jsondecode|expecting (?:value|property)|structured judgement/i.test(message)) {
    return "The provider returned an incomplete structured judgement. Run the panel again later.";
  }
  return message;
}

function evaluationPanelHTML(evaluation, index) {
  const predictive = evaluation.predictive;
  const retrieval = evaluation.retrieval || { status: "disabled", reason: "Semantic retrieval is disabled.", evidence: [] };
  const retrievedEvidence = retrieval.evidence?.length
    ? `<div class="retrieval-list">${retrieval.evidence.map((item) => `<article><header><strong>${esc(item.source)}</strong><span>${esc(item.source_type)}</span></header><p>${esc(item.excerpt)}</p></article>`).join("")}</div>`
    : "";
  return `<div class="evaluation-heading"><div><span class="section-kicker">MODEL PANEL RESULT</span><h3>Independent evaluation</h3></div><button class="action-button" data-run-evaluation="${index}">Run again</button></div><div class="panel-consensus"><strong>${evaluation.consensus.score}/100</strong><div><b>${esc(evaluation.consensus.band)}</b><span>${esc(evaluation.consensus.rule)}</span></div></div><h4 class="evaluation-subtitle">Evidence coverage</h4><div class="dataset-scores">${Object.entries(evaluation.datasets).map(([name, lens]) => `<div><small>${esc(name)} dataset</small><b>${lens.score}/100</b><span>${esc(lens.detail)}</span></div>`).join("")}</div><div class="validation-layers"><div><small>DETERMINISTIC ALGORITHM</small><b>${evaluation.deterministic.score}/100 · ${esc(evaluation.deterministic.status)}</b><span>Policy, evidence, suitability, freshness and hard-stop validation.</span></div><div><small>PREDICTIVE PROBABILITY</small><b>${esc(predictive.status)}</b><span>${esc(predictive.reason)}</span></div></div><h4 class="evaluation-subtitle">Chroma semantic evidence</h4><div class="retrieval-status ${retrieval.status === "ready" ? "ready" : ""}"><strong>${esc(retrieval.status)}</strong><span>${esc(retrieval.reason)}</span></div>${retrievedEvidence}<h4 class="evaluation-subtitle">Independent judges</h4><div class="judge-list">${evaluation.judges.map((judge) => `<article class="${judge.status === "Completed" ? "completed" : "unavailable"}"><header><div><small>${esc(judge.provider)} provider</small><strong>${esc(judge.model)}</strong></div><b>${judge.status === "Completed" ? `${judge.score}/100` : esc(judge.status)}</b></header>${judge.status === "Completed" ? `<p>${esc(judge.rationale)}</p><div><span>Customer ${judge.customer_fit}</span><span>Product ${judge.product_fit}</span><span>Signal ${judge.signal_support}</span></div>${judge.required_rm_checks?.length ? `<ul>${judge.required_rm_checks.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}` : `<p>${esc(judgeFailureMessage(judge))}</p>`}</article>`).join("")}</div><p class="privacy-note">${esc(evaluation.privacy)} RM approval is still required.</p>`;
}

async function runIndependentEvaluation(client, index, button) {
  button.disabled = true;
  button.textContent = "Evaluating…";
  try {
    const response = await fetch("/api/evaluations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: client.client_id, recommendation_index: index }),
    });
    const payload = await response.json().catch(() => ({ error: `Evaluation service returned ${response.status}` }));
    if (response.status === 404) {
      throw new Error("Evaluation API unavailable. Start the project with python app.py (not a static file server), then refresh.");
    }
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    const panel = $("#evaluation-panel");
    panel.className = "evaluation-panel evaluation-results";
    panel.innerHTML = evaluationPanelHTML(payload, index);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Retry model panel";
    showToast(error.message, "error");
  }
}

function showMethod() {
  openModal(`<span class="section-kicker">METHODOLOGY & CONTROLS</span><h2>From records to an accountable decision</h2><p>Portfolio data is joined by effective date, checked against mandate rules, and reduced to the records required for the current client review.</p><div class="method-steps"><div class="method-step"><b>01 · JOIN BY EFFECTIVE DATE</b><p>Dated holding snapshots remain separate so historical context is preserved.</p></div><div class="method-step"><b>02 · IDENTIFY A REVIEW POINT</b><p>Client objectives, holdings, cash needs, mandates, facilities and RM notes are compared.</p></div><div class="method-step"><b>03 · APPLY CONTROLS</b><p>Mandate checks, approved event sources, valuation-lag flags and confidence rules run before the brief is shown.</p></div><div class="method-step"><b>04 · PREPARE OPTIONS</b><p>The system presents reversible actions and their suitability conditions; it does not place trades.</p></div><div class="method-step"><b>05 · RECORD THE DECISION</b><p>Approval, editing, dismissal and rationale are written to the audit ledger.</p></div></div>`);
}

function showEditRecommendation(client, index) {
  const recommendation = client.recommendations[index];
  const current = decisionFor(client.client_id, index);
  const value = current?.note || recommendation.detail;
  openModal(`<span class="section-kicker">EDIT ACTION</span><h2>${esc(recommendation.title)}</h2><p>Update the wording before approval. The original recommendation remains available in the evidence record.</p><form id="edit-action-form" data-index="${index}"><label class="form-field"><span>Revised action</span><textarea name="note" maxlength="1000" rows="7" required>${esc(value)}</textarea></label><div class="modal-actions"><button type="button" class="small-button" data-close-modal>Cancel</button><button type="submit" class="action-button approve">Save revision</button></div></form>`);
}

function showApproveRecommendation(client, index) {
  const recommendation = client.recommendations[index];
  const current = decisionFor(client.client_id, index);
  openModal(`<span class="section-kicker">RM APPROVAL</span><h2>${esc(recommendation.title)}</h2><p>Record what you have done or will do for this client. Approval is written to the evidence ledger and does not place a trade.</p><form id="approve-action-form" data-index="${index}"><label class="form-field"><span>Action taken or agreed</span><textarea name="note" minlength="10" maxlength="1000" rows="6" required placeholder="Example: Confirmed the facility buffer with Credit and scheduled a client review before funding.">${esc(current?.note || "")}</textarea></label><div class="modal-actions"><button type="button" class="small-button" data-close-modal>Cancel</button><button type="submit" class="action-button approve">Approve and record</button></div></form>`);
}

async function persistDecision(client, index, action, note = "") {
  const response = await fetch("/api/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: client.client_id, recommendation_index: index, action, note }),
  });
  const payload = await response.json().catch(() => ({ error: `Decision service returned ${response.status}` }));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  state.decisions = { records: payload.records, effective: payload.effective };
  renderBook();
  if (state.currentView === "client") renderClient(state.currentClient);
  if (state.currentView === "governance") renderGovernance();
}

function showChartPoint(point) {
  const chart = point.closest("#chart-panel-body");
  if (!chart) return;
  $$(".chart-point", chart).forEach((item) => item.classList.toggle("selected", item === point));
  const change = Number(point.dataset.change);
  $(".chart-readout", chart).innerHTML = `<strong>${monthYear(point.dataset.date)} · $${Number(point.dataset.value).toFixed(2)}m</strong><span>${change === 0 ? "Starting snapshot" : `${change > 0 ? "+" : ""}$${change.toFixed(2)}m from previous snapshot`}</span>`;
}

function bindEvents() {
  document.addEventListener("click", async (event) => {
    const nav = event.target.closest("[data-view]");
    if (nav) showView(nav.dataset.view, nav.dataset.client);
    const open = event.target.closest("[data-open-client]");
    if (open) {
      const useNativeLink = open.matches("a")
        && (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey);
      if (useNativeLink) return;
      event.preventDefault();
      showView("client", open.dataset.openClient);
    }
    const studio = event.target.closest("[data-open-studio]");
    if (studio) showView("scenario", studio.dataset.openStudio);
    if (event.target.closest("[data-back-book]")) showView("book");

    const clientScenario = event.target.closest("[data-client-scenario]");
    if (clientScenario) {
      state.currentScenario = Number(clientScenario.dataset.clientScenario);
      $$("[data-client-scenario]").forEach((button, index) => button.classList.toggle("active", index === state.currentScenario));
      $("#client-scenario-output").innerHTML = scenarioHTML(profiles()[state.currentClient], state.currentScenario);
    }

    const studioScenario = event.target.closest("[data-studio-scenario]");
    if (studioScenario) {
      state.studioScenario = Number(studioScenario.dataset.studioScenario);
      state.studioScale = 100;
      renderScenarioStudio();
    }

    const range = event.target.closest("[data-chart-range]");
    if (range) {
      state.chartRange = range.dataset.chartRange;
      $("#chart-panel-body").innerHTML = pathChart(profiles()[state.currentClient], state.chartRange);
    }

    const chartPoint = event.target.closest("[data-chart-point]");
    if (chartPoint) showChartPoint(chartPoint);

    const decisionButton = event.target.closest("[data-decision]");
    if (decisionButton) {
      const client = profiles()[state.currentClient];
      const index = Number(decisionButton.dataset.index);
      const action = decisionButton.dataset.decision;
      if (action === "edit") {
        showEditRecommendation(client, index);
      } else if (action === "approved") {
        showApproveRecommendation(client, index);
      } else {
        state.dismissedListOpen = action === "pending" && decisionButton.closest(".dismissed-list")?.open === true;
        decisionButton.disabled = true;
        try {
          await persistDecision(client, index, action, decisionFor(client.client_id, index)?.note || "");
          showToast(action === "dismissed" ? "Action dismissed. It can be restored from this review." : action === "approved" ? "Action approved and written to the decision ledger." : "Action restored to the active review.");
        } catch (error) {
          decisionButton.disabled = false;
          showToast(error.message, "error");
        }
      }
    }

    const riskButton = event.target.closest("[data-risk-index]");
    if (riskButton) showRiskValidation(profiles()[state.currentClient], Number(riskButton.dataset.riskIndex));

    const evaluationButton = event.target.closest("[data-run-evaluation]");
    if (evaluationButton) {
      await runIndependentEvaluation(
        profiles()[state.currentClient],
        Number(evaluationButton.dataset.runEvaluation),
        evaluationButton,
      );
    }

    if (event.target.closest("[data-evidence]")) showEvidence(profiles()[state.currentClient]);
    if (event.target.closest("[data-close-modal]")) closeModal();
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-studio-client]")) {
      state.studioClient = event.target.value;
      state.studioScenario = 0;
      state.studioScale = 100;
      history.replaceState({ view: "scenario", clientId: state.studioClient }, "", routeFor("scenario", state.studioClient));
      renderScenarioStudio();
    }
  });

  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-scenario-scale]")) {
      state.studioScale = Number(event.target.value);
      $("#studio-scenario-output").innerHTML = scenarioHTML(profiles()[state.studioClient], state.studioScenario, state.studioScale, true);
    }
  });

  document.addEventListener("focusin", (event) => {
    const chartPoint = event.target.closest("[data-chart-point]");
    if (chartPoint) showChartPoint(chartPoint);
  });

  document.addEventListener("mouseover", (event) => {
    const chartPoint = event.target.closest("[data-chart-point]");
    if (chartPoint) showChartPoint(chartPoint);
  });

  document.addEventListener("submit", async (event) => {
    if (!event.target.matches("#edit-action-form, #approve-action-form")) return;
    event.preventDefault();
    const form = event.target;
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const isApproval = form.matches("#approve-action-form");
      await persistDecision(profiles()[state.currentClient], Number(form.dataset.index), isApproval ? "approved" : "edited", new FormData(form).get("note"));
      closeModal();
      showToast(isApproval ? "Action approved with the RM action recorded." : "Revision saved to the decision ledger.");
    } catch (error) {
      submit.disabled = false;
      showToast(error.message, "error");
    }
  });

  $("#method-button").addEventListener("click", showMethod);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModal(); });
  window.addEventListener("popstate", applyRoute);
}

async function init() {
  try {
    const [intelligenceResponse, decisionsResponse] = await Promise.all([
      fetch("/api/intelligence"),
      fetch("/api/decisions"),
    ]);
    if (!intelligenceResponse.ok) throw new Error(`Intelligence service returned ${intelligenceResponse.status}`);
    if (!decisionsResponse.ok) throw new Error(`Decision ledger returned ${decisionsResponse.status}`);
    state.data = await intelligenceResponse.json();
    state.decisions = await decisionsResponse.json();
    const focusClients = Object.keys(state.data.featured_clients);
    state.currentClient = focusClients[0] || Object.keys(profiles())[0];
    state.studioClient = focusClients.at(-1) || state.currentClient;
    $("#as-of").textContent = fullDate(state.data.meta.as_of);
    $("#rm-context").textContent = `${state.data.meta.rm} · ${state.data.meta.desk}`.toUpperCase();
    $("#rm-avatar").textContent = initials(state.data.meta.rm);
    $("#rm-avatar").setAttribute("aria-label", state.data.meta.rm);
    renderBook();
    renderGovernance();
    bindEvents();
    $("#loading").remove();
    $("#app").hidden = false;
    applyRoute();
  } catch (error) {
    $("#loading").innerHTML = `<p>Unable to load current portfolio records.</p><small>${esc(error.message)}</small><button class="ghost-button" onclick="window.location.reload()">Retry</button>`;
  }
}

init();
