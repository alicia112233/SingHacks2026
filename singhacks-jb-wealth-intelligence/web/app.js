const state = {
  data: null,
  reviewGeneration: 0,
  decisions: { records: [], effective: {} },
  currentView: "book",
  currentClient: null,
  currentScenario: 0,
  studioClient: null,
  studioScenario: 0,
  studioScale: 100,
  chartRange: "YTD",
  dismissedListOpen: false,
  chatClient: null,
  chatClientResults: [],
  chatClientActiveIndex: -1,
  chatConversations: new Map(),
  chatStorageWarningShown: false,
  chatRecognition: null,
  chatSpeechRequest: null,
  chatSpeechMessage: null,
  chatPlayback: "idle",
  chatMessageSequence: 0,
  chatDeleteClient: null,
  eventFilters: { from: "", to: "", sort: "newest", severity: "all", source: "all" },
  clientSearch: "",
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
  return new Date(iso.length === 10 ? `${iso}T00:00:00+08:00` : iso).toLocaleDateString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Singapore",
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

function syncChatContext(clientId = state.currentClient) {
  if (!state.data) return;
  const allProfiles = profiles();
  const nextClient = allProfiles[clientId] ? clientId : state.chatClient || Object.keys(allProfiles)[0];
  if (nextClient !== state.chatClient) {
    cancelChatDeletion();
    if (state.chatClient) stopChatAudio();
    state.chatClient = nextClient;
    $("#chat-input").value = "";
    renderChatTranscript();
  }
  const client = allProfiles[state.chatClient];
  $("#chat-client").value = state.chatClient;
  $("#chat-client").title = `${client.name} · ${client.client_id}`;
  $("#chat-client-name").textContent = client.name;
  $("#chat-client-id").textContent = client.client_id;
  toggleChatClientPicker(false);
}

function toggleChatClientPicker(open, restoreFocus = false) {
  const menu = $("#chat-client-menu");
  menu.hidden = !open;
  $("#chat-client").setAttribute("aria-expanded", String(open));
  const search = $("#chat-client-search");
  search.setAttribute("aria-expanded", String(open));
  if (open) {
    search.value = "";
    renderChatClientOptions();
    search.focus();
  } else {
    search.removeAttribute("aria-activedescendant");
    if (restoreFocus) $("#chat-client").focus();
  }
}

function renderChatClientOptions() {
  const normalize = (value) => String(value).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
  const terms = normalize($("#chat-client-search").value).trim().split(/\s+/).filter(Boolean);
  const clients = Object.values(profiles());
  state.chatClientResults = clients.filter((client) => {
    const label = normalize(`${client.name} ${client.client_id}`);
    return terms.every((term) => label.includes(term));
  });
  const matches = state.chatClientResults;
  $("#chat-client-count").textContent = terms.length
    ? `${matches.length} of ${clients.length} clients`
    : `${clients.length} client${clients.length === 1 ? "" : "s"}`;
  $("#chat-client-list").innerHTML = matches.length ? matches.map((client, index) => `
    <div id="chat-client-option-${index}" class="chat-client-option" role="option" aria-selected="${client.client_id === state.chatClient}" data-chat-client="${esc(client.client_id)}">
      <span class="chat-client-option-avatar" aria-hidden="true">${esc(initials(client.name))}</span>
      <span class="chat-client-option-copy"><strong>${esc(client.name)}</strong><small>${esc(client.client_id)}</small></span>
      ${client.client_id === state.chatClient ? '<svg class="chat-client-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>' : ""}
    </div>`).join("") : '<div class="chat-client-empty"><strong>No clients found</strong><p>Try another name or client ID.</p></div>';
  const selectedIndex = matches.findIndex((client) => client.client_id === state.chatClient);
  setChatClientActiveOption(matches.length ? Math.max(0, selectedIndex) : -1);
}

function setChatClientActiveOption(index) {
  state.chatClientActiveIndex = index;
  $$("[data-chat-client]").forEach((option, optionIndex) => option.classList.toggle("is-active", optionIndex === index));
  const search = $("#chat-client-search");
  if (index < 0) {
    search.removeAttribute("aria-activedescendant");
    return;
  }
  const id = `chat-client-option-${index}`;
  search.setAttribute("aria-activedescendant", id);
  $(`#${id}`).scrollIntoView({ block: "nearest" });
}

function handleChatClientKeydown(event) {
  if (event.isComposing) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    toggleChatClientPicker(false, true);
  } else if (event.key === "Tab") {
    // Return to the trigger before letting the browser advance focus normally.
    toggleChatClientPicker(false, true);
  } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    const count = state.chatClientResults.length;
    if (count) setChatClientActiveOption((state.chatClientActiveIndex + (event.key === "ArrowDown" ? 1 : -1) + count) % count);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const client = state.chatClientResults[state.chatClientActiveIndex];
    if (client) {
      syncChatContext(client.client_id);
      $("#chat-client").focus();
    }
  }
}

function chatStorageKey(clientId) {
  return `tessera.chat.v1:${encodeURIComponent(state.data.meta.rm)}:${encodeURIComponent(clientId)}`;
}

function chatConversation(clientId = state.chatClient) {
  if (!state.chatConversations.has(clientId)) {
    const conversation = { messages: [], request: null, storageAvailable: true, status: "No audio is stored by TESSERA" };
    try {
      const saved = JSON.parse(window.localStorage.getItem(chatStorageKey(clientId)) || "null");
      if (saved?.version === 1 && saved.clientId === clientId && Array.isArray(saved.messages)) {
        conversation.messages = saved.messages.filter((item) => (
          item && ["user", "assistant"].includes(item.role) && typeof item.content === "string"
        )).map((item) => ({
          role: item.role,
          content: item.content,
          mode: typeof item.mode === "string" ? item.mode : "grounded_extract",
          citations: Array.isArray(item.citations) ? item.citations.filter((citation) => citation && typeof citation === "object") : [],
        }));
      }
    } catch {
      conversation.storageAvailable = false;
    }
    state.chatConversations.set(clientId, conversation);
  }
  return state.chatConversations.get(clientId);
}

function saveChatConversation(clientId) {
  const conversation = chatConversation(clientId);
  try {
    window.localStorage.setItem(chatStorageKey(clientId), JSON.stringify({
      version: 1, clientId, messages: conversation.messages,
    }));
    conversation.storageAvailable = true;
  } catch {
    conversation.storageAvailable = false;
    if (!state.chatStorageWarningShown) {
      showToast("Browser storage is unavailable. Chat history will only last for this session.", "error");
      state.chatStorageWarningShown = true;
    }
  }
}

function updateChatControls() {
  const conversation = chatConversation();
  const submit = $(".chat-send", $("#chat-form"));
  submit.disabled = Boolean(conversation.request);
  submit.textContent = conversation.request ? "Thinking…" : "Send";
  $("#chat-delete").disabled = !conversation.messages.length;
  $("#chat-storage-status").textContent = conversation.storageAvailable ? "History saved in this browser" : "History available for this session only";
  $("#chat-status").textContent = conversation.status;
  updateChatAudioControls();
}

function renderChatTranscript() {
  const messages = $("#chat-messages");
  const conversation = chatConversation();
  messages.innerHTML = "";
  if (conversation.messages.length) {
    conversation.messages.forEach((message, index) => messages.append(chatMessageElement(message, index)));
  } else {
    messages.innerHTML = `<article class="chat-message assistant"><div><b>TESSERA</b><span>Client conversation</span></div><p>Ask about ${esc(profiles()[state.chatClient].name)}'s portfolio, liquidity, credit, scenarios, actions, or source evidence.</p></article>`;
  }
  updateChatControls();
  messages.scrollTop = messages.scrollHeight;
}

function deleteChatConversation() {
  const clientId = state.chatClient;
  const conversation = chatConversation(clientId);
  const dialog = $("#chat-delete-dialog");
  if (!conversation.messages.length || dialog.open) return;
  state.chatDeleteClient = clientId;
  $("#chat-delete-client-name").textContent = `${profiles()[clientId].name} (${clientId})`;
  stopChatAudio();
  dialog.showModal();
  $("#chat-delete-cancel").focus();
}

function cancelChatDeletion() {
  state.chatDeleteClient = null;
  const dialog = $("#chat-delete-dialog");
  if (dialog.open) dialog.close();
}

function confirmChatDeletion() {
  const clientId = state.chatDeleteClient;
  if (!clientId || clientId !== state.chatClient || !$("#chat-delete-dialog").open) return;
  const conversation = chatConversation(clientId);
  cancelChatDeletion();
  let deleted = true;
  try {
    window.localStorage.removeItem(chatStorageKey(clientId));
  } catch {
    deleted = false;
    conversation.storageAvailable = false;
  }
  conversation.request?.abort();
  conversation.request = null;
  conversation.messages = [];
  conversation.status = "No audio is stored by TESSERA";
  $("#chat-input").value = "";
  stopChatAudio();
  renderChatTranscript();
  $("#chat-input").focus();
  showToast(deleted ? "Conversation deleted for this client." : "Conversation cleared for this session. Saved browser history could not be deleted.", deleted ? "default" : "error");
}

function updateChatAudioControls() {
  const messages = $("#chat-messages");
  chatConversation().messages.forEach((message, index) => {
    if (message.role !== "assistant") return;
    const button = $(`[data-speak-message="${index}"]`, messages);
    if (!button) return;
    const playback = message === state.chatSpeechMessage ? state.chatPlayback : "idle";
    const labels = {
      loading: ["Loading…", "Loading voice for this answer"],
      speaking: ["Pause", "Pause this answer"],
      paused: ["Resume", "Resume this answer"],
      idle: ["Listen", "Read this answer aloud"],
    }[playback];
    button.textContent = labels[0];
    button.setAttribute("aria-label", labels[1]);
    button.dataset.playback = playback;
    button.disabled = playback === "loading";
  });
  const status = {
    loading: "Loading voice…",
    speaking: "Reading answer aloud…",
    paused: "Audio paused",
  }[state.chatPlayback];
  if (status) $("#chat-status").textContent = status;
}

function toggleChatAudio() {
  if (!state.chatSpeechRequest || !["speaking", "paused"].includes(state.chatPlayback)) return;
  const pause = state.chatPlayback === "speaking";
  if (pause) window.speechSynthesis.pause();
  else window.speechSynthesis.resume();
  state.chatPlayback = pause ? "paused" : "speaking";
  updateChatAudioControls();
}

function stopChatAudio(status = "No audio is stored by TESSERA") {
  state.chatSpeechRequest?.abort();
  state.chatSpeechRequest = null;
  state.chatSpeechMessage = null;
  state.chatPlayback = "idle";
  updateChatAudioControls();
  if (state.chatRecognition) {
    state.chatRecognition.abort?.();
    state.chatRecognition = null;
  }
  window.speechSynthesis?.cancel();
  if (window.speechSynthesis?.paused) window.speechSynthesis.resume();
  const microphone = $("#chat-mic");
  microphone.classList.remove("listening");
  microphone.textContent = "Mic";
  $("#chat-status").textContent = status;
}

