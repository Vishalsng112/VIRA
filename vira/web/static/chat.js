const state = {
  conversations: [],
  conversationId: null,
  incognito: false,
  username: "User",
  sending: false,
  agentId: "",
  search: "",
  abort: null,
  retryRunId: null,
  canSelectModel: false,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: "include", ...options });
  if (response.status === 401) {
    window.location.href = "/login";
    return null;
  }
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new Error(data?.detail || `Request failed (${response.status})`);
  }
  return data;
}

function newIdempotencyKey() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setStatus(message = "", error = false) {
  const element = $("#conversation-status");
  element.textContent = message;
  element.classList.toggle("error", error);
}

async function loadCurrentUser() {
  try {
    const principal = await api("/api/v1/auth/me");
    if (principal?.username) {
      state.username = principal.username;
    }
  } catch (error) {
    setStatus(error.message, true);
  }
}

function messageAuthor(role) {
  return role === "assistant" ? "VIRA" : state.username;
}

function userInitial() {
  return (state.username.trim().charAt(0) || "U").toUpperCase();
}

// ---- Markdown rendering (safe: everything is HTML-escaped first) -----------
function inlineMd(text) {
  const codes = [];
  let t = escapeHtml(text);
  t = t.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  t = t.replace(/\*\*([^*\n]+?)\*\*|__([^_\n]+?)__/g, (_, a, b) => `<strong>${a || b}</strong>`);
  t = t.replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?![*\w])/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_\w])_([^_\s][^_\n]*?)_(?![_\w])/g, "$1<em>$2</em>");
  t = t.replace(/~~([^~\n]+?)~~/g, "<del>$1</del>");
  t = t.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g,
    '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
}

function buildList(items, start) {
  const base = items[start].indent;
  const tag = items[start].ordered ? "ol" : "ul";
  let html = `<${tag}>`;
  let i = start;
  while (i < items.length && items[i].indent >= base) {
    if (items[i].indent > base) {
      const [sub, next] = buildList(items, i);
      html = html.endsWith("</li>") ? html.slice(0, -5) + sub + "</li>" : html + sub;
      i = next;
      continue;
    }
    html += `<li>${inlineMd(items[i].text)}</li>`;
    i++;
  }
  return [html + `</${tag}>`, i];
}

function splitTableRow(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

function renderMarkdown(source) {
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  const listRe = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  const isBlockStart = (l) => /^(#{1,6})\s/.test(l) || /^\s*(```|>|[-*_]{3,}\s*$)/.test(l) || listRe.test(l);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    const fence = line.match(/^\s*```\s*([\w+-]*)/);
    if (fence) {
      const code = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
      i++;
      out.push(`<div class="code-block"><div class="code-head"><span>${escapeHtml(fence[1] || "code")}</span>` +
        `<button type="button" class="code-copy" data-copy>Copy</button></div>` +
        `<pre><code>${escapeHtml(code.join("\n"))}</code></pre></div>`);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (heading) {
      out.push(`<h${heading[1].length}>${inlineMd(heading[2])}</h${heading[1].length}>`);
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(quote.join("\n"))}</blockquote>`);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      const head = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(splitTableRow(lines[i++]));
      out.push('<div class="table-wrap"><table><thead><tr>' +
        head.map((c) => `<th>${inlineMd(c)}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + head.map((_, k) => `<td>${inlineMd(r[k] || "")}</td>`).join("") + "</tr>").join("") +
        "</tbody></table></div>");
      continue;
    }
    if (listRe.test(line)) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(listRe);
        if (!m) break;
        items.push({ indent: m[1].replace(/\t/g, "    ").length, ordered: /\d/.test(m[2]), text: m[3] });
        i++;
      }
      let pos = 0;
      while (pos < items.length) {
        const [html, next] = buildList(items, pos);
        out.push(html);
        pos = next;
      }
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && (para.length === 0 || !isBlockStart(lines[i]))) para.push(lines[i++]);
    out.push(`<p>${para.map(inlineMd).join("<br>")}</p>`);
  }
  return out.join("");
}

