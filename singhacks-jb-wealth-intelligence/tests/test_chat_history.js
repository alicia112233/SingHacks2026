const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

// Exercise the browser's real chat functions with isolated storage and a small DOM.
const source = fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8")
  .replace(/\binit\(\);\s*$/, "");

function browser(storage = new Map(), rm = "Test RM") {
  const elements = new Map();
  const documentListeners = new Map();
  function element() {
    return {
      children: [], options: [1], value: "", hidden: false, checked: false, open: false,
      disabled: false, textContent: "", dataset: {}, scrollHeight: 100,
      listeners: new Map(),
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
      classList: { add() {}, remove() {} },
      focus() { context.document.activeElement = this; },
      showModal() { this.returnFocus = context.document.activeElement; this.open = true; },
      close() { this.open = false; this.returnFocus?.focus(); },
      addEventListener(type, listener) { this.listeners.set(type, listener); },
      set innerHTML(value) { this.html = value; this.children = []; },
      get innerHTML() { return this.html || ""; },
      append(child) { this.children.push(child); },
      querySelector(selector) { return select(selector); },
    };
  }
  function select(selector) {
    if (!elements.has(selector)) elements.set(selector, element());
    return elements.get(selector);
  }
  const context = vm.createContext({
    AbortController, URL, console,
    document: { querySelector: select, createElement: element, addEventListener: (type, listener) => {
      if (!documentListeners.has(type)) documentListeners.set(type, []);
      documentListeners.get(type).push(listener);
    } },
    window: {
      localStorage: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: (key) => storage.delete(key),
      },
      confirm: () => { throw new Error("Browser confirmation must not be used"); },
      addEventListener() {},
      clearTimeout() {}, setTimeout() {},
      speechSynthesis: { cancel() {} },
    },
  });
  vm.runInContext(source, context);
  const run = (code) => vm.runInContext(code, context);
  context.testRm = rm;
  run(`state.data = { meta: { rm: testRm }, client_profiles: {
    A: { client_id: "A", name: "Client A" },
    B: { client_id: "B", name: "Client B" },
  }}; syncChatContext("A");`);
  return { context, run, select, storage, documentListeners };
}

function deferredReply(browser, answer = "Answer for A") {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  const requests = [];
  browser.context.fetch = (_url, options) => {
    requests.push(options);
    return promise;
  };
  return {
    requests,
    resolve: () => resolve({ ok: true, status: 200, json: async () => ({
      answer, mode: "grounded_extract", citations: [],
    }) }),
    reject,
  };
}