function toggleChatExpanded(force) {
  const panel = $("#chat-panel");
  const expanded = typeof force === "boolean" ? force : !panel.classList.contains("is-expanded");
  panel.classList.toggle("is-expanded", expanded);
  const button = $("#chat-expand");
  const label = expanded ? "Collapse chat" : "Expand chat";
  button.setAttribute("aria-expanded", String(expanded));
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
}

function toggleChat(force) {
  const panel = $("#chat-panel");
  const willOpen = typeof force === "boolean" ? force : panel.hidden;
  panel.hidden = !willOpen;
  $("#chat-launcher").setAttribute("aria-expanded", String(willOpen));
  if (willOpen) {
    syncChatContext(state.currentView === "client" ? state.currentClient : state.chatClient);
    window.setTimeout(() => $("#chat-input").focus(), 0);
  } else {
    toggleChatClientPicker(false);
    cancelChatDeletion();
    stopChatAudio();
  }
}

function chatCitationsHTML(citations = [], sourcePrefix = "chat-source") {
  if (!citations.length) return "";
  return `<details class="chat-sources"><summary>${citations.length} source${citations.length === 1 ? "" : "s"}</summary>${citations.map((item) => {
    let sourceLink = "";
    try {
      const url = new URL(item.source_url);
      if (url.protocol === "https:" && !url.username && !url.password) sourceLink = ` · <a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>`;
    } catch { /* Recorded evidence may have no external URL. */ }
    const label = item.evidence_kind === "external_report" ? "External report · not independently verified" : item.evidence_kind === "derived_assessment" ? "Calculated assessment" : "Recorded evidence";
    return `<div class="chat-source" id="${esc(sourcePrefix)}-${esc(item.number)}" tabindex="-1"><b>[${esc(item.number)}] ${esc(item.source)}</b><span>${esc(label)}${item.source_date ? ` · ${esc(item.source_date)}` : ""}${sourceLink}</span>${item.retrieved_at ? `<small>Retrieved ${esc(item.retrieved_at)}</small>` : ""}<p>${esc(item.excerpt)}</p></div>`;
  }).join("")}</details>`;
}

function chatAnswerHTML(content, citations, sourcePrefix) {
  const known = new Set(citations.map((item) => item.number).filter((number) => Number.isInteger(number) && number > 0));
  return String(content).split(/\n\s*\n/).filter((paragraph) => paragraph.trim()).map((paragraph) => {
    const text = esc(paragraph).replace(/\[(\d+)\]/g, (original, number) => known.has(Number(number))
      ? `<button type="button" class="chat-citation" data-chat-citation="${sourcePrefix}-${number}" aria-label="View source ${number}">[${number}]</button>`
      : original);
    return `<p>${text.replaceAll("\n", "<br>")}</p>`;
  }).join("");
}

function chatMessageElement({ role, content, mode, citations }, index) {
  const article = document.createElement("article");
  article.className = `chat-message ${role}`;
  const label = role === "user" ? "You" : "TESSERA";
  const modeLabel = mode === "error" ? "Assistant unavailable" : mode === "insufficient_evidence" ? "Insufficient evidence" : mode === "grounded_summary" ? "Summary" : "From client records";
  const sources = citations || [];
  const sourcePrefix = `chat-source-${++state.chatMessageSequence}`;
  article.innerHTML = `<header class="chat-message-header"><b>${label}</b>${role === "assistant" ? `<span>${esc(modeLabel)}</span><button type="button" data-speak-message="${index}" aria-label="Read this answer aloud">Listen</button>` : ""}</header><div class="chat-answer" data-chat-answer>${chatAnswerHTML(content, sources, sourcePrefix)}</div>${chatCitationsHTML(sources, sourcePrefix)}`;
  return article;
}

function addChatMessage(clientId, role, content, payload = {}) {
  const message = { role, content, mode: payload.mode, citations: payload.citations || [] };
  chatConversation(clientId).messages.push(message);
  saveChatConversation(clientId);
  if (state.chatClient === clientId) renderChatTranscript();
  return message;
}

function preferredChatVoice(voices) {
  // The Web Speech API provides names and languages, but no gender field.
  const femaleName = /\b(female|zira|hazel|susan|heera|samantha|karen|victoria|moira|tessa|serena|aria|jenny|sonia|libby|natasha|clara|ava|emma|ana|joanna)\b/i;
  const english = voices.filter((voice) => /^en(?:[-_]|$)/i.test(voice.lang));
  const female = english.filter((voice) => femaleName.test(voice.name));
  return female.find((voice) => /^en[-_]SG$/i.test(voice.lang))
    || female[0]
    || english.find((voice) => voice.default)
    || english[0];
}

function speakAnswer(message) {
  if (!("speechSynthesis" in window)) {
    showToast("Audio playback is not supported in this browser.", "error");
    return;
  }
  state.chatSpeechRequest?.abort();
  const request = new AbortController();
  state.chatSpeechRequest = request;
  state.chatSpeechMessage = message;
  state.chatPlayback = "loading";
  updateChatAudioControls();
  const synthesis = window.speechSynthesis;
  synthesis.cancel();
  if (synthesis.paused) synthesis.resume();
  const utterance = new SpeechSynthesisUtterance(message.content.replace(/\[\d+\]/g, ""));
  utterance.rate = 1.25;
  const syncPlayback = () => {
    if (state.chatSpeechRequest !== request) return;
    state.chatPlayback = synthesis.paused ? "paused" : "speaking";
    updateChatAudioControls();
  };
  utterance.onstart = syncPlayback;
  utterance.onpause = syncPlayback;
  utterance.onresume = syncPlayback;
  const finish = (status) => {
    if (state.chatSpeechRequest !== request) return;
    $("#chat-status").textContent = status;
    request.abort();
    state.chatSpeechRequest = null;
    state.chatSpeechMessage = null;
    state.chatPlayback = "idle";
    updateChatAudioControls();
  };
  utterance.onend = () => finish("No audio is stored by TESSERA");
  utterance.onerror = () => finish("Audio playback stopped");
  let timer;
  let started = false;
  const cleanup = () => {
    window.clearTimeout(timer);
    synthesis.removeEventListener("voiceschanged", voicesChanged);
  };
  const speak = () => {
    if (request.signal.aborted || started) return;
    started = true;
    cleanup();
    const voice = preferredChatVoice(synthesis.getVoices());
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang || "en-SG";
    synthesis.speak(utterance);
  };
  const voicesChanged = () => {
    if (synthesis.getVoices().length) speak();
  };
  request.signal.addEventListener("abort", cleanup, { once: true });
  if (synthesis.getVoices().length) {
    speak();
  } else {
    synthesis.addEventListener("voiceschanged", voicesChanged);
    timer = window.setTimeout(speak, 1000);
  }
}

function startDictation() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    showToast("Voice input is not supported here. Try Chrome or Edge, or type your question.", "error");
    return;
  }
  if (state.chatRecognition) {
    state.chatRecognition.stop();
    return;
  }
  const recognition = new Recognition();
  state.chatRecognition = recognition;
  recognition.lang = "en-SG";
  recognition.interimResults = true;
  recognition.continuous = false;
  const button = $("#chat-mic");
  button.classList.add("listening");
  button.textContent = "Stop";
  $("#chat-status").textContent = "Listening… audio is handled by your browser";
  recognition.onresult = (event) => {
    if (state.chatRecognition !== recognition) return;
    $("#chat-input").value = [...event.results].map((result) => result[0].transcript).join("");
  };
  recognition.onerror = (event) => {
    if (event.error !== "aborted") showToast(`Voice input stopped: ${event.error}`, "error");
  };
  recognition.onend = () => {
    if (state.chatRecognition !== recognition) return;
    state.chatRecognition = null;
    button.classList.remove("listening");
    button.textContent = "Mic";
    $("#chat-status").textContent = "Review the transcription, then send";
  };
  recognition.start();
}

async function sendChatQuestion(question) {
  const clientId = state.chatClient;
  const conversation = chatConversation(clientId);
  if (conversation.request) return;
  const request = new AbortController();
  conversation.request = request;
  const history = conversation.messages.slice(-6).map((item) => ({
    role: item.role,
    content: item.content.slice(0, item.role === "assistant" ? 800 : 600),
  }));
  conversation.status = "Retrieving controlled evidence…";
  addChatMessage(clientId, "user", question);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, question, history }),
      signal: request.signal,
    });
    const payload = await response.json().catch(() => ({ error: `Assistant returned ${response.status}` }));
    if (response.status === 404) throw new Error("Chat API unavailable. Start the app with python app.py.");
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    if (conversation.request !== request) return;
    conversation.status = payload.mode === "insufficient_evidence" ? "Insufficient evidence for this question" : `Answer with ${payload.citations.length} source${payload.citations.length === 1 ? "" : "s"}`;
    const answer = addChatMessage(clientId, "assistant", payload.answer, payload);
    if (state.chatClient === clientId && !$("#chat-panel").hidden && $("#chat-auto-speak").checked) speakAnswer(answer);
  } catch (error) {
    if (conversation.request !== request) return;
    conversation.status = "Assistant unavailable";
    addChatMessage(clientId, "assistant", `I could not answer that request: ${error.message}`, { mode: "error" });
  } finally {
    if (conversation.request === request) {
      conversation.request = null;
      if (state.chatClient === clientId) updateChatControls();
    }
  }
}

function routeFor(name, clientId) {
  if (name === "client") return `/clients/${encodeURIComponent(clientId)}`;
  if (name === "scenario") return `/scenario-studio?client=${encodeURIComponent(clientId || state.studioClient)}`;
  if (name === "governance") return "/evidence-ledger";
  if (name === "market-events") return "/market-events";
  if (name === "all-clients") return "/all-clients";
  return "/";
}

function initials(name) {
  return String(name || "RM").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function showView(name, clientId, updateHistory = true) {
  const availableViews = ["book", "client", "scenario", "governance", "market-events", "all-clients"];
  const nextView = availableViews.includes(name) ? name : "book";
  $$(".view").forEach((view) => { view.hidden = true; });
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === nextView));

  if (nextView === "client") {
    state.currentClient = profiles()[clientId] ? clientId : state.currentClient;
    syncChatContext(state.currentClient);
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
  } else if (nextView === "all-clients") {
    renderAllClients();
    $("#all-clients-view").hidden = false;
    $("#page-title").textContent = "All clients";
  } else if (nextView === "governance") {
    renderGovernance();
    $("#governance-view").hidden = false;
    $("#page-title").textContent = "Evidence & governance";
  } else if (nextView === "market-events") {
    renderMarketEvents();
    $("#market-events-view").hidden = false;
    $("#page-title").textContent = "Market events";
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
  } else if (path === "/all-clients") {
    showView("all-clients", null, false);
  } else if (path === "/evidence-ledger") {
    showView("governance", null, false);
  } else if (path === "/market-events") {
    showView("market-events", null, false);
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
  const actionsRecorded = client.recommendations.every((_, index) => {
    const action = decisionFor(clientId, index)?.action;
    return action === "approved" || action === "dismissed";
  });
  const queueItem = state.data.book.priority_queue.find((item) => item.client_id === clientId);
  return actionsRecorded && queueItem && urgencyScore(queueItem) < 70;
}