// ---- Agent activity trace ("what is the agent doing") ----------------------
function buildTrace(events) {
  const items = [];
  const byId = new Map();
  let label = "Thinking";
  for (const e of events || []) {
    if (e.type === "status") label = e.label || label;
    else if (e.type === "thought") items.push({ kind: "thought", text: e.text, agent: e.agent });
    else if (e.type === "check") items.push({ kind: "check", text: e.text, level: e.level });
    else if (e.type === "tool_start") {
      const item = { kind: "tool", id: e.id, tool: e.tool, params: e.params || {}, agent: e.agent, state: "running" };
      byId.set(e.id, item);
      items.push(item);
      label = `Using ${e.tool}`;
    } else if (e.type === "tool_end") {
      const item = byId.get(e.id);
      if (item) Object.assign(item, { state: e.ok ? "ok" : "error", ms: e.ms, preview: e.preview });
    }
  }
  const stamps = (events || []).map((e) => e.ts).filter(Boolean);
  const seconds = stamps.length > 1 ? Math.max(1, Math.round(stamps[stamps.length - 1] - stamps[0])) : 0;
  return { items, label, seconds };
}

function toolSummary(params) {
  const first = Object.values(params || {})[0];
  return first == null ? "" : String(first).replace(/\s+/g, " ").slice(0, 90);
}

function renderTrace(live) {
  const { items, label, seconds } = buildTrace(live.events);
  if (!live.running && !items.length) return "";
  const tools = items.filter((item) => item.kind === "tool").length;
  const summary = live.running
    ? `${escapeHtml(label)}…`
    : `Worked for ${seconds || 1}s${tools ? ` · ${tools} tool call${tools > 1 ? "s" : ""}` : ""}`;
  const body = items.map((item, index) => {
    const who = item.agent ? `<span class="trace-agent">${escapeHtml(item.agent)}</span>` : "";
    if (item.kind === "thought") {
      return `<div class="trace-item thought"><span class="trace-icon">◌</span><div>${who}<div class="trace-text">${escapeHtml(item.text)}</div></div></div>`;
    }
    if (item.kind === "check") {
      return `<div class="trace-item check"><span class="trace-icon">⚠</span><div>${who}<div class="trace-text">${escapeHtml(item.text)}</div></div></div>`;
    }
    const icon = item.state === "running" ? '<span class="trace-spinner"></span>' : item.state === "ok" ? "✓" : "✕";
    const open = live.openTools.has(index);
    return `<div class="trace-item tool ${item.state}">
      <span class="trace-icon">${icon}</span>
      <div class="trace-tool">
        <button type="button" class="trace-tool-head" data-trace-tool="${index}">
          ${who}<strong>${escapeHtml(item.tool)}</strong>
          <span class="trace-arg">${escapeHtml(toolSummary(item.params))}</span>
          ${item.ms != null ? `<span class="trace-ms">${item.ms >= 1000 ? (item.ms / 1000).toFixed(1) + "s" : item.ms + "ms"}</span>` : ""}
        </button>
        ${open ? `<div class="trace-detail"><div class="trace-label">Input</div><pre>${escapeHtml(JSON.stringify(item.params, null, 2))}</pre>${
          item.preview != null ? `<div class="trace-label">Result</div><pre>${escapeHtml(item.preview)}</pre>` : ""}</div>` : ""}
      </div>
    </div>`;
  }).join("");
  return `<div class="trace ${live.running ? "running" : ""}">
    <button type="button" class="trace-summary" data-trace-toggle>
      ${live.running ? '<span class="trace-spinner"></span>' : '<span class="trace-chevron">›</span>'}
      <span>${summary}</span>
      ${live.running ? "" : `<span class="trace-chevron ${live.open ? "open" : ""}">⌄</span>`}
    </button>
    ${live.open && items.length ? `<div class="trace-body">${body}</div>` : ""}
  </div>`;
}

function newLive(events = [], running = false) {
  return { events, running, open: running, openTools: new Set() };
}

