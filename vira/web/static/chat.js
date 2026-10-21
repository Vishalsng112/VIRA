const state = {
  conversations: [],
  conversationId: null,
  incognito: false,
  username: "User",
  sending: false,
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

function renderConversations() {
  const list = $("#conversation-list");
  if (!state.conversations.length) {
    list.innerHTML = '<p class="sidebar-status">No chats yet.</p>';
    return;
  }
  list.innerHTML = state.conversations.map((conversation) => `
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
  $("#message-list").innerHTML = messages.map((message) => `
    <article class="message ${message.role === "assistant" ? "assistant" : ""}">
      <div class="message-avatar">${message.role === "assistant" ? "V" : escapeHtml(userInitial())}</div>
      <div class="message-content">
        <div class="message-role">${escapeHtml(messageAuthor(message.role))}</div>
        <div>${escapeHtml(message.content)}</div>
      </div>
    </article>
  `).join("");
  const scroller = $("#message-scroller");
  scroller.scrollTop = scroller.scrollHeight;
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

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#message-input");
  const message = input.value.trim();
  if (!message || state.sending) return;
  state.sending = true;
  $("#send-button").disabled = true;
  input.value = "";
  input.style.height = "auto";

  const list = $("#message-list");
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
    list.insertAdjacentHTML("beforeend", `
      <article class="message">
        <div class="message-avatar">${escapeHtml(userInitial())}</div>
        <div class="message-content"><div class="message-role">${escapeHtml(state.username)}</div><div>${escapeHtml(message)}</div></div>
      </article>
      <article id="typing-message" class="message assistant">
        <div class="message-avatar">V</div>
        <div class="message-content"><div class="message-role">assistant</div><div class="typing">VIRA is thinking...</div></div>
      </article>
    `);
    $("#message-scroller").scrollTop = $("#message-scroller").scrollHeight;

    const result = await api("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": newIdempotencyKey(),
      },
      body: JSON.stringify({ conversation_id: state.conversationId, message }),
    });
    $("#typing-message")?.remove();
    list.insertAdjacentHTML("beforeend", `
      <article class="message assistant">
        <div class="message-avatar">V</div>
        <div class="message-content"><div class="message-role">assistant</div><div>${escapeHtml(result.response || "")}</div></div>
      </article>
    `);
    if (state.conversations.find((item) => item.id === state.conversationId)?.title === "New conversation") {
      await api(`/conversations/${encodeURIComponent(state.conversationId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: message.slice(0, 48) }),
      });
    }
    await loadConversations();
    $("#chat-title").textContent = state.conversations.find((item) => item.id === state.conversationId)?.title || "Chat";
  } catch (error) {
    $("#typing-message")?.remove();
    list.insertAdjacentHTML("beforeend", `
      <article class="message assistant">
        <div class="message-avatar">!</div>
        <div class="message-content"><div class="message-role">error</div><div>${escapeHtml(error.message)}</div></div>
      </article>
    `);
  } finally {
    state.sending = false;
    $("#send-button").disabled = false;
    input.focus();
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
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
$("#composer").addEventListener("submit", sendMessage);
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

applyTheme(localStorage.getItem("vira-chat-theme") || "dark");
loadCurrentUser().then(() => loadConversations());