function conversationsRequiringAttention() {
  // A client needs attention today when they may be exposed to a headline or score 70+.
  return state.data.book.priority_queue.filter((item) => {
    if (isClientReviewComplete(item.client_id)) return false;
    return ["breach", "now"].includes(followUpInfo({ ...item, score: urgencyScore(item) }).key);
  }).length;
}

function updateTodayCount(count = conversationsRequiringAttention()) {
  $("#now-count").textContent = count;
}

function followUpLabel(item) {
  return followUpInfo(item).label;
}

// Queue lanes. "May be exposed" answers "did a recent headline touch this
// portfolio hard enough to check today?"; the score answers "whose pressure has
// built up most?". We flag possible exposure; we do not predict the outcome.
//   0 May be exposed - a headline's stress test crosses a hard line; RM confirms or dismisses
//   1 Act now       - urgency score 70+
//   2 This week     - urgency score 45-69
//   3 Monitor       - urgency score under 45
//   4 Reviewed      - RM recorded the review; exposure remains monitored
// Inside each lane the highest score comes first.
const TIER_RANK = { breach: 0, now: 1, week: 2, monitor: 3, resolved: 4 };
const LANES = {
  breach: { title: "May be exposed", note: "A recent headline touches these portfolios. Check each one, then confirm or dismiss." },
  now: { title: "Act now", note: "Urgency score 70 or above" },
  week: { title: "This week", note: "Urgency score 45 to 69" },
  monitor: { title: "Monitor", note: "Urgency score below 45" },
  resolved: { title: "Reviewed", note: "Review recorded; exposure still monitored" },
};

function openBreach(item) {
  return item.escalation && item.escalation.review?.status !== "dismissed" ? item.escalation : null;
}

function followUpInfo(item) {
  if (item.complete) return { key: "resolved", label: "Review recorded · continue monitoring", short: "Reviewed" };
  const breach = openBreach(item);
  if (breach) return { key: "breach", label: "MAY BE EXPOSED", short: breach.review?.status === "confirmed" ? "Exposure confirmed" : "May be exposed" };
  if (item.score >= 70) return { key: "now", label: "ACT NOW", short: "Act now" };
  if (item.score >= 45) return { key: "week", label: "THIS WEEK", short: "This week" };
  return { key: "monitor", label: "MONITOR", short: "Monitor" };
}

function queueCounts(rows) {
  const counts = { breach: 0, now: 0, week: 0, monitor: 0, resolved: 0 };
  rows.forEach((item) => { counts[followUpInfo(item).key] += 1; });
  return counts;
}

function buildQueue() {
  return state.data.book.priority_queue.map((item) => ({
    ...item,
    score: urgencyScore(item),
    complete: isClientReviewComplete(item.client_id),
  })).map((item) => ({ ...item, tier: followUpInfo(item) }))
    .sort((left, right) => right.score - left.score)
    .map((item, index) => ({ ...item, rank: index + 1 }))
    .sort((left, right) => TIER_RANK[left.tier.key] - TIER_RANK[right.tier.key] || left.rank - right.rank);
}

// "Next up" shows where the queue continues when nothing is urgent, so clearing
// the immediate items reveals work rather than an empty page.
function markNextUp(queue) {
  const active = queue.filter((item) => !item.complete);
  const urgent = active.some((item) => ["breach", "now"].includes(item.tier.key));
  if (urgent) return null;
  return active[0]?.client_id || null;
}