// ---- Auto-scroll that follows new content unless the user scrolled up -------
let pinnedToBottom = true;
function follow(force = false) {
  const scroller = $("#message-scroller");
  if (force) pinnedToBottom = true;
  if (pinnedToBottom) scroller.scrollTop = scroller.scrollHeight;
}

function assistantArticle({ answer = "", live = null, error = false } = {}) {
  const article = document.createElement("article");
  article.className = "message assistant";
  article.innerHTML = `
    <div class="message-avatar">${error ? "!" : "V"}</div>
    <div class="message-content">
      <div class="message-role">${error ? "error" : "VIRA"}</div>
      <div class="trace-slot"></div>
      <div class="answer md"></div>
    </div>`;
  const setTrace = () => {
    article.querySelector(".trace-slot").innerHTML = live ? renderTrace(live) : "";
  };
  article._live = live;
  article._setTrace = setTrace;
  setTrace();
  if (error) article.querySelector(".answer").textContent = answer;
  else article.querySelector(".answer").innerHTML = renderMarkdown(answer);
  return article;
}

function userArticle(content) {
  const article = document.createElement("article");
  article.className = "message user";
  article.innerHTML = `
    <div class="message-avatar">${escapeHtml(userInitial())}</div>
    <div class="message-content">
      <div class="message-role">${escapeHtml(state.username)}</div>
      <div class="user-text">${escapeHtml(content)}</div>
    </div>`;
  return article;
}

// ---- Failure recovery: retry, inspect, or switch model ---------------------
function errorArticle({ detail, nextSteps = [], runId = null, message = "" }) {
  const article = document.createElement("article");
  article.className = "message assistant";
  article.innerHTML = `
    <div class="message-avatar">!</div>
    <div class="message-content">
      <div class="message-role">error</div>
      <div class="answer"></div>
      <div class="recovery">
        <p class="recovery-title">What to do next</p>
        <p class="recovery-hint">Your message is preserved. Retry it, inspect the run, or switch to another model.</p>
        <div class="recovery-actions">
          <button type="button" class="primary" data-recovery-retry>Retry</button>
          <button type="button" data-recovery-switch>Switch model &amp; retry</button>
          ${runId ? '<button type="button" data-recovery-details>Show what failed</button>' : ""}
        </div>
        <div class="recovery-models" hidden></div>
        <div class="recovery-details" hidden></div>
      </div>
    </div>`;
  article.querySelector(".answer").textContent = detail || "The request failed.";
  const steps = article.querySelector(".recovery-details");
  if (nextSteps.length) {
    steps.innerHTML = `<p class="recovery-title">Suggested steps</p><ol>${
      nextSteps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>`;
  }
  return article;
}

async function showRunDetails(article, runId, detailsBox) {
  detailsBox.hidden = false;
  detailsBox.innerHTML = '<p class="recovery-hint">Loading the run trace…</p>';
  try {
    const data = await api(`/api/v1/runs/${encodeURIComponent(runId)}/events?limit=80`);
    const events = data.events || [];
    const lines = events.map((event) => {
      const payload = event.data || {};
      if (event.event_type === "tool_start") return `→ ${payload.tool || "tool"} ${payload.params ? JSON.stringify(payload.params) : ""}`;
      if (event.event_type === "tool_end") return `  ${payload.ok === false ? "✗" : "✓"} ${payload.tool || "tool"}${payload.ms != null ? ` (${payload.ms} ms)` : ""}`;
      if (event.event_type === "check") return `! ${payload.text || "check"}`;
      if (event.event_type === "status") return `… ${payload.label || "status"}`;
      if (event.event_type === "thought") return `◌ ${payload.text || "thought"}`;
      return `${event.event_type}`;
    });
    detailsBox.innerHTML = lines.length
      ? `<p class="recovery-title">Run trace</p><pre>${escapeHtml(lines.join("\n"))}</pre>`
      : '<p class="recovery-hint">No run events were recorded for this failure.</p>';
  } catch (error) {
    detailsBox.innerHTML = `<p class="recovery-hint">Could not load the trace: ${escapeHtml(error.message)}</p>`;
  }
}