test("each client's full transcript and citations survive switching and reloads", () => {
  const app = browser();
  app.run(`
    for (let index = 0; index < 16; index++) addChatMessage("A", "user", "Question " + index);
    addChatMessage("A", "assistant", "A cited answer [1]", { mode: "grounded_model", citations: [
      { number: 1, source: "Recorded holdings", excerpt: "Original evidence", source_url: "https://example.com/evidence" }
    ] });
    syncChatContext("B");
    addChatMessage("B", "user", "B's separate question");
    syncChatContext("A");
  `);
  assert.equal(app.select("#chat-messages").children.length, 17);
  assert.match(app.select("#chat-messages").children.at(-1).innerHTML, /Original evidence/);
  assert.match(app.select("#chat-messages").children.at(-1).innerHTML, /From client records/);
  const reloaded = browser(app.storage);
  assert.equal(reloaded.select("#chat-messages").children.length, 17);
  assert.match(reloaded.select("#chat-messages").children.at(-1).innerHTML, /https:\/\/example.com\/evidence/);
  reloaded.run('syncChatContext("B")');
  assert.equal(reloaded.select("#chat-messages").children.length, 1);
  assert.match(reloaded.select("#chat-messages").children[0].innerHTML, /B&#039;s separate question/);
  const otherRm = browser(app.storage, "Another RM");
  assert.equal(otherRm.run("chatConversation().messages.length"), 0);
});

test("a delayed reply stays with its original client while another client is selected", async () => {
  const app = browser();
  app.run('addChatMessage("B", "user", "B history")');
  const reply = deferredReply(app);
  const sending = app.run('sendChatQuestion("A question")');
  assert.equal(app.select(".chat-send").disabled, true);
  app.select("#chat-input").value = "A draft";
  app.run('syncChatContext("B")');
  assert.equal(app.select("#chat-input").value, "");
  assert.equal(app.select(".chat-send").disabled, false);
  reply.resolve();
  await sending;
  assert.equal(JSON.parse(reply.requests[0].body).client_id, "A");
  assert.equal(app.run('chatConversation("B").messages.length'), 1);
  assert.doesNotMatch(app.select("#chat-messages").children[0].innerHTML, /Answer for A/);
  app.run('syncChatContext("A")');
  assert.match(app.select("#chat-messages").children.at(-1).innerHTML, /Answer for A/);
  assert.equal(app.select(".chat-send").disabled, false);
});

test("pending state is restored on return and duplicate sends are ignored", async () => {
  const app = browser();
  const reply = deferredReply(app);
  const sending = app.run('sendChatQuestion("A question")');
  await app.run('sendChatQuestion("Duplicate")');
  app.run('syncChatContext("B"); syncChatContext("A")');
  assert.equal(app.select(".chat-send").disabled, true);
  assert.equal(reply.requests.length, 1);
  assert.equal(app.run("chatConversation().messages.length"), 1);
  reply.resolve();
  await sending;
  assert.equal(app.select(".chat-send").disabled, false);
});

test("overlapping client requests can finish in reverse order without changing the other's controls", async () => {
  const app = browser();
  const replyA = deferredReply(app, "A answer");
  const sendingA = app.run('sendChatQuestion("A question")');
  app.run('syncChatContext("B")');
  const replyB = deferredReply(app, "B answer");
  const sendingB = app.run('sendChatQuestion("B question")');
  replyB.resolve();
  await sendingB;
  app.run('syncChatContext("A")');
  assert.equal(app.select(".chat-send").disabled, true);
  replyA.resolve();
  await sendingA;
  assert.equal(app.run('chatConversation("A").messages[1].content'), "A answer");
  assert.equal(app.run('chatConversation("B").messages[1].content'), "B answer");
  assert.equal(app.select(".chat-send").disabled, false);
});

test("navigating between client review pages restores the matching conversation", () => {
  const app = browser();
  app.context.document.querySelectorAll = () => [];
  app.context.window.scrollTo = () => {};
  app.context.history = { pushState() {} };
  app.run(`
    renderClient = () => {};
    addChatMessage("A", "user", "A review history");
    addChatMessage("B", "user", "B review history");
    showView("client", "B");
  `);
  assert.equal(app.select("#chat-client").value, "B");
  assert.match(app.select("#chat-messages").children[0].innerHTML, /B review history/);
  app.run('showView("client", "A")');
  assert.equal(app.select("#chat-client").value, "A");
  assert.match(app.select("#chat-messages").children[0].innerHTML, /A review history/);
});

test("deletion is client-scoped and a late reply cannot restore deleted history", async () => {
  const app = browser();
  app.run('addChatMessage("B", "user", "Keep B")');
  const reply = deferredReply(app);
  const sending = app.run('sendChatQuestion("Delete A")');
  app.run("deleteChatConversation(); confirmChatDeletion()");
  assert.equal(reply.requests[0].signal.aborted, true);
  assert.equal(app.run("chatConversation().messages.length"), 0);
  assert.equal(app.select("#chat-delete").disabled, true);
  assert.equal(app.storage.has(app.run('chatStorageKey("A")')), false);
  reply.resolve();
  await sending;
  assert.equal(app.storage.has(app.run('chatStorageKey("A")')), false);
  const reloaded = browser(app.storage);
  assert.equal(reloaded.run("chatConversation().messages.length"), 0);
  reloaded.run('syncChatContext("B")');
  assert.equal(reloaded.run("chatConversation().messages[0].content"), "Keep B");
});

test("a new conversation can start immediately after deletion without a stale reply changing it", async () => {
  const app = browser();
  const oldReply = deferredReply(app, "Deleted answer");
  const oldSending = app.run('sendChatQuestion("Old question")');
  app.run("deleteChatConversation(); confirmChatDeletion()");
  const newReply = deferredReply(app, "New answer");
  const newSending = app.run('sendChatQuestion("New question")');
  oldReply.resolve();
  await oldSending;
  assert.equal(app.select(".chat-send").disabled, true);
  newReply.resolve();
  await newSending;
  assert.equal(app.run("chatConversation().messages.length"), 2);
  assert.equal(app.run("chatConversation().messages[1].content"), "New answer");
});

test("canceling deletion keeps the saved conversation", () => {
  const app = browser();
  app.run('addChatMessage("A", "user", "Keep this")');
  const before = [...app.storage.entries()];
  app.run("deleteChatConversation()");
  assert.equal(app.select("#chat-delete-dialog").open, true);
  assert.equal(app.select("#chat-delete-client-name").textContent, "Client A (A)");
  assert.equal(app.context.document.activeElement, app.select("#chat-delete-cancel"));
  assert.deepEqual([...app.storage.entries()], before);
  app.run("cancelChatDeletion(); confirmChatDeletion()");
  assert.equal(app.select("#chat-delete-dialog").open, false);
  assert.deepEqual([...app.storage.entries()], before);
  assert.equal(app.run("chatConversation().messages.length"), 1);
});

test("request errors stay with the original client and restore the send control", async () => {
  const app = browser();
  const reply = deferredReply(app);
  const sending = app.run('sendChatQuestion("A question")');
  app.run('syncChatContext("B")');
  reply.reject(new Error("Network offline"));
  await sending;
  assert.equal(app.run('chatConversation("B").messages.length'), 0);
  app.run('syncChatContext("A")');
  assert.equal(app.select(".chat-send").disabled, false);
  assert.match(app.select("#chat-messages").children.at(-1).innerHTML, /Assistant unavailable.*Network offline/);
});

test("corrupt or unavailable storage does not break chat and failed saves/deletions are reported", () => {
  const storage = new Map([["tessera.chat.v1:Test%20RM:A", "invalid json"]]);
  const app = browser(storage);
  assert.equal(app.run("chatConversation().messages.length"), 0);
  app.context.window.localStorage.setItem = () => { throw new Error("Quota exceeded"); };
  app.run('addChatMessage("A", "user", "In-memory question"); syncChatContext("B"); syncChatContext("A")');
  assert.equal(app.run("chatConversation().messages[0].content"), "In-memory question");
  assert.match(app.select("#chat-storage-status").textContent, /session only/);
  app.context.window.localStorage.removeItem = () => { throw new Error("Storage blocked"); };
  app.run("deleteChatConversation(); confirmChatDeletion()");
  assert.equal(app.run("chatConversation().messages.length"), 0);
  assert.match(app.select("#toast").textContent, /could not be deleted/);
});

test("switching clients or closing chat cancels deletion and a stale confirmation cannot delete another client", () => {
  const app = browser();
  app.run('addChatMessage("A", "user", "Keep A"); addChatMessage("B", "user", "Keep B")');
  const before = [...app.storage.entries()];
  app.run('deleteChatConversation(); syncChatContext("B"); confirmChatDeletion()');
  assert.equal(app.select("#chat-delete-dialog").open, false);
  assert.deepEqual([...app.storage.entries()], before);
  app.run('deleteChatConversation(); toggleChat(false); confirmChatDeletion()');
  assert.equal(app.select("#chat-delete-dialog").open, false);
  assert.deepEqual([...app.storage.entries()], before);
});

test("dialog Escape cancels safely and the in-app delete button requires explicit confirmation", async () => {
  const app = browser();
  app.run('addChatMessage("A", "user", "Keep until confirmed"); bindEvents(); deleteChatConversation()');
  const escape = { key: "Escape", target: { matches: () => false }, preventDefault() {} };
  app.documentListeners.get("keydown").forEach((listener) => listener(escape));
  assert.equal(app.select("#chat-panel").hidden, false);
  let prevented = false;
  app.select("#chat-delete-dialog").listeners.get("cancel")({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(app.select("#chat-delete-dialog").open, false);
  assert.equal(app.run("chatConversation().messages.length"), 1);
  app.run("deleteChatConversation()");
  const target = { closest: (selector) => selector.split(/,\s*/).includes("#chat-delete-confirm")
    || selector.includes("#chat-delete-dialog") ? target : null };
  await app.documentListeners.get("click")[0]({ target });
  assert.equal(app.select("#chat-delete-dialog").open, false);
  assert.equal(app.run("chatConversation().messages.length"), 0);
  assert.equal(app.context.document.activeElement, app.select("#chat-input"));
});

test("requests include only the selected client's last six messages", async () => {
  const app = browser();
  app.run(`
    addChatMessage("B", "user", "Other client history");
    for (let index = 0; index < 8; index++) addChatMessage("A", "user", "A " + index);
  `);
  const reply = deferredReply(app);
  const sending = app.run('sendChatQuestion("Next question")');
  const body = JSON.parse(reply.requests[0].body);
  assert.deepEqual(body.history.map((item) => item.content), ["A 2", "A 3", "A 4", "A 5", "A 6", "A 7"]);
  reply.resolve();
  await sending;
});

test("saved messages are rendered as text and unsafe source links are excluded", () => {
  const storage = new Map([["tessera.chat.v1:Test%20RM:A", JSON.stringify({
    version: 1, clientId: "A", messages: [
      null, { role: "system", content: "invalid role" },
      { role: "assistant", content: "<script>alert(1)</script>", citations: [null, {
        number: '<img src=x onerror="alert(1)">', source: "<b>source</b>",
        excerpt: "Evidence", source_url: "javascript:alert(1)",
      }] },
    ],
  })]]);
  const app = browser(storage);
  const html = app.select("#chat-messages").children[0].innerHTML;
  assert.equal(app.run("chatConversation().messages.length"), 1);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<script>|<img|href=/);
});

test("summaries render paragraphs, collapsed sources and citation buttons tied to the right message", () => {
  const app = browser();
  app.run(`
    addChatMessage("A", "assistant", "Cash is approximately USD 1.71m. [1]\\n\\nThe confirmed need is EUR 3.4m. [2]", {
      mode: "grounded_summary", citations: [
        { number: 1, source: "Holdings", excerpt: "Original cash evidence" },
        { number: 2, source: "Cash needs", excerpt: "Original need evidence" },
      ],
    });
    addChatMessage("A", "assistant", "A different answer [1].", {
      mode: "grounded_summary", citations: [{ number: 1, source: "Other source", excerpt: "Other evidence" }],
    });
  `);
  const first = app.select("#chat-messages").children[0].innerHTML;
  const second = app.select("#chat-messages").children[1].innerHTML;
  assert.match(first, /<span>Summary<\/span>/);
  assert.match(first, /<\/p><p>The confirmed need/);
  assert.match(first, /aria-label="View source 2"/);
  assert.match(first, /<details class="chat-sources">/);
  assert.doesNotMatch(first, /<details[^>]*\bopen\b/);
  const target = /data-chat-citation="([^"]+)"/.exec(first)[1];
  assert.ok(first.includes(`id="${target}"`));
  assert.ok(!second.includes(`id="${target}"`));
});