function breachPanelHTML(item) {
  const escalation = item.escalation;
  if (!escalation || item.complete) return "";
  const status = escalation.review?.status;
  if (status === "dismissed") {
    return `<div class="breach-panel dismissed">Exposure dismissed by the RM as not relevant: “${esc(escalation.headline)}”</div>`;
  }
  const actions = status === "confirmed"
    ? `<span class="breach-status">Confirmed by the RM · recorded in the ledger</span>`
    : `<button class="small-button" data-escalation-review="confirmed" data-client="${esc(item.client_id)}" data-escalation="${esc(escalation.id)}">Confirm</button>
       <button class="small-button" data-escalation-review="dismissed" data-client="${esc(item.client_id)}" data-escalation="${esc(escalation.id)}">Not relevant</button>`;
  return `
    <div class="breach-panel">
      <div>
        <strong>${esc(escalation.reason)}.</strong>
        ${escalation.check ? `<span><b>What to check:</b> ${esc(escalation.check)}.</span>` : ""}
        ${escalation.exposed_holdings?.length ? `<span><b>Holdings it touches:</b> ${esc(escalation.exposed_holdings.join(", "))}</span>` : ""}
        <span>${sourceTag("news")} Headline: “${esc(escalation.headline)}” · ${esc(escalation.severity)} · ${fullDate(escalation.date)}${escalation.source_url ? ` · <a href="${esc(escalation.source_url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}</span>
        ${escalation.stress ? `<small class="breach-stress">${sourceTag("sim")} ${esc(escalation.stress)}</small>` : ""}
      </div>
      <div class="breach-actions">${actions}</div>
    </div>`;
}

function queueRowHTML(item, nextUpId) {
  const nextUp = item.client_id === nextUpId;
  const chip = item.tier.key === "resolved" ? "done" : `lane-${item.tier.key}`;
  return `
    <a class="queue-row tier-${item.tier.key}" href="${routeFor("client", item.client_id)}" data-open-client="${esc(item.client_id)}" aria-label="Open client review for ${esc(item.client_name)}">
      <div class="score-ring" style="--score:${item.score}"><b>${item.score}</b></div>
      <div class="client-cell"><strong>${esc(item.client_name)}${nextUp ? '<span class="next-up-tag">Next up</span>' : ""}</strong><span>#${item.rank} by score · ${esc(item.client_id)} · ${esc(item.booking_centre)} · $${item.aum_usd_m}m</span></div>
      <div class="cell-copy"><strong>${esc(item.tension)}</strong><span>${esc(item.evidence)}${item.ltv ? ` · ${esc(item.ltv)}` : ""}</span></div>
      <div class="cell-copy"><span class="priority-chip ${chip}">${esc(item.tier.short)}</span><span>${esc(item.complete ? "All actions recorded" : item.next_step)}</span></div>
      <span class="queue-row-arrow" aria-hidden="true">↗</span>
    </a>${breachPanelHTML(item)}`;
}

function queueTableHTML(queue, nextUpId) {
  let lane = null;
  const rows = queue.map((item) => {
    const header = item.tier.key !== lane
      ? `<div class="queue-lane lane-${item.tier.key}"><strong>${LANES[item.tier.key].title}</strong><span>${LANES[item.tier.key].note}</span></div>`
      : "";
    lane = item.tier.key;
    return header + queueRowHTML(item, nextUpId);
  });
  return `
    <div class="queue">
      <div class="queue-head"><span>Score</span><span>Client</span><span>Reason for review</span><span>RM follow-up</span><span></span></div>
      ${rows.join("")}
    </div>`;
}

function summaryHeaderHTML(counts, total) {
  const lanes = [
    ["exposed", counts.breach, "May be exposed"],
    ["now", counts.now, "Act now"],
    ["week", counts.week, "This week"],
    ["monitor", counts.monitor, "Monitor"],
  ];
  return `
    <div class="queue-summary" aria-label="Follow-up summary">
      ${lanes.map(([key, count, label]) => `<div class="queue-stat stat-${key}"><strong>${count}</strong><span>${label}</span></div>`).join("")}
      <div class="queue-stat stat-reviewed"><strong>${counts.resolved}<small> / ${total}</small></strong><span>Reviewed</span></div>
    </div>`;
}

function renderBook() {
  const { book, market_signal: signal } = state.data;
  const fullQueue = buildQueue();
  const counts = queueCounts(fullQueue);
  const nextUpId = markNextUp(fullQueue);
  const queue = fullQueue.slice(0, 5); // Today shows the first five; the rest live on the All clients page
  const attentionCount = counts.breach + counts.now;
  updateTodayCount(attentionCount);
  $("#book-view").innerHTML = `
    <div class="hero-grid">
      <article class="hero-panel">
        <span class="section-kicker">DAILY BOOK REVIEW</span>
        <h1>${attentionCount} client review${attentionCount === 1 ? "" : "s"} require RM attention today.</h1>
        <p>Clients who may be exposed to a recent headline come first, so the RM can check them. Then clients are ranked by urgency score. TESSERA flags possible exposure; it does not predict what the news will do. Every score can be traced to its source records.</p>
        <div class="hero-stats">
          <div><strong>${book.client_count}</strong><small>clients monitored</small></div>
          <div><strong>$${book.aum_usd_m}m</strong><small>book AUM</small></div>
          <div><strong>${book.portfolio_count}</strong><small>portfolios reviewed</small></div>
          <div><strong>${book.stale_valuations}</strong><small>lagged marks flagged</small></div>
        </div>
      </article>
      <aside class="signal-panel">
        <div class="signal-header"><span class="section-kicker">LATEST MARKET EVENT</span><span class="severity severity-${esc(signal.severity).toLowerCase()}">${esc(signal.severity)}</span></div>
        <h2>${esc(signal.description)}</h2>
        <p><strong>Portfolio channel:</strong> ${esc(signal.transmission)}</p>
        <span class="source-line">${esc(signal.source || "Market event")} · ${fullDate(signal.date)}${signal.source_url ? ` · <a href="${esc(signal.source_url)}" target="_blank" rel="noopener noreferrer">Open source</a>` : ""}</span>
        <button class="small-button event-list-link" data-view="market-events">View all market events →</button>
      </aside>
    </div>

    <div class="section-head">
      <div><span class="section-kicker">REVIEW QUEUE</span><h2>Prioritised client follow-up</h2></div>
      <p>Possible news exposure first, then lanes by urgency score, highest first inside each lane. Clearing urgent work reveals the next clients in line.</p>
    </div>
    ${dataLegendHTML()}
    ${summaryHeaderHTML(counts, book.client_count)}
    ${queueTableHTML(queue, nextUpId)}
    <div class="all-clients-link-row"><button class="small-button event-list-link" data-view="all-clients">Open all clients →</button><span>${fullQueue.length - queue.length} more client${fullQueue.length - queue.length === 1 ? "" : "s"} on the all-clients page</span></div>

    <div class="section-head">
      <div><span class="section-kicker">PRIORITY CASES</span><h2>Reviews needing deeper preparation</h2></div>
      <p>Each case brings portfolio history, scenario sensitivities, suitability controls and an accountable decision record into one workflow.</p>
    </div>
    <div class="featured-grid">
      ${Object.values(state.data.featured_clients).map((client) => `
        <button class="featured-card" data-open-client="${esc(client.client_id)}">
          <small>${esc(client.client_id)} · ${esc(client.risk_profile)}</small>
          <h3>${esc(client.name)}</h3>
          <p>${esc(client.tension.portfolio_does)} ${esc(client.tension.future_demands)}</p>
          <b>↗</b>
        </button>`).join("")}
    </div>`;
}

function renderAllClients() {
  $("#all-clients-view").innerHTML = `
    <section class="events-hero">
      <div><span class="section-kicker">FULL BOOK</span><h1>All clients</h1><p>The complete queue: possible news exposure first, then lanes by urgency score, highest first inside each lane. Today’s page shows only the first five.</p></div>
      <button class="back-link" data-view="book">← Back to today</button>
    </section>
    <div class="client-search-toolbar" role="search" aria-label="Search client list">
      <label class="client-search-field" for="all-clients-search">
        <span>Search clients</span>
        <input id="all-clients-search" type="search" data-client-search value="${esc(state.clientSearch)}" placeholder="Name, ID, booking centre, risk profile or RM" autocomplete="off" aria-describedby="client-search-count">
      </label>
      <button class="small-button" id="clear-client-search" type="button" data-clear-client-search>Clear search</button>
      <p id="client-search-count" role="status" aria-live="polite" aria-atomic="true"></p>
    </div>
    <div id="all-clients-results"></div>`;
  renderClientSearchResults();
}

function renderClientSearchResults() {
  const queue = buildQueue();
  const terms = state.clientSearch.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filteredQueue = queue.filter((item) => {
    const searchText = [item.client_name, item.client_id, item.booking_centre, item.risk_profile, state.data.meta.rm]
      .join(" ").toLowerCase();
    return terms.every((term) => searchText.includes(term));
  });
  $("#client-search-count").textContent = `Showing ${filteredQueue.length} of ${queue.length} client${queue.length === 1 ? "" : "s"}`;
  $("#clear-client-search").disabled = !state.clientSearch;
  $("#all-clients-results").innerHTML = `
    ${summaryHeaderHTML(queueCounts(filteredQueue), filteredQueue.length)}
    ${filteredQueue.length ? queueTableHTML(filteredQueue, markNextUp(queue)) : `
      <div class="empty-state"><strong>No clients match your search</strong><span>Try a different name, client ID, booking centre, risk profile or RM, or clear your search.</span></div>`}`;
}

function renderMarketEvents() {
  const events = state.data.market_events || [];
  const { from, to, sort, severity, source } = state.eventFilters;
  const filteredEvents = events
    .filter((event) => (!from || event.date >= from) && (!to || event.date <= to))
    .filter((event) => severity === "all" || event.severity === severity)
    .filter((event) => source === "all" || (source === "live" ? event.source === "live news" : event.source !== "live news"))
    .sort((left, right) => {
      if (sort === "oldest") return left.date.localeCompare(right.date);
      if (sort === "severity") return ({ Severe: 0, High: 1, Medium: 2, Low: 3 }[left.severity] ?? 4) - ({ Severe: 0, High: 1, Medium: 2, Low: 3 }[right.severity] ?? 4) || right.date.localeCompare(left.date);
      return right.date.localeCompare(left.date);
    });
  $("#market-events-view").innerHTML = `
    <section class="events-hero">
      <div><span class="section-kicker">MARKET INTELLIGENCE</span><h1>All market events</h1><p>Controlled events and relevant live-news signals that inform the review workflow.</p></div>
      <button class="back-link" data-view="book">← Back to today</button>
    </section>
    <section class="panel all-events-panel">
      <div class="panel-title"><div><h3>${filteredEvents.length} event${filteredEvents.length === 1 ? "" : "s"} shown</h3><small>${events.length} TOTAL · ${sort === "oldest" ? "OLDEST FIRST" : sort === "severity" ? "HIGHEST SEVERITY FIRST" : "NEWEST FIRST"}</small></div></div>
      <div class="event-filters" aria-label="Filter market events by date">
        <label><span>From</span><input type="date" value="${esc(from)}" data-event-from aria-label="Start date"></label>
        <label><span>To</span><input type="date" value="${esc(to)}" data-event-to aria-label="End date"></label>
        <label><span>Sort</span><select data-event-sort aria-label="Sort market events"><option value="newest" ${sort === "newest" ? "selected" : ""}>Newest first</option><option value="oldest" ${sort === "oldest" ? "selected" : ""}>Oldest first</option><option value="severity" ${sort === "severity" ? "selected" : ""}>Highest severity</option></select></label>
        <label><span>Severity</span><select data-event-severity aria-label="Filter by severity"><option value="all" ${severity === "all" ? "selected" : ""}>All severities</option><option value="Severe" ${severity === "Severe" ? "selected" : ""}>Severe</option><option value="High" ${severity === "High" ? "selected" : ""}>High</option><option value="Medium" ${severity === "Medium" ? "selected" : ""}>Medium</option><option value="Low" ${severity === "Low" ? "selected" : ""}>Low</option></select></label>
        <label><span>Source</span><select data-event-source aria-label="Filter by source"><option value="all" ${source === "all" ? "selected" : ""}>All sources</option><option value="live" ${source === "live" ? "selected" : ""}>Live news</option><option value="controlled" ${source === "controlled" ? "selected" : ""}>Controlled register</option></select></label>
        <button class="small-button" type="button" data-clear-event-filters ${from || to || sort !== "newest" || severity !== "all" || source !== "all" ? "" : "disabled"}>Clear filters</button>
      </div>
      <div class="all-events-list">${filteredEvents.length ? filteredEvents.map((event) => `<article class="all-event-row"><div class="all-event-date"><strong>${fullDate(event.date)}</strong><span>${esc(event.region)} · ${esc(event.type)}</span></div><div class="all-event-copy"><header><span class="severity severity-${esc(event.severity).toLowerCase()}">${esc(event.severity)}</span>${sourceTag(event.source === "live news" ? "news" : "record")}<h3>${esc(event.description)}</h3></header><p>${esc(event.transmission)}</p><small>${esc(event.publisher || event.source)}${event.source_url ? ` · <a href="${esc(event.source_url)}" target="_blank" rel="noopener noreferrer">Open news source ↗</a>` : ""}</small>${triageNote(event)}</div></article>`).join("") : `<div class="empty-state"><strong>No events match those dates</strong><span>Choose a wider date range or clear the calendar filters.</span></div>`}</div>
    </section>`;
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
  const decision = state.decisions.effective[`${clientId}:${index}`];
  const client = profiles()[clientId];
  const action = client && reviewedRecommendation(client, index);
  if (!decision || !action || decision.recommendation_id !== action.id) return null;
  if (decision.action === "approved" && (decision.version !== action.version || approvalBlocked(action))) return null;
  return decision;
}

function urgencyScore(item) {
  return item.score;
}

function actionReference(client, index) {
  const action = reviewedRecommendation(client, index);
  return { recommendation_id: action.id, version: action.version };
}

function reviewedRecommendation(client, index) {
  const original = client.recommendations[index];
  const revision = state.decisions.reviews?.[`${client.client_id}:${index}`];
  return revision && revision.id === original.id && revision.evidence_version === original.evidence_version ? { ...original, ...revision } : original;
}

function approvalBlocked(recommendation) {
  const validation = recommendation.risk_validation;
  return !validation || validation.band === "Blocked" || validation.score < 50 || Boolean(validation.blockers?.length);
}

function recommendationHTML(client, recommendation, index) {
  const decision = decisionFor(client.client_id, index);
  recommendation = reviewedRecommendation(client, index);
  const detail = recommendation.detail;
  const status = decision?.action || "pending";
  const validation = recommendation.risk_validation;
  const blocked = approvalBlocked(recommendation);
  const replacementChip = recommendation.replacement_for ? `<span class="replacement-chip" title="Generated after the RM dismissed: ${esc(recommendation.replacement_for)}">Replacement suggestion</span>` : "";
  return `<article class="recommendation" data-recommendation="${index}">
    <header><h4>${index + 1}. ${esc(recommendation.title)}</h4><div class="recommendation-badges">${replacementChip}${validation ? `<button class="confidence-chip ${validation.band.toLowerCase().replaceAll(" ", "-")}" data-risk-index="${index}" aria-label="Open evidence rubric for ${esc(recommendation.title)}"><span>Evidence</span><b>${validation.score}</b><span>${esc(validation.band)}</span></button>` : ""}${status !== "pending" ? `<span class="decision-status ${status}">${esc(status)}</span>` : ""}</div></header>
    <p>${esc(detail)}</p>
    ${blocked ? `<div class="validation-flags blocked"><strong>Needs correction</strong>${(validation?.blockers?.length ? validation.blockers : [validation?.disposition || "Validation is unavailable"]).map(reason => `<span>${esc(reason)}</span>`).join("")}</div>` : ""}
    ${recommendationRationaleHTML(recommendation, index)}
    <footer><span class="suitability">${esc(recommendation.suitability)}</span><div class="recommendation-actions">
      <button class="action-button" data-decision="edit" data-index="${index}">Edit</button>
      ${status === "approved" && !blocked ? `<button class="action-button" data-decision="pending" data-index="${index}">Reopen</button>` : blocked ? `<span class="action-tooltip" data-tooltip="Correct the action and pass validation before approval" tabindex="0"><button class="action-button" disabled aria-label="Approval blocked">Blocked</button></span>` : `<button class="action-button approve" data-decision="approved" data-index="${index}">Approve</button>`}
      <button class="action-button dismiss" data-decision="dismissed" data-index="${index}">Dismiss</button>
    </div></footer>
  </article>`;
}

function recommendationRationaleHTML(recommendation, index) {
  const rationale = recommendation.decision_rationale;
  if (!rationale) return "";
  const evidence = rationale.supporting_evidence || [];
  const checks = rationale.rm_checks || [];
  const priority = recommendation.priority;
  return `<details class="action-rationale">
    <summary><span>Why this action</span>${priority ? `<em class="priority-tag priority-${priority.band.toLowerCase()}">${esc(priority.band)} priority</em>` : ""}<small>View rationale and evidence</small></summary>
    <div class="rationale-body">
      ${priority ? `<div class="rationale-section rationale-priority"><strong>Why ${index ? "it sits here" : "it comes first"}</strong><p>${esc(priority.reason)}</p></div>` : ""}
      <p class="rationale-summary">${esc(rationale.summary)}</p>
      <div class="rationale-section"><strong>Trigger</strong><p>${esc(rationale.trigger)}</p></div>
      ${evidence.length ? `<div class="rationale-section"><strong>Evidence used</strong><div class="rationale-evidence">${evidence.map((item) => `<div><span>${esc(item.claim)}</span><small>${esc(item.source)} · ${esc(item.status)}</small></div>`).join("")}</div></div>` : ""}
      ${checks.length ? `<div class="rationale-section"><strong>RM checks before action</strong><ul>${checks.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div>` : ""}
      <p class="rationale-method">${esc(rationale.method)}</p>
    </div>
  </details>`;
}

function recommendationsHTML(client) {
  const active = [], blocked = [], dismissed = [];
  client.recommendations.forEach((recommendation, index) => {
    const entry = { recommendation, index };
    if (decisionFor(client.client_id, index)?.action === "dismissed") dismissed.push(entry);
    else if (approvalBlocked(reviewedRecommendation(client, index))) blocked.push(entry);
    else active.push(entry);
  });
  const dismissedOpen = state.dismissedListOpen && dismissed.length > 0;
  state.dismissedListOpen = false;
  return `${active.length ? active.map(({ recommendation, index }) => recommendationHTML(client, recommendation, index)).join("") : `<div class="empty-state"><strong>No supported actions available</strong><span>Resolve the drafts below or return to the review queue.</span></div>`}
    ${blocked.length ? `<section class="needs-correction" aria-label="Drafts needing correction"><div class="panel-title"><h3>Needs correction</h3><small>NOT SUPPORTED FOR APPROVAL</small></div>${blocked.map(({ recommendation, index }) => recommendationHTML(client, recommendation, index)).join("")}</section>` : ""}
    ${dismissed.length ? `<details class="dismissed-list"${dismissedOpen ? " open" : ""}><summary>${dismissed.length} dismissed action${dismissed.length > 1 ? "s" : ""}</summary>${dismissed.map(({ recommendation, index }) => `<div class="dismissed-row"><div><strong>${esc(recommendation.title)}</strong><span>${esc(decisionFor(client.client_id, index)?.note || "Dismissed from the active review")}</span></div><button class="action-button" data-decision="pending" data-index="${index}">Restore</button></div>`).join("")}</details>` : ""}`;
}

function riskAnalysisHTML(risk = {}) {
  risk = risk || {};
  const score = value => typeof value === "number" && Number.isFinite(value) ? `${Number(value.toFixed(1))}/5` : "Insufficient data";
  return `<section class="panel risk-analysis">
    <div class="panel-title"><h3>Risk Appetite ${sourceTag("calc")}</h3></div>
    <div class="risk-analysis-scores">${["capacity", "tolerance", "horizon", "overall"].map(key => `<div><span>${key[0].toUpperCase() + key.slice(1)}:</span> <strong>${score(risk[key])}</strong></div>`).join("")}</div>
    <p>${esc(risk.explanation || "Insufficient data. Risk analysis is unavailable in the current customer record.")}</p>
  </section>`;
}

function urgencyAcknowledgementHTML(clientId) {
  const queueItem = state.data.book.priority_queue.find((item) => item.client_id === clientId);
  if (!queueItem || urgencyScore(queueItem) < 80) return "";
  return `<section class="urgency-alert-control" aria-label="Urgency alert control">
    <div><span class="section-kicker">TELEGRAM ALERT ACTIVE</span><strong>Urgency score ${urgencyScore(queueItem)}/100</strong><p>Acknowledge after you have seen the alert. This pauses reminders, but a material worsening will still trigger an escalation alert.</p></div>
    <button class="action-button acknowledge-alert" data-urgency-acknowledge="${esc(clientId)}">Acknowledge alert</button>
  </section>`;
}

async function acknowledgeUrgencyAlert(clientId, button) {
  button.disabled = true;
  try {
    await requestJson("/api/notifications/urgency/acknowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, note: "Acknowledged in TESSERA" }),
    });
    button.textContent = "Alert acknowledged";
    showToast("Telegram reminders are paused for this case. A material worsening will still alert you.");
  } catch (error) {
    button.disabled = false;
    showToast(error.message, "error");
  }
}

function queueCard(clientId) {
  return state.data.book.priority_queue.find((item) => item.client_id === clientId);
}

// The same exposure flag as the queue, so the client page never tells a different story.
function clientBreachHTML(clientId) {
  const card = queueCard(clientId);
  if (!card?.escalation) return "";
  return `<div class="client-breach"><span class="section-kicker">MAY BE EXPOSED</span>${breachPanelHTML({ ...card, complete: isClientReviewComplete(clientId) })}</div>`;
}

function detectedFromHTML(clientId) {
  const card = queueCard(clientId);
  if (!card?.detections?.length) return "";
  const names = {
    "clients.csv: source_of_wealth": "source of wealth",
    "clients.csv: objectives": "stated objectives",
    "clients.csv: liquidity_needs": "stated liquidity need",
    "clients.csv: risk_profile": "risk profile",
    "holdings.csv: liquidity_tier": "holding liquidity",
    "holdings.csv: asset_class": "asset mix",
    "holdings.csv: instrument_ccy": "holding currencies",
    "holdings.csv: maturities": "bond maturities",
    "planned_cash_needs.csv": "planned cash needs",
    "commitments.csv": "fund commitments",
  };
  const sources = card.detected_from.map((source) => names[source] || source.replace("rm_notes.json: ", "RM note "));
  return `<p class="detected-from"><strong>Why this client is flagged:</strong> ${esc(card.tension)}. Detected from ${esc(sources.join(", "))}.</p>`;
}

function clientVector(clientId) {
  return state.data.client_vectors?.clients?.[clientId];
}

function featureValue(unit, value) {
  if (unit === "share") return `${Math.round(value * 100)}%`;
  if (unit === "points") return `${value > 0 ? "+" : ""}${Math.round(value * 100)} pts`;
  if (unit === "ratio") return `${value.toFixed(1)}×`;
  if (unit === "years") return `${value} yrs`;
  return `${value}/10`;
}

function similarReasons(item) {
  if (!item.drivers.length) return "No single dimension stands out";
  return item.drivers.map((reason) => `${reason.label} ${featureValue(reason.unit, reason.a)} vs ${featureValue(reason.unit, reason.b)}`).join(" · ");
}

function standing(row) {
  return row.above >= row.below ? `higher than ${row.above} of ${row.others}` : `lower than ${row.below} of ${row.others}`;
}

function goalDriftChart(points) {
  const width = 300, height = 92, pad = 22;
  const values = points.map((point) => point.pct);
  const top = Math.max(...values, 1) * 1.15;
  const x = (i) => pad + (i * (width - 2 * pad)) / Math.max(points.length - 1, 1);
  const y = (v) => height - 18 - (v / top) * (height - 34);
  const line = points.map((point, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(point.pct).toFixed(1)}`).join(" ");
  return `<svg class="drift-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Share in themes the client asked to leave, from ${values[0]}% to ${values[values.length - 1]}%">
    <line x1="${pad}" y1="${height - 18}" x2="${width - pad}" y2="${height - 18}" class="drift-axis"/>
    <path d="${line}" class="drift-line"/>
    ${points.map((point, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(point.pct).toFixed(1)}" r="${i === points.length - 1 ? 4.5 : 3}" class="drift-dot"/><text x="${x(i).toFixed(1)}" y="${(y(point.pct) - 8).toFixed(1)}" text-anchor="middle" class="drift-value">${point.pct}%</text><text x="${x(i).toFixed(1)}" y="${height - 4}" text-anchor="middle" class="drift-date">${monthYear(point.date)}</text>`).join("")}
  </svg>`;
}

function clientVectorHTML(clientId) {
  const vector = clientVector(clientId);
  if (!vector) return "";
  const drift = vector.goal_gap
    ? `<div class="vector-block"><small>DRIFT FROM STATED GOAL</small><p>Share of the portfolio in what the client asked to move away from (${esc(vector.goal_themes)}), looked through.</p>${goalDriftChart(vector.goal_gap)}</div>`
    : "";
  const fingerprint = `<div class="vector-block"><small>WHAT SETS THIS BOOK APART</small><ul class="vector-moves vector-fingerprint">${vector.fingerprint.map((row) => `<li><span><em>${esc(row.group)}</em>${esc(row.label)} <b>${featureValue(row.unit, row.value)}</b></span><small>${standing(row)}</small></li>`).join("")}</ul></div>`;
  const similar = vector.similar.map((item) => `
      <a class="similar-row" href="${routeFor("client", item.client_id)}" data-open-client="${esc(item.client_id)}">
        <span class="similar-name">${esc(item.name)}</span><span class="similar-score">${item.similarity.toFixed(2)} similarity</span>
        <small>${esc(similarReasons(item))}</small>
      </a>`).join("");
  return `
    <section class="panel vector-panel">
      <div class="panel-title"><h3>Client vector ${sourceTag("calc")}</h3><small>${state.data.client_vectors.features.length} NAMED DIMENSIONS · CALCULATED IN-HOUSE · NEVER SENT TO A MODEL</small></div>
      <div class="vector-grid">
        <div class="vector-stack">${drift}${fingerprint}</div>
        <div class="vector-block"><small>CLIENTS LIKE THIS ONE</small>${similar}<p class="vector-note">Similarity runs from -1 to 1: each of the 24 dimensions is ranked across the book and the five groups count equally. Reasons are the dimensions that add most to the score. A measure of how alike two books look, not a prediction or a news signal.</p></div>
      </div>
    </section>`;
}

// Every section says where its content comes from, so simulated and real data are never confused.
const SOURCE_TAGS = {
  record: "Client record (synthetic)",
  calc: "Calculated by TESSERA",
  sim: "Scenario, not a forecast",
  news: "Public news",
};

function sourceTag(kind) {
  return `<span class="source-tag source-${kind}">${SOURCE_TAGS[kind]}</span>`;
}

function triageNote(event) {
  const triage = event.triage;
  if (!triage) return "";
  const read = triage.relevant ? (triage.topics.length ? `Topics: ${triage.topics.join(", ")}` : "No portfolio topic") : "Not relevant to client books";
  return `<small class="triage-note">Read by ${triage.models.length} public-news models · ${esc(read)} · ${esc(triage.agreement)}</small>`;
}

function dataLegendHTML() {
  return `<div class="data-legend"><div><strong>Sources</strong>${sourceTag("record")}${sourceTag("calc")}${sourceTag("sim")}${sourceTag("news")}</div><p>Client records are invented for this demo. In a bank, client records and figures calculated from them are confidential (C3 to C4); public news is C1 to C2.</p></div>`;
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
    ${dataLegendHTML()}
    <div class="metric-rail">${client.headline_metrics.map((metric) => `<div><strong>${esc(metric.value)}</strong><span>${esc(metric.label)}</span></div>`).join("")}</div>
    <div class="tag-row">Figures above ${sourceTag("calc")}</div>
    ${clientBreachHTML(clientId)}
    ${riskAnalysisHTML(client.risk_analysis)}
    ${urgencyAcknowledgementHTML(clientId)}
    <div class="tension-map">
      <div class="tension-item"><small>CLIENT POSITION</small>${sourceTag("record")}<p>${esc(client.tension.client_says)}</p></div>
      <div class="tension-item"><small>PORTFOLIO POSITION</small>${sourceTag("calc")}<p>${esc(client.tension.portfolio_does)}</p></div>
      <div class="tension-item"><small>UPCOMING CONSTRAINT</small>${sourceTag("record")}<p>${esc(client.tension.future_demands)}</p></div>
    </div>
    ${detectedFromHTML(clientId)}
    ${clientVectorHTML(clientId)}

    <div class="analysis-grid">
      <section class="panel">
        <div class="panel-title"><h3>Portfolio value history ${sourceTag("record")}</h3><small>OBSERVED SNAPSHOTS · USD CONVERTED</small></div>
        <div id="chart-panel-body">${pathChart(client)}</div>
        <p class="chart-note">Value includes market movement, transactions, withdrawals and currency translation. Select a point for the exact snapshot value and period change.</p>
      </section>
      <aside class="panel">
        <div class="panel-title"><h3>Relevant market events</h3><small>EVENT REGISTER + LIVE NEWS</small></div>
        <div class="events-list">${client.linked_events.length ? client.linked_events.slice(-3).map((event) => `<div class="event-item"><small>${fullDate(event.date)} · ${esc(event.severity)}${event.publisher ? ` · ${esc(event.publisher)}` : ""}</small>${sourceTag(event.source === "live news" ? "news" : "record")}<p>${esc(event.description)}</p><span>${esc(event.transmission)}${event.source_url ? ` · <a href="${esc(event.source_url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}</span>${triageNote(event)}</div>`).join("") : `<div class="empty-state"><strong>No directly linked events</strong><span>The review is based on portfolio, mandate and client records.</span></div>`}</div>
      </aside>
    </div>

    <section class="panel scenario-panel">
      <aside class="scenario-sidebar"><span class="section-kicker">SCENARIO ANALYSIS</span><h3>Test the portfolio</h3>${sourceTag("sim")}${client.scenarios.map((scenario, index) => `<button class="scenario-selector ${index === state.currentScenario ? "active" : ""}" data-client-scenario="${index}">${esc(scenario.name)}</button>`).join("")}<button class="scenario-studio-link" data-open-studio="${esc(client.client_id)}">Open full scenario studio →</button></aside>
      <div class="scenario-output" id="client-scenario-output">${scenarioHTML(client, state.currentScenario)}</div>
    </section>

    <div class="decision-grid">
      <section class="panel"><div class="panel-title"><h3>Actions worth considering ${sourceTag("calc")}</h3><small>MOST PRESSING FIRST · EVIDENCE SHOWS HOW WELL EACH IS SUPPORTED</small></div><div id="recommendations-list">${recommendationsHTML(client)}</div></section>
      <aside class="panel conversation-card"><div class="panel-title"><h3>Conversation brief ${sourceTag("calc")}</h3><small>${esc(client.confidence.level)}</small></div><div class="talk-line"><small>OPEN WITH</small><p>${esc(client.conversation.open)}</p></div><div class="talk-line"><small>SHOW</small><p>${esc(client.conversation.show)}</p></div><div class="talk-line"><small>ASK</small><p>${esc(client.conversation.ask)}</p></div><div class="talk-line"><small>AVOID</small><p>${esc(client.conversation.avoid)}</p></div><button class="evidence-button" data-evidence>Open evidence passport →</button></aside>
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