async function showModelPicker(article, modelsBox, onSelected) {
  modelsBox.hidden = false;
  modelsBox.innerHTML = '<span class="recovery-hint">Loading installed models…</span>';
  try {
    const data = await api("/api/v1/models");
    state.canSelectModel = Boolean(data.can_select);
    if (!data.can_select) {
      modelsBox.innerHTML = '<span class="recovery-hint">Only an administrator can switch models. Ask an administrator to change the Chatbot model, or try a smaller prompt.</span>';
      return;
    }
    if (!data.reachable) {
      modelsBox.innerHTML = `<span class="recovery-hint">Ollama is not reachable at ${escapeHtml(data.ollama_url || "")}. Start it, then retry.</span>`;
      return;
    }
    const models = data.models || [];
    if (!models.length) {
      modelsBox.innerHTML = '<span class="recovery-hint">No models are installed. Run <code>ollama pull</code> first.</span>';
      return;
    }
    modelsBox.innerHTML = `
      <select aria-label="Choose a model">
        ${models.map((item) => `<option value="${escapeHtml(item.name)}" ${item.current ? "selected" : ""}>${escapeHtml(item.name)}${item.installed === false ? " (not installed)" : ""}</option>`).join("")}
      </select>
      <button type="button" data-recovery-apply>Use model &amp; retry</button>`;
    modelsBox.querySelector("[data-recovery-apply]").addEventListener("click", async () => {
      const select = modelsBox.querySelector("select");
      const chosen = select.value;
      try {
        await api("/api/v1/models/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: chosen }),
        });
        modelsBox.innerHTML = `<span class="recovery-hint">Switched to ${escapeHtml(chosen)}. Retrying…</span>`;
        onSelected();
      } catch (error) {
        modelsBox.innerHTML = `<span class="recovery-hint">Could not switch: ${escapeHtml(error.message)}</span>`;
      }
    });
  } catch (error) {
    modelsBox.innerHTML = `<span class="recovery-hint">Could not load models: ${escapeHtml(error.message)}</span>`;
  }
}

function bindRecovery(article, { detail, nextSteps, runId, message }) {
  const detailsBox = article.querySelector(".recovery-details");
  const modelsBox = article.querySelector(".recovery-models");
  article.querySelector("[data-recovery-retry]")?.addEventListener("click", () => {
    article.remove();
    retryMessage(message, runId);
  });
  article.querySelector("[data-recovery-switch]")?.addEventListener("click", () => {
    showModelPicker(article, modelsBox, () => {
      article.remove();
      retryMessage(message, runId);
    });
  });
  article.querySelector("[data-recovery-details]")?.addEventListener("click", () => {
    showRunDetails(article, runId, detailsBox);
  });
}

function renderConversations() {
  const list = $("#conversation-list");
  const query = state.search.trim().toLowerCase();
  const conversations = query
    ? state.conversations.filter((item) => String(item.title || "").toLowerCase().includes(query))
    : state.conversations;
  if (!conversations.length) {
    list.innerHTML = `<p class="sidebar-status">${state.conversations.length ? "No chats match your search." : "No chats yet."}</p>`;
    return;
  }
  list.innerHTML = conversations.map((conversation) => `
    <div class="conversation-item ${conversation.id === state.conversationId ? "active" : ""}">
      <button class="conversation-select" type="button" data-open="${escapeHtml(conversation.id)}" title="${escapeHtml(conversation.title)}">
        ${conversation.incognito ? "◌ " : ""}${escapeHtml(conversation.title || "New conversation")}
      </button>
      <button class="icon-button conversation-menu" type="button" data-delete="${escapeHtml(conversation.id)}" title="Delete chat" aria-label="Delete chat">⋯</button>
    </div>
  `).join("");
}

function renderChatMode() {
  const badge = $("#chat-mode");
  badge.hidden = !state.incognito;
  $("#incognito-toggle").checked = state.incognito;
}

async function loadRuntimeContext() {
  try {
    const [orchestration, definitions] = await Promise.all([
      api("/orchestration"),
      api("/api/v1/agent-definitions"),
    ]);
    const agents = (orchestration?.agents || [])
      .filter((agent) => agent.enabled !== false)
      .sort((a, b) => {
        const rank = (agent) => (
          agent.id === "chatbot" || String(agent.name || "").toLowerCase() === "chatagent"
        ) ? 0 : 1;
        return rank(a) - rank(b) || String(a.name || "").localeCompare(String(b.name || ""));
      });
    const chatAgent = agents.find((agent) =>
      agent.id === "chatbot" || String(agent.name || "").toLowerCase() === "chatagent"
    ) || agents[0];
    if (!state.agentId || !agents.some((agent) => agent.id === state.agentId)) {
      state.agentId = chatAgent?.id || "";
    }
    const select = $("#agent-select");
    select.innerHTML = agents.length
      ? agents.map((agent) =>
          `<option value="${escapeHtml(agent.id)}">${escapeHtml(agent.name)}</option>`).join("")
      : '<option value="">ChatAgent</option>';
    select.value = state.agentId;

    const active = agents.find((agent) => agent.id === state.agentId) || chatAgent;
    $("#context-runtime").textContent = orchestration?.running ? "Online" : "Stopped";
    $("#context-runtime-sub").textContent = orchestration?.running
      ? `${agents.length} agent(s) · ${orchestration?.tools?.total || 0} tools`
      : "The agent orchestrator is not running";
    $("#context-agent").textContent = active?.name || "VIRA";
    $("#context-agent-sub").textContent = active?.description || "Main assistant";

    const names = orchestration?.tools?.metadata || orchestration?.tools?.names || [];
    const tools = names.slice(0, 14).map((tool) => typeof tool === "string"
      ? `<span>${escapeHtml(tool)}</span>`
      : `<span>${escapeHtml(tool.name)}</span>`).join("");
    $("#context-tools").innerHTML = tools || '<span class="context-muted">No tools registered</span>';

    const specialists = definitions?.definitions || [];
    $("#context-specialists").innerHTML = specialists.length
      ? specialists.slice(0, 8).map((item) => `<div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.description || "")}</span></div>`).join("")
      : '<span class="context-muted">No specialist definitions</span>';
  } catch (error) {
    $("#context-runtime").textContent = "Unavailable";
    $("#context-runtime-sub").textContent = error.message;
    $("#context-tools").innerHTML = '<span class="context-muted">Runtime details unavailable</span>';
    $("#context-specialists").innerHTML = '<span class="context-muted">Runtime details unavailable</span>';
  }
}