const LEDGER_LABELS = {
  approved: "Approved",
  edited: "Edited",
  dismissed: "Dismissed",
  pending: "Restored",
  evaluated: "Model review",
  alternative: "Alternative",
  escalation_confirmed: "Exposure confirmed",
  escalation_dismissed: "Exposure dismissed",
};

// Shows exactly what would leave TESSERA, so the privacy boundary can be checked, not just claimed.
const CLAIM_FILES = { "planned_cash_needs.csv": "Planned cash need", "mandates.csv": "Mandate", "holdings.csv": "Holding", "credit_facilities.csv": "Credit facility" };
const CLAIM_FIELDS = {
  amount: "amount", amount_usd_m: "amount in USD", "due_from.year": "due year", min_pct: "minimum weight", max_pct: "maximum weight",
  delta_usd_m: "change in value", ltv_pct: "loan-to-value", trigger_pct: "margin-call level", points_to_trigger: "points to margin call",
  lending_value_buffer_m: "lending value cushion",
};

function claimValue(claim) {
  if (claim.unit === "percent") return `${claim.value}%`;
  if (claim.unit.endsWith(" million")) return `${claim.unit.split(" ")[0]} ${claim.value}m`;
  if (claim.unit === "number") return String(claim.value);
  return `${claim.value} ${claim.unit}`;
}

// Every number in an action is traced to a record; this shows where each one comes from.
function claimSourcesHTML(claims) {
  if (!claims?.length) return "";
  const rows = claims.map((claim) => claim.sources.map((source) => {
    const [file, ...record] = String(source.source).split(":");
    return `<tr><td>${esc(claimValue(claim))}</td><td>${esc(CLAIM_FILES[file] || file)}, ${esc(CLAIM_FIELDS[source.field] || source.field.replaceAll("_", " "))}<small>${esc(record.join(":"))} · ${fullDate(source.as_of)}</small></td></tr>`;
  }).join("")).join("");
  return `<div class="claim-sources"><strong>Where each number comes from</strong><table><thead><tr><th>In this action</th><th>Source record</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function modelPacketHTML(evaluation) {
  if (!evaluation.packet) return "";
  const check = evaluation.privacy_check || {};
  const status = check.status === "Passed" ? "Privacy check passed" : `Privacy check blocked: ${(check.issues || []).join(", ")}`;
  return `<details class="model-packet"><summary><strong>What the in-house model sees</strong><span>${esc(status)} · fingerprint ${esc(String(evaluation.packet_fingerprint || "").slice(0, 12))}</span></summary><pre>${esc(JSON.stringify(evaluation.packet, null, 2))}</pre></details>`;
}

function renderDecisionLedger() {
  const records = [...state.decisions.records].reverse().slice(0, 12);
  if (!records.length) return `<div class="empty-state ledger-empty"><strong>No decisions recorded</strong><span>Approvals, edits, dismissals and exposure reviews will appear here.</span></div>`;
  return `<div class="ledger-list">${records.map((record) => {
    const breach = record.action?.startsWith("escalation_");
    const title = breach ? `Possible exposure: ${record.headline}` : record.recommendation_title;
    const detail = breach ? record.reason : record.note;
    return `<article class="ledger-row"><span class="decision-status ${esc(record.action)}">${esc(LEDGER_LABELS[record.action] || record.action)}</span><div><strong>${esc(title)}</strong><p>${esc(record.client_name)} · ${esc(record.actor || "Review service")} · ${recordedDate(record.recorded_at)}</p>${detail ? `<small>${esc(detail)}</small>` : ""}</div></article>`;
  }).join("")}</div>`;
}

function renderGovernance() {
  const { governance, data_quality: quality } = state.data;
  const rubric = governance.confidence_rubric;
  const nodes = [
    ["01", "Bank records", "Dated positions, portfolios, facilities, needs and RM notes"],
    ["02", "Temporal joins", "As-of views preserve valuation dates and surface stale marks"],
    ["03", "Deterministic gate", "Mandates, exclusions, concentration and source integrity"],
    ["04", "Contradiction detection", "Client words compared with look-through holdings, sources cited"],
    ["05", "News exposure check", "Recent headlines nudge scores; a hard-line stress flags the client to check"],
    ["06", "RM decision", "Approvals and exposure reviews are recorded in the ledger"],
  ];
  $("#governance-view").innerHTML = `
    <section class="governance-hero"><span class="section-kicker">CONTROLLED BY DESIGN</span><h1>Every review point has an owner, a source and a recorded outcome.</h1><p>TESSERA keeps three things apart: calculations done by deterministic code, signals read from client records and news, and a second-layer model review that can only lower a score; in production it runs on the bank's in-house model, while external models only see public data. Relationship Managers stay accountable for every action and the reason behind it.</p></section>
    <section class="architecture"><div class="panel-title"><h3>Operating architecture</h3><small>CLIENT DATA STAYS ON THE BANK'S IN-HOUSE MODEL</small></div><div class="architecture-flow">${nodes.map((node) => `<div class="architecture-node"><b>${node[0]}</b><strong>${node[1]}</strong><span>${node[2]}</span></div>`).join("")}</div></section>
    <div class="governance-grid"><section class="panel"><div class="panel-title"><h3>Control framework</h3><small>${esc(governance.recommendation_state)}</small></div><div class="principle-list">${governance.principles.map((principle, index) => `<div class="principle-item"><b>${index + 1}</b><p>${esc(principle)}</p></div>`).join("")}</div></section><section class="panel"><div class="panel-title"><h3>Data fitness before advice</h3><small>${esc(quality.overall)}</small></div><div class="quality-list">${quality.checks.map((item) => `<div class="quality-item"><div><strong>${esc(item.name)}</strong><span>${esc(item.evidence)}</span></div><b class="quality-status ${esc(item.status)}">${esc(item.status)}</b></div>`).join("")}</div></section></div>
    ${rubric ? `<section class="panel confidence-rubric"><div class="panel-title"><div><h3>Recommendation confidence rubric</h3><p>${esc(rubric.meaning)}</p></div><small>VERSION ${esc(rubric.version)} · ${esc(rubric.calibration)}</small></div><div class="rubric-layout"><div class="rubric-weights">${rubric.weights.map((item) => `<div><span>${esc(item.name)}</span><b>${item.weight} pts</b></div>`).join("")}</div><div class="rubric-bands">${rubric.bands.map((item) => `<div><b>${esc(item.range)}</b><strong>${esc(item.label)}</strong><span>${esc(item.action)}</span></div>`).join("")}</div></div></section>` : ""}
    <section class="panel decision-ledger"><div class="panel-title"><h3>Decision ledger</h3><small>${state.decisions.records.length} RECORDED EVENT${state.decisions.records.length === 1 ? "" : "S"}</small></div>${renderDecisionLedger()}</section>`;
}

function showEvidence(client) {
  openModal(`<span class="section-kicker">EVIDENCE PASSPORT</span><h2>${esc(client.name)}</h2><p>${esc(client.confidence.reason)} Each review point remains linked to the record used to support it.</p>${client.evidence_passport.map((item) => `<div class="passport-row"><header><strong>${esc(item.claim)}</strong><b>${esc(item.status)}</b></header><p>${esc(item.source)}</p></div>`).join("")}`);
}

function showRiskValidation(client, index) {
  const recommendation = reviewedRecommendation(client, index);
  const validation = recommendation.risk_validation;
  if (!validation) return;
  openModal(`<span class="section-kicker">RECOMMENDATION RISK RUBRIC</span><h2>${esc(recommendation.title)}</h2><p>Rubric ${esc(validation.rubric_version)} &middot; Sources as of ${esc(validation.as_of)}</p><p>Raw ${validation.raw_score}/100 &rarr; ${validation.blockers.length ? "hard stop" : `cap ${Math.min(100, ...validation.caps.map(cap => cap.value))}`} &rarr; published ${validation.score}/100</p><div class="validation-summary"><strong>${validation.score}/100</strong><div><b>${esc(validation.band)}</b><span>${esc(validation.disposition)}</span></div></div><p>${esc(validation.score_meaning)} Residual hallucination risk: ${esc(validation.residual_hallucination_risk)}.</p><div class="validation-layers"><div><small>DETERMINISTIC VALIDATION</small><b>${esc(validation.model_validation.status)}</b><span>${esc(validation.model_validation.reason)}</span></div><div><small>HUMAN VALIDATION</small><b>${esc(validation.human_validation.status)}</b><span>${esc(validation.human_validation.owner)}: ${esc(validation.human_validation.decision)}</span></div></div><div class="dimension-list">${validation.dimensions.map((item) => `<div class="dimension-row"><div><strong>${esc(item.name)}</strong><span>${esc(item.reason)}</span><span>${item.max - item.score} points withheld.</span></div><b>${item.score}/${item.max}</b></div>`).join("")}</div>${validation.caps.length ? `<div class="validation-flags"><strong>Score limits</strong>${validation.caps.map((item) => `<span>Capped at ${item.value}: ${esc(item.reason.charAt(0).toLowerCase() + item.reason.slice(1))}</span>`).join("")}</div>` : ""}${validation.blockers.length ? `<div class="validation-flags blocked"><strong>Hard stops</strong>${validation.blockers.map((item) => `<span>${esc(item)}</span>`).join("")}</div>` : ""}${claimSourcesHTML(validation.resolved_claims)}<div id="evaluation-panel" class="evaluation-panel evaluation-launch"><div><strong>Independent evaluation panel</strong><span>Check this action with the bank's own model from three angles.</span></div><button class="action-button approve" data-run-evaluation="${index}">Run model panel</button></div>`, "risk");
  if (recommendation.evaluation) {
    const panel = $("#evaluation-panel");
    panel.className = "evaluation-panel evaluation-results";
    panel.innerHTML = evaluationPanelHTML(recommendation.evaluation, index);
  }
}