async function loadConversations() {
  try {
    state.conversations = (await api("/conversations?limit=100")).conversations || [];
    renderConversations();
    if (state.conversationId && !state.conversations.some((item) => item.id === state.conversationId)) {
      await startNewChat(false);
    }
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderMessages(messages) {
  $("#welcome-state").hidden = messages.length > 0;
  const list = $("#message-list");
  list.innerHTML = "";
  for (const message of messages) {
    if (message.role === "assistant") {
      const trace = message.metadata?.trace;
      const live = trace?.length ? newLive(trace, false) : null;
      list.appendChild(assistantArticle({ answer: message.content, live }));
    } else {
      list.appendChild(userArticle(message.content));
    }
  }
  follow(true);
}

async function openConversation(id) {
  state.conversationId = id;
  const conversation = state.conversations.find((item) => item.id === id);
  state.incognito = Boolean(conversation?.incognito);
  renderChatMode();
  $("#chat-title").textContent = conversation?.title || "New chat";
  renderConversations();
  try {
    const result = await api(`/conversations/${encodeURIComponent(id)}/messages?limit=100`);
    renderMessages(result.messages || []);
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function startNewChat(shouldFocus = true) {
  state.conversationId = null;
  state.incognito = $("#incognito-toggle").checked;
  renderChatMode();
  $("#chat-title").textContent = "New chat";
  renderConversations();
  renderMessages([]);
  setStatus("");
  if (shouldFocus) $("#message-input").focus();
}

async function deleteAllConversations() {
  if (!state.conversations.length) {
    setStatus("There are no chats to delete.");
    return;
  }
  if (!window.confirm(`Delete all ${state.conversations.length} chat${state.conversations.length === 1 ? "" : "s"}? This cannot be undone.`)) return;
  try {
    await api("/conversations", { method: "DELETE" });
    state.conversations = [];
    await startNewChat(false);
    await loadConversations();
    setStatus("All chats deleted.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function deleteConversation(id) {
  const conversation = state.conversations.find((item) => item.id === id);
  if (!conversation || !window.confirm(`Delete "${conversation.title || "this chat"}"?`)) return;
  try {
    await api(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.conversationId === id) {
      await startNewChat(false);
    }
    await loadConversations();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function streamChat(payload, onEvent, signal) {
  const response = await fetch("/chat/stream", {
    method: "POST",
    credentials: "include",
    signal,
    headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
    body: JSON.stringify(payload),
  });
  if (response.status === 401) { window.location.href = "/login"; return; }
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || `Request failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
}

function defaultNextSteps(error) {
  if (error?.name === "AbortError") {
    return ["Retry when you are ready; the server may still save the answer."];
  }
  return [
    "Retry the message; the conversation is preserved.",
    "Run `python -m vira doctor` in the VIRA directory to check Ollama and the model.",
    "Switch to another model from this panel, or use a cloud provider.",
  ];
}

async function submitMessage(message, { appendUser = true, retryRunId = null } = {}) {
  if (!message || state.sending) return;
  state.sending = true;
  state.abort = new AbortController();
  $("#send-button").disabled = true;
  $("#stop-button").hidden = false;

  const list = $("#message-list");
  let pending = null;
  try {
    if (!state.conversationId) {
      const created = await api("/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: message.slice(0, 48), incognito: state.incognito }),
      });
      state.conversationId = created.id;
      await loadConversations();
    }

    $("#welcome-state").hidden = true;
    if (appendUser) list.appendChild(userArticle(message));
    const live = newLive([], true);
    pending = assistantArticle({ live });
    list.appendChild(pending);
    follow(true);

    let answer = null;
    let errorEvent = null;
    await streamChat({
      conversation_id: state.conversationId,
      message,
      agent_id: state.agentId || null,
      retry_run_id: retryRunId || null,
    }, (evt) => {
      if (evt.type === "done") { answer = evt.response || ""; return; }
      if (evt.type === "error") { errorEvent = evt; return; }
      live.events.push(evt);
      pending._setTrace();
      follow();
    }, state.abort.signal);
    if (errorEvent) {
      const failure = new Error(errorEvent.detail || "Chat failed");
      failure.payload = errorEvent;
      throw failure;
    }
    if (answer === null) throw new Error("The connection closed before VIRA answered.");

    live.running = false;
    live.open = false;
    pending._setTrace();
    pending.querySelector(".answer").innerHTML = renderMarkdown(answer);
    follow();

    if (state.conversations.find((item) => item.id === state.conversationId)?.title === "New conversation") {
      await api(`/conversations/${encodeURIComponent(state.conversationId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: message.slice(0, 48) }),
      });
    }
    await loadConversations();
    $("#chat-title").textContent = state.conversations.find((item) => item.id === state.conversationId)?.title || "Chat";
    $("#message-input").value = "";
    $("#message-input").style.height = "auto";
  } catch (error) {
    pending?.remove();
    const payload = error.payload || {};
    const detail = payload.detail || error.message;
    const runId = payload.run_id || null;
    const nextSteps = payload.next_steps?.length ? payload.next_steps : defaultNextSteps(error);
    const article = errorArticle({ detail, nextSteps, runId, message });
    list.appendChild(article);
    bindRecovery(article, { detail, nextSteps, runId, message });
    if (!$("#message-input").value.trim()) {
      $("#message-input").value = message;
      $("#message-input").style.height = "auto";
    }
    if (error.name === "AbortError") {
      setStatus("Stopped. The server may still finish and save the answer.");
    }
    follow();
  } finally {
    state.sending = false;
    state.abort = null;
    $("#send-button").disabled = false;
    $("#stop-button").hidden = true;
    $("#message-input").focus();
  }
}

async function retryMessage(message, runId) {
  if (!message || state.sending) return;
  await submitMessage(message, { appendUser: !runId, retryRunId: runId });
}

function sendMessage(event) {
  event.preventDefault();
  const input = $("#message-input");
  const message = input.value.trim();
  if (!message || state.sending) return;
  input.value = "";
  input.style.height = "auto";
  submitMessage(message, { appendUser: true });
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("vira-theme", theme);
  localStorage.setItem("vira-chat-theme", theme);
  $("#theme-toggle").textContent = theme === "light" ? "☾" : "☼";
}

$("#conversation-list").addEventListener("click", (event) => {
  const open = event.target.closest("[data-open]");
  const remove = event.target.closest("[data-delete]");
  if (open) openConversation(open.dataset.open);
  if (remove) deleteConversation(remove.dataset.delete);
});
$("#new-chat").addEventListener("click", () => startNewChat());
$("#incognito-toggle").addEventListener("change", (event) => {
  if (state.conversationId) {
    event.target.checked = state.incognito;
    setStatus("Start a new chat to change incognito mode.", true);
    return;
  }
  state.incognito = event.target.checked;
});
$("#refresh-chats").addEventListener("click", loadConversations);
$("#clear-chats").addEventListener("click", deleteAllConversations);
$("#conversation-search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderConversations();
});
$("#agent-select").addEventListener("change", (event) => {
  state.agentId = event.target.value;
  loadRuntimeContext();
});
$("#context-toggle").addEventListener("click", () => {
  const main = $("#chat-main");
  const open = main.classList.toggle("context-open");
  $("#context-toggle").setAttribute("aria-expanded", String(open));
});
$("#context-close").addEventListener("click", () => {
  $("#chat-main").classList.remove("context-open");
  $("#context-toggle").setAttribute("aria-expanded", "false");
});
$("#composer").addEventListener("submit", sendMessage);
$("#stop-button").addEventListener("click", () => {
  state.abort?.abort();
});
$("#message-scroller").addEventListener("scroll", () => {
  const el = $("#message-scroller");
  pinnedToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
});
$("#message-list").addEventListener("click", (event) => {
  const copy = event.target.closest("[data-copy]");
  if (copy) {
    const code = copy.closest(".code-block").querySelector("code").textContent;
    navigator.clipboard?.writeText(code).then(() => {
      copy.textContent = "Copied";
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    return;
  }
  const article = event.target.closest("article.message");
  const live = article?._live;
  if (!live) return;
  const tool = event.target.closest("[data-trace-tool]");
  if (tool) {
    const index = Number(tool.dataset.traceTool);
    live.openTools.has(index) ? live.openTools.delete(index) : live.openTools.add(index);
    article._setTrace();
  } else if (event.target.closest("[data-trace-toggle]")) {
    live.open = !live.open;
    article._setTrace();
  }
});
$("#message-input").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 180)}px`;
});
$("#message-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#composer").requestSubmit();
  }
});
document.querySelectorAll("[data-suggestion]").forEach((button) => {
  button.addEventListener("click", () => {
    $("#message-input").value = button.dataset.suggestion;
    $("#composer").requestSubmit();
  });
});
$("#theme-toggle").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});
$("#logout-button").addEventListener("click", async () => {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
    window.location.href = "/login";
  } catch (error) {
    setStatus(error.message, true);
  }
});

applyTheme(localStorage.getItem("vira-theme") || localStorage.getItem("vira-chat-theme") ||
  (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
loadCurrentUser().then(() => loadConversations());
loadRuntimeContext();