function judgeFailureMessage(judge) {
  const message = String(judge.reason || judge.error || "Judge unavailable");
  if (/unterminated string|jsondecode|expecting (?:value|property)|structured judgement/i.test(message)) {
    return "The provider returned an incomplete structured judgement. Run the panel again later.";
  }
  return message;
}

function evaluationPanelHTML(evaluation, index) {
  const retrieval = evaluation.retrieval || { status: "disabled", evidence: [] };
  const retrievedEvidence = retrieval.status === "ready" && retrieval.evidence?.length
    ? `<h4 class="evaluation-subtitle">Similar past evidence</h4><div class="retrieval-list">${retrieval.evidence.map((item) => `<article><header><strong>${esc(item.source)}</strong><span>${esc(item.source_type)}</span></header><p>${esc(item.excerpt)}</p></article>`).join("")}</div>`
    : "";
  const angles = evaluation.judges.map((judge) => (judge.angle || judge.model).toLowerCase()).join(", ").replace(/, ([^,]*)$/, " and $1");
  const ran = evaluation.judges.some((judge) => judge.status === "Completed");
  const standIn = evaluation.reviewer?.deployment?.startsWith("Demo") ? ` In this demo, ${esc(evaluation.reviewer.model)} stands in for the bank's model.` : "";
  const inHouse = ran
    ? `<h4 class="evaluation-subtitle">In-house model, three angles</h4><p class="production-note">Client data only goes to the bank's own model, which checks this action for ${esc(angles)}.${standIn}</p><div class="judge-list">${evaluation.judges.map((judge) => `<article class="${judge.status === "Completed" ? "completed" : "unavailable"}"><header><div><small>${esc(judge.angle ? "Angle · In-house model" : `${judge.provider} provider`)}</small><strong>${esc(judge.angle || judge.model)}</strong></div><b>${judge.status === "Completed" ? `${judge.score}/100` : esc(judge.status)}</b></header>${judge.status === "Completed" ? `<p>${esc(judge.rationale)}</p><div><span>Customer ${judge.customer_fit}</span><span>Product ${judge.product_fit}</span><span>Signal ${judge.signal_support}</span></div>${judge.required_rm_checks?.length ? `<ul>${judge.required_rm_checks.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}` : `<p>${esc(judgeFailureMessage(judge))}</p>`}</article>`).join("")}</div>`
    : `<p class="review-off"><b>In-house review not run in this demo,</b> so the action keeps its rules score of ${evaluation.deterministic.score}. When switched on, the bank's own model checks ${esc(angles)}, using only the de-identified packet below, and the result becomes the lower of the two.</p>`;
  return `<div class="evaluation-heading"><div><span class="section-kicker">SECOND-LAYER REVIEW</span><h3>Model review of this action</h3></div><button class="action-button" data-run-evaluation="${index}">Run again</button></div>${ran ? `<div class="panel-consensus"><strong>${evaluation.consensus.score}/100</strong><div><b>${esc(evaluation.consensus.band)}</b><span>${esc(evaluation.consensus.rule)}</span></div></div>` : inHouse}<h4 class="evaluation-subtitle">Evidence coverage</h4><div class="dataset-scores">${Object.entries(evaluation.datasets).map(([name, lens]) => `<div><small>${esc(name)} dataset</small><b>${lens.score}/100</b><span>${esc(lens.detail)}</span></div>`).join("")}</div>${retrievedEvidence}${ran ? inHouse : ""}${modelPacketHTML(evaluation)}<p class="privacy-note">Names, IDs, nationality, the client's own words and RM notes never leave TESSERA. RM approval is still required.</p>`;
}

async function runIndependentEvaluation(client, index, button) {
  const originalPanel = $("#evaluation-panel");
  const reference = actionReference(client, index);
  button.disabled = true;
  button.textContent = "Evaluating…";
  try {
    const response = await fetch("/api/evaluations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: client.client_id, recommendation_index: index, ...reference }),
    });
    const payload = await response.json().catch(() => ({ error: `Evaluation service returned ${response.status}` }));
    if (response.status === 404) {
      throw new Error("Evaluation API unavailable. Start the project with python app.py (not a static file server), then refresh.");
    }
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    if (!await loadReviewState()) return;
    renderBook();
    if (state.currentView === "client") renderClient(state.currentClient);
    const panel = $("#evaluation-panel");
    if (!panel || panel !== originalPanel || $("#modal").hidden) return;
    const current = reviewedRecommendation(profiles()[client.client_id], index);
    if (current.version !== reference.version) return;
    panel.className = "evaluation-panel evaluation-results";
    panel.innerHTML = evaluationPanelHTML(current.evaluation || payload, index);
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
  const recommendation = reviewedRecommendation(client, index);
  const current = decisionFor(client.client_id, index);
  const value = recommendation.detail;
  openModal(`<span class="section-kicker">EDIT ACTION</span><h2>${esc(recommendation.title)}</h2><p>Changed wording is saved as an unassessed draft and cannot be approved. Restore the source-backed wording or request a source-backed alternative. Only case, whitespace and dash formatting changes preserve the assessment.</p><form id="edit-action-form" data-index="${index}"><label class="form-field"><span>Revised action</span><textarea name="note" maxlength="1000" rows="7" required>${esc(value)}</textarea></label><div class="modal-actions"><button type="button" class="small-button" data-close-modal>Cancel</button><button type="submit" class="action-button approve">Save revision</button></div></form>`);
}

function showApproveRecommendation(client, index) {
  const recommendation = reviewedRecommendation(client, index);
  const decision = decisionFor(client.client_id, index);
  const current = decision?.action === "approved" ? decision : null;
  openModal(`<span class="section-kicker">RM APPROVAL</span><h2>${esc(recommendation.title)}</h2><p>Record what you have done or will do for this client. Approval is written to the evidence ledger and does not place a trade.</p><form id="approve-action-form" data-index="${index}"><label class="form-field"><span>Action taken or agreed</span><textarea name="note" minlength="10" maxlength="1000" rows="6" required placeholder="Example: Confirmed the facility buffer with Credit and scheduled a client review before funding.">${esc(current?.note || "")}</textarea></label><div class="modal-actions"><button type="button" class="small-button" data-close-modal>Cancel</button><button type="submit" class="action-button approve">Approve and record</button></div></form>`);
}

function showDismissRecommendation(client, index) {
  const recommendation = reviewedRecommendation(client, index);
  openModal(`<span class="section-kicker">DISMISS SUGGESTION</span><h2>${esc(recommendation.title)}</h2><p>Record why this action is being dismissed. The reason is written to the evidence ledger and shapes future suggestions for this client.</p><form id="dismiss-action-form" data-index="${index}"><div class="dismiss-reasons" role="radiogroup" aria-label="Dismiss reason">
      ${[["Client declined the suggestion", "Saved as a client preference and steered away from"], ["Not now, revisit later", "Snoozed; it can return with a dated follow-up"], ["Suggestion is wrong", "Flagged for model/data review, not a client preference"], ["Already handled elsewhere", "Closes the topic and checks for stale data"]].map(([value, hint], reasonIndex) => `<label class="dismiss-reason"><input type="radio" name="reason" value="${esc(value)}" ${reasonIndex === 0 ? "checked" : ""} required><span><b>${esc(value)}</b><small>${esc(hint)}</small></span></label>`).join("")}
    </div><label class="form-field"><span>Optional context</span><textarea name="note" maxlength="1000" rows="3" placeholder="Anything the ledger should capture, such as what the client actually said."></textarea></label><div class="modal-actions"><button type="button" class="small-button" data-close-modal>Cancel</button><button type="submit" class="action-button dismiss">Dismiss and record reason</button></div></form>`, "risk");
}

async function requestAlternativeRecommendation(client, dismissedIndex, dismissedTitle) {
  const response = await fetch("/api/recommendations/alternate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: client.client_id, dismissed_index: dismissedIndex, ...actionReference(client, dismissedIndex) }),
  });
  const payload = await response.json().catch(() => ({ error: `Recommendation service returned ${response.status}` }));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  payload.recommendation.replacement_for = dismissedTitle;
  await loadReviewState();
  return payload.recommendation;
}

async function persistDecision(client, index, action, note = "") {
  const response = await fetch("/api/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: client.client_id, recommendation_index: index, action, note, ...actionReference(client, index) }),
  });
  const payload = await response.json().catch(() => ({ error: `Decision service returned ${response.status}` }));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  try {
    if (!await loadReviewState()) return;
  } catch (error) {
    throw new Error(`Decision saved, but the review could not reload. Refresh the page. ${error.message}`);
  }
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
    if (!event.target.closest("#chat-client-picker")) toggleChatClientPicker(false);
    if (event.target.closest("#chat-client")) {
      toggleChatClientPicker($("#chat-client-menu").hidden);
      return;
    }
    const clientOption = event.target.closest("[data-chat-client]");
    if (clientOption) {
      syncChatContext(clientOption.dataset.chatClient);
      $("#chat-client").focus();
      return;
    }
    const chatInteraction = event.target.closest("#chat-panel, #chat-launcher, #chat-delete-dialog");
    if (!$("#chat-panel").hidden && !chatInteraction) toggleChat(false);
    if (event.target.closest("#chat-launcher")) toggleChat();
    if (event.target.closest("#chat-close")) toggleChat(false);
    if (event.target.closest("#chat-expand")) toggleChatExpanded();
    if (event.target.closest("#chat-delete")) return deleteChatConversation();
    if (event.target.closest("#chat-delete-cancel, [data-chat-delete-cancel]")) return cancelChatDeletion();
    if (event.target.closest("#chat-delete-confirm")) return confirmChatDeletion();
    const prompt = event.target.closest("[data-chat-prompt]");
    if (prompt) {
      $("#chat-input").value = prompt.dataset.chatPrompt;
      $("#chat-input").focus();
    }
    if (event.target.closest("#chat-mic")) startDictation();
    const speak = event.target.closest("[data-speak-message]");
    if (speak) {
      const message = chatConversation().messages[Number(speak.dataset.speakMessage)];
      if (message?.role === "assistant") {
        if (message === state.chatSpeechMessage) toggleChatAudio();
        else speakAnswer(message);
      }
    }
    const citation = event.target.closest("[data-chat-citation]");
    if (citation) {
      const article = citation.closest(".chat-message");
      const source = article.querySelector(`#${citation.dataset.chatCitation}`);
      if (source) {
        article.querySelector(".chat-sources").open = true;
        source.scrollIntoView({ block: "nearest", behavior: "smooth" });
        source.focus({ preventScroll: true });
      }
    }
    const breachReview = event.target.closest("[data-escalation-review]");
    if (breachReview) {
      event.preventDefault();
      breachReview.disabled = true;
      try {
        await requestJson("/api/escalations/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: breachReview.dataset.client, escalation_id: breachReview.dataset.escalation, decision: breachReview.dataset.escalationReview }),
        });
        if (await loadReviewState()) {
          renderBook();
          applyRoute();
        }
        showToast(breachReview.dataset.escalationReview === "confirmed" ? "Exposure confirmed and recorded" : "Exposure dismissed and recorded");
      } catch (error) {
        breachReview.disabled = false;
        showToast(error.message, "error");
      }
      return;
    }
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
      } else if (action === "dismissed") {
        showDismissRecommendation(client, index);
      } else {
        state.dismissedListOpen = action === "pending" && decisionButton.closest(".dismissed-list")?.open === true;
        try {
          await persistDecision(client, index, action, decisionFor(client.client_id, index)?.note || "");
          showToast(action === "approved" ? "Action approved and written to the decision ledger." : "Action restored to the active review.");
        } catch (error) {
          decisionButton.disabled = false;
          showToast(error.message, "error");
        }
      }
    }

    const acknowledgeButton = event.target.closest("[data-urgency-acknowledge]");
    if (acknowledgeButton) {
      await acknowledgeUrgencyAlert(acknowledgeButton.dataset.urgencyAcknowledge, acknowledgeButton);
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
    if (event.target.closest("[data-clear-event-filters]")) {
      state.eventFilters = { from: "", to: "", sort: "newest", severity: "all", source: "all" };
      renderMarketEvents();
    }
    if (event.target.closest("[data-clear-client-search]")) {
      state.clientSearch = "";
      const input = $("[data-client-search]");
      input.value = "";
      renderClientSearchResults();
      input.focus();
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-studio-client]")) {
      state.studioClient = event.target.value;
      state.studioScenario = 0;
      state.studioScale = 100;
      history.replaceState({ view: "scenario", clientId: state.studioClient }, "", routeFor("scenario", state.studioClient));
      renderScenarioStudio();
    }
    if (event.target.matches("[data-event-from]")) {
      state.eventFilters.from = event.target.value;
      renderMarketEvents();
    }
    if (event.target.matches("[data-event-to]")) {
      state.eventFilters.to = event.target.value;
      renderMarketEvents();
    }
    if (event.target.matches("[data-event-sort]")) {
      state.eventFilters.sort = event.target.value;
      renderMarketEvents();
    }
    if (event.target.matches("[data-event-severity]")) {
      state.eventFilters.severity = event.target.value;
      renderMarketEvents();
    }
    if (event.target.matches("[data-event-source]")) {
      state.eventFilters.source = event.target.value;
      renderMarketEvents();
    }
  });

  document.addEventListener("input", (event) => {
    if (event.target.matches("#chat-client-search")) renderChatClientOptions();
    if (event.target.matches("[data-client-search]")) {
      state.clientSearch = event.target.value;
      renderClientSearchResults();
    }
    if (event.target.matches("[data-scenario-scale]")) {
      state.studioScale = Number(event.target.value);
      $("#studio-scenario-output").innerHTML = scenarioHTML(profiles()[state.studioClient], state.studioScenario, state.studioScale, true);
    }
  });

  document.addEventListener("focusin", (event) => {
    if (!event.target.closest("#chat-client-picker")) toggleChatClientPicker(false);
    const chartPoint = event.target.closest("[data-chart-point]");
    if (chartPoint) showChartPoint(chartPoint);
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("#chat-client-search")) handleChatClientKeydown(event);
    if (event.target.matches("#chat-client") && ["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      toggleChatClientPicker(true);
    }
    if (event.target.matches("#chat-input") && event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      event.target.form?.requestSubmit();
    }
  });

  document.addEventListener("mouseover", (event) => {
    const chartPoint = event.target.closest("[data-chart-point]");
    if (chartPoint) showChartPoint(chartPoint);
  });

  document.addEventListener("submit", async (event) => {
    if (event.target.matches("#chat-form")) {
      event.preventDefault();
      const input = $("#chat-input");
      const question = input.value.trim();
      if (!question || chatConversation().request) return;
      input.value = "";
      await sendChatQuestion(question);
      return;
    }
    if (!event.target.matches("#edit-action-form, #approve-action-form, #dismiss-action-form")) return;
    event.preventDefault();
    const form = event.target;
    const client = profiles()[state.currentClient];
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      let action = "edited";
      let note = new FormData(form).get("note") || "";
      if (form.matches("#approve-action-form")) {
        action = "approved";
      } else if (form.matches("#dismiss-action-form")) {
        action = "dismissed";
        const reason = String(new FormData(form).get("reason") || "");
        note = note ? `Reason: ${reason}. ${note}` : `Reason: ${reason}`;
        state.pendingDeclinedIndex = reason.startsWith("Client declined") ? Number(form.dataset.index) : null;
      }
      await persistDecision(profiles()[state.currentClient], Number(form.dataset.index), action, note);
      closeModal();
      showToast(action === "approved" ? "Action approved with the RM action recorded." : action === "dismissed" ? (state.pendingDeclinedIndex != null ? "Client preference recorded. Checking for one alternative." : "Dismissal recorded with its reason.") : "Revision saved to the decision ledger.");
      if (action === "dismissed" && state.pendingDeclinedIndex != null) {
        // Decline chain rule: a suggestion declined for the FIRST time always
        // produces one new suggestion (A -> B -> C ...). Only re-dismissing a
        // suggestion that was already declined before yields nothing, so the
        // list can never flood no matter how often the RM cycles.
        const dismissedIndex = state.pendingDeclinedIndex;
        state.pendingDeclinedIndex = null;
        const dismissedTitle = client.recommendations[dismissedIndex]?.title;
        const justRecordedId = state.decisions.records.at(-1)?.id;
        const declinedTitles = new Set(state.decisions.records
          .filter((record) => (
            record.id !== justRecordedId
            && record.client_id === client.client_id
            && record.action === "dismissed"
            && String(record.note || "").startsWith("Reason: Client declined")
          ))
          .map((record) => record.recommendation_title));
        if (dismissedTitle && !declinedTitles.has(dismissedTitle)) {
          try {
            const replacement = await requestAlternativeRecommendation(client, dismissedIndex, dismissedTitle);
            renderClient(state.currentClient);
            showToast(`How about this instead? ${replacement.title}`);
          } catch (replacementError) {
            console.warn("No alternative available:", replacementError);
            showToast("No replacement suggestion is available for this action.", "error");
          }
        } else if (dismissedTitle) {
          showToast("This suggestion was already declined before, so no duplicate replacement was created.");
        }
      }
    } catch (error) {
      submit.disabled = false;
      showToast(error.message, "error");
    }
  });

  $("#method-button").addEventListener("click", showMethod);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.defaultPrevented) {
      if (!$("#chat-client-menu").hidden) {
        event.preventDefault();
        toggleChatClientPicker(false, true);
        return;
      }
      if ($("#chat-delete-dialog").open) return;
      if (!$("#modal").hidden) closeModal();
      else if (!$("#chat-panel").hidden) toggleChat(false);
    }
  });
  $("#chat-delete-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    cancelChatDeletion();
  });
  window.addEventListener("popstate", applyRoute);
}

async function requestJson(url, options = {}, attempts = 2) {
  const canRetry = !options.method || options.method.toUpperCase() === "GET";
  const limit = canRetry ? attempts : 1;
  for (let attempt = 0; attempt < limit; attempt += 1) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (attempt === limit - 1) throw error;
    }
    if (response?.ok) return response.json();
    if (response && (response.status < 500 || attempt === limit - 1)) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `${url} returned ${response.status}`);
    }
    await new Promise(resolve => window.setTimeout(resolve, 250));
  }
}

async function refreshMarketNewsInBackground() {
  try {
    const result = await requestJson("/api/market-news/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (result.intelligence && state.data) {
      if (!await loadReviewState()) return;
      $("#as-of").textContent = fullDate(state.data.meta.as_of);
      renderBook();
      renderGovernance();
      applyRoute();
      if (result.urgency_alerts?.status === "unavailable") showToast(result.urgency_alerts.reason, "error");
    }
  } catch (error) {
    console.warn("Market-news refresh failed", error);
  }
}

async function loadReviewState() {
  const generation = ++state.reviewGeneration;
  const context = await requestJson("/api/review");
  if (generation !== state.reviewGeneration) return false;
  state.data = context.intelligence;
  state.decisions = context.decisions;
  return true;
}

async function init() {
  try {
    await loadReviewState();
    const focusClients = Object.keys(state.data.featured_clients);
    state.currentClient = focusClients[0] || Object.keys(profiles())[0];
    state.studioClient = focusClients.at(-1) || state.currentClient;
    syncChatContext();
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
    refreshMarketNewsInBackground();
    window.setInterval(() => { if (state.data) renderBook(); }, 60_000);
  } catch (error) {
    $("#loading").innerHTML = `<p>Unable to load current portfolio records.</p><small>${esc(error.message)}</small><button class="ghost-button" onclick="window.location.reload()">Retry</button>`;
  }
}

init();