const REFRESH_INTERVAL_MS = 30000;
const MAX_EVENT_ENTRIES = 200;

let eventCount = 0;
let eventSource = null;

const statusEl = document.getElementById("status");
const streamStatusEl = document.getElementById("stream-status");
const eventLogEl = document.getElementById("event-log");
const eventCountEl = document.getElementById("event-count");
const eventsLastUpdatedEl = document.getElementById("events-last-updated");

function applyTheme(theme) {
  const isLight = theme === "light";
  document.documentElement.dataset.theme = isLight ? "light" : "dark";
  localStorage.setItem("vira-theme", isLight ? "light" : "dark");
  document.getElementById("theme-icon").textContent = isLight ? "☾" : "☀";
  document.getElementById("theme-label").textContent = isLight ? "Dark mode" : "Light mode";
  document.getElementById("theme-toggle").setAttribute(
    "aria-label",
    isLight ? "Switch to dark theme" : "Switch to light theme"
  );
}

document.getElementById("theme-toggle").addEventListener("click", () => {
  const currentTheme = document.documentElement.dataset.theme || "dark";
  applyTheme(currentTheme === "light" ? "dark" : "light");
});

applyTheme(document.documentElement.dataset.theme || "dark");

document.getElementById("logout-btn").addEventListener("click", async () => {
  const logoutButton = document.getElementById("logout-btn");
  logoutButton.disabled = true;
  logoutButton.textContent = "Logging out...";

  try {
    const response = await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error(`Logout failed (${response.status})`);
    }
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    window.location.href = "/login";
  } catch (error) {
    logoutButton.disabled = false;
    logoutButton.textContent = "Log out";
    logoutButton.title = error.message;
  }
});

function setInlineMessage(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.toggle("success", !isError && Boolean(message));
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTimestamp(value) {
  if (typeof value === "number") {
    return new Date(value * 1000).toLocaleTimeString();
  }

  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toLocaleTimeString();
  }

  return "unknown";
}

async function fetchWithAuth(url, options = {}) {
  const response = await fetch(url, { credentials: "include", ...options });
  if (response.status === 401) {
    window.location.href = "/login";
    return null;
  }
  return response;
}

async function fetchJson(url, options = {}) {
  const response = await fetchWithAuth(url, options);
  if (!response) {
    return { ok: false, data: null, status: 401 };
  }

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  return { ok: response.ok, data, status: response.status };
}

async function loadHealth() {
  const healthStatusEl = document.getElementById("health-status");
  const healthJsonEl = document.getElementById("health-json");

  try {
    const result = await fetchJson("/health");
    if (!result.ok) {
      healthStatusEl.textContent = "Unavailable";
      healthJsonEl.textContent = `Request failed (${result.status})`;
      statusEl.textContent = "Degraded";
      statusEl.classList.add("degraded");
      return;
    }

    const status = String(result.data.status || "unknown");
    const normalized = status.toLowerCase();
    healthStatusEl.textContent = status;
    healthJsonEl.textContent = formatJson(result.data);

    statusEl.textContent = normalized === "healthy" ? "Running" : "Degraded";
    statusEl.classList.toggle("degraded", normalized !== "healthy");
  } catch (error) {
    healthStatusEl.textContent = "Error";
    healthJsonEl.textContent = `Error loading health: ${error.message}`;
  }
}

async function loadMetrics() {
  const metricsJsonEl = document.getElementById("metrics-json");
  try {
    const result = await fetchJson("/metrics");
    metricsJsonEl.textContent = result.ok
      ? formatJson(result.data)
      : `Request failed (${result.status})`;
  } catch (error) {
    metricsJsonEl.textContent = `Error loading metrics: ${error.message}`;
  }
}

async function loadContext() {
  const contextJsonEl = document.getElementById("context-json");
  try {
    const result = await fetchJson("/context");
    contextJsonEl.textContent = result.ok
      ? formatJson(result.data)
      : `Request failed (${result.status})`;
  } catch (error) {
    contextJsonEl.textContent = `Error loading context: ${error.message}`;
  }
}

async function loadConfig() {
  const configJsonEl = document.getElementById("config-json");
  try {
    const result = await fetchJson("/config");
    configJsonEl.textContent = result.ok
      ? formatJson(result.data)
      : `Request failed (${result.status})`;
  } catch (error) {
    configJsonEl.textContent = `Error loading config: ${error.message}`;
  }
}

function renderOrchestrationAgents(agents) {
  const agentsEl = document.getElementById("orchestration-agents");
  if (!agents.length) {
    agentsEl.innerHTML = '<p class="empty-state">No agents are registered.</p>';
    return;
  }

  agentsEl.innerHTML = agents.map((agent) => {
    const capabilities = (agent.capabilities || [])
      .map((capability) => capability.name || capability)
      .join(", ");
    const events = (agent.subscribed_events || []).join(", ");
    return `
      <article class="agent-card">
        <div class="agent-card-header">
          <strong>${escapeHtml(agent.name || agent.id)}</strong>
          <span class="agent-state ${escapeHtml(agent.state || "unknown")}">${escapeHtml(agent.state || "unknown")}</span>
        </div>
        <p>${escapeHtml(agent.description || "No description provided.")}</p>
        <dl>
          <dt>ID</dt><dd>${escapeHtml(agent.id)}</dd>
          <dt>Capabilities</dt><dd>${escapeHtml(capabilities || "None registered")}</dd>
          <dt>Subscribed events</dt><dd>${escapeHtml(events || "None")}</dd>
          <dt>Interval</dt><dd>${escapeHtml(agent.interval_seconds == null ? "Event-driven" : `${agent.interval_seconds}s`)}</dd>
        </dl>
      </article>
    `;
  }).join("");
}

function renderOrchestrationTools(toolNames) {
  const toolsEl = document.getElementById("orchestration-tools");
  if (!toolNames.length) {
    toolsEl.innerHTML = '<span class="empty-state">No tools are registered.</span>';
    return;
  }

  toolsEl.innerHTML = toolNames
    .map((toolName) => `<span class="tool-chip">${escapeHtml(toolName)}</span>`)
    .join("");
}

function renderSecurityPosture(posture) {
  const postureEl = document.getElementById("security-posture");
  postureEl.innerHTML = Object.entries(posture || {})
    .map(([key, value]) => `
      <article class="posture-item">
        <span>${escapeHtml(key.replaceAll("_", " "))}</span>
        <strong>${escapeHtml(value)}</strong>
      </article>
    `)
    .join("");
}

function renderSecurityTools(tools) {
  const toolsEl = document.getElementById("security-tools-list");
  if (!tools.length) {
    toolsEl.innerHTML = '<p class="empty-state">No registered tools.</p>';
    return;
  }

  toolsEl.innerHTML = tools.map((tool) => `
    <article class="security-tool">
      <strong>${escapeHtml(tool.name)}</strong>
      <span>${escapeHtml((tool.actions || []).join(" · ") || "No actions declared")}</span>
    </article>
  `).join("");
}

function renderSecurityLimits(limits) {
  const limitsEl = document.getElementById("security-limits-list");
  limitsEl.innerHTML = (limits || []).map((limit) => `<li>${escapeHtml(limit)}</li>`).join("");
}

async function loadSecurity() {
  const result = await fetchJson("/security");
  const statusEl = document.getElementById("security-status");

  if (!result.ok || !result.data) {
    statusEl.textContent = "Unavailable";
    statusEl.className = "panel-state error";
    return;
  }

  const data = result.data;
  statusEl.textContent = data.authentication?.admin_configured
    ? "Protected"
    : "Setup required";
  statusEl.className = `panel-state ${data.authentication?.admin_configured ? "healthy" : "warning"}`;

  renderSecurityPosture(data.posture);
  document.getElementById("security-authentication").textContent = formatJson(data.authentication);
  document.getElementById("security-authorization").textContent = formatJson(data.authorization);
  document.getElementById("security-events").textContent = formatJson(data.event_dispatch);
  document.getElementById("security-runtime").textContent = formatJson(data.agent_runtime);
  renderSecurityTools(data.tools?.registered || []);
  renderSecurityLimits(data.visibility_limits);
}

async function loadOrchestration() {
  const result = await fetchJson("/orchestration");
  const statusEl = document.getElementById("orchestration-status");
  const controlEl = document.getElementById("orchestration-control");

  if (!result.ok || !result.data) {
    statusEl.textContent = "Unavailable";
    statusEl.className = "panel-state error";
    controlEl.textContent = `Request failed (${result.status})`;
    return;
  }

  const data = result.data;
  const agents = Array.isArray(data.agents) ? data.agents : [];
  const scheduler = data.scheduler || {};
  const tools = data.tools || {};
  const runningAgents = agents.filter((agent) => ["running", "waiting"].includes(agent.state)).length;

  statusEl.textContent = data.available
    ? (data.running ? "Running" : "Stopped")
    : "Not loaded";
  statusEl.className = `panel-state ${data.running ? "healthy" : "warning"}`;
  document.getElementById("orchestration-agent-count").textContent = String(agents.length);
  document.getElementById("orchestration-running-count").textContent = String(runningAgents);
  document.getElementById("orchestration-task-count").textContent =
    `${scheduler.running_tasks || 0}/${scheduler.max_concurrent || 0}`;
  document.getElementById("orchestration-tool-count").textContent = String(tools.total || 0);

  renderOrchestrationAgents(agents);
  renderOrchestrationTools(Array.isArray(tools.names) ? tools.names : []);
  controlEl.textContent = formatJson({
    router: data.router,
    scheduler,
    runtime: data.runtime,
    tools: {
      mcp_connections: tools.mcp_connections || 0,
      total: tools.total || 0
    }
  });
}

async function loadModules() {
  const moduleListEl = document.getElementById("module-list");
  const runningModulesEl = document.getElementById("running-modules");
  const totalModulesEl = document.getElementById("total-modules");

  try {
    const result = await fetchJson("/modules");
    if (!result.ok || !Array.isArray(result.data)) {
      moduleListEl.innerHTML = "<li>Failed to load modules</li>";
      return;
    }

    const modules = result.data;
    const runningCount = modules.filter((module) => Boolean(module.running)).length;

    runningModulesEl.textContent = String(runningCount);
    totalModulesEl.textContent = String(modules.length);

    if (!modules.length) {
      moduleListEl.innerHTML = "<li>No modules loaded</li>";
      return;
    }

    moduleListEl.innerHTML = modules
      .map((module) => {
        const stateLabel = module.running ? "Running" : "Stopped";
        const statusClass = module.running ? "running" : "stopped";
        return `
          <li>
            <span class="name">${module.name}</span>
            <span class="status-badge ${statusClass}">${stateLabel}</span>
          </li>
        `;
      })
      .join("");
  } catch (error) {
    moduleListEl.innerHTML = `<li>Error loading modules: ${error.message}</li>`;
  }
}

function addEventToLog(event) {
  eventCount += 1;
  eventCountEl.textContent = String(eventCount);
  eventsLastUpdatedEl.textContent = `Last event at ${new Date().toLocaleTimeString()}`;

  const priority = String(event.priority || "NORMAL").toUpperCase();
  const entry = document.createElement("div");
  entry.className = `event-entry ${priority}`;
  entry.innerHTML = `
    <span class="time">${formatTimestamp(event.timestamp)}</span>
    <span class="type">${event.type || "unknown.event"}</span>
    <span class="data">${JSON.stringify(event.data ?? {})}</span>
    <span class="priority ${priority}">${priority}</span>
  `;

  eventLogEl.prepend(entry);

  while (eventLogEl.children.length > MAX_EVENT_ENTRIES) {
    eventLogEl.removeChild(eventLogEl.lastChild);
  }
}

function connectEventStream() {
  if (eventSource) {
    eventSource.close();
  }

  streamStatusEl.textContent = "Connecting...";
  eventSource = new EventSource("/events/stream", { withCredentials: true });

  eventSource.onopen = () => {
    streamStatusEl.textContent = "Connected";
    streamStatusEl.classList.remove("disconnected");
  };

  eventSource.onmessage = (messageEvent) => {
    try {
      const event = JSON.parse(messageEvent.data);
      addEventToLog(event);
    } catch {
      // Ignore malformed stream packets.
    }
  };

  eventSource.onerror = () => {
    streamStatusEl.textContent = "Disconnected (retrying)";
    streamStatusEl.classList.add("disconnected");
    eventSource.close();
    setTimeout(connectEventStream, 3000);
  };
}

async function refreshAll() {
  await Promise.all([
    loadHealth(),
    loadMetrics(),
    loadContext(),
    loadConfig(),
    loadOrchestration(),
    loadSecurity(),
    loadModules()
  ]);
}

document.getElementById("load-module-btn").addEventListener("click", async () => {
  const modulePathEl = document.getElementById("module-path");
  const moduleActionResultEl = document.getElementById("module-action-result");
  const modulePath = modulePathEl.value.trim();

  if (!modulePath) {
    setInlineMessage(moduleActionResultEl, "Enter a module path first.", true);
    return;
  }

  setInlineMessage(moduleActionResultEl, "Loading module...");
  try {
    const result = await fetchJson("/modules/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module_path: modulePath })
    });

    if (result.ok) {
      setInlineMessage(moduleActionResultEl, `Loaded: ${modulePath}`);
      modulePathEl.value = "";
      await loadModules();
      return;
    }

    const detail = typeof result.data === "object" ? result.data?.detail : "";
    setInlineMessage(
      moduleActionResultEl,
      `Failed to load module (${result.status})${detail ? `: ${detail}` : ""}`,
      true
    );
  } catch (error) {
    setInlineMessage(moduleActionResultEl, `Error: ${error.message}`, true);
  }
});

document.getElementById("publish-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const publishResultEl = document.getElementById("publish-result");
  const type = document.getElementById("event-type").value.trim();
  const dataRaw = document.getElementById("event-data").value.trim();

  let payload;
  try {
    payload = JSON.parse(dataRaw);
  } catch {
    setInlineMessage(publishResultEl, "Event data must be valid JSON.", true);
    return;
  }

  try {
    const result = await fetchJson("/events/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, data: payload, source: "webui", priority: "NORMAL" })
    });

    if (result.ok) {
      const correlation = result.data?.correlation_id || "n/a";
      const subscribers = result.data?.subscribers ?? "n/a";
      setInlineMessage(
        publishResultEl,
        `Published successfully. correlation_id=${correlation}, subscribers=${subscribers}`
      );
      return;
    }

    const detail = typeof result.data === "object" ? result.data?.detail : "";
    setInlineMessage(
      publishResultEl,
      `Publish failed (${result.status})${detail ? `: ${detail}` : ""}`,
      true
    );
  } catch (error) {
    setInlineMessage(publishResultEl, `Publish error: ${error.message}`, true);
  }
});

document.getElementById("api-test-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const method = document.getElementById("api-method").value.trim().toUpperCase();
  const endpoint = document.getElementById("api-endpoint").value.trim();
  const bodyRaw = document.getElementById("api-body").value.trim();
  const responseEl = document.getElementById("api-response");
  const metaEl = document.getElementById("api-response-meta");

  let parsedBody;
  if (method !== "GET" && bodyRaw) {
    try {
      parsedBody = JSON.parse(bodyRaw);
    } catch {
      setInlineMessage(metaEl, "Body must be valid JSON for non-GET requests.", true);
      return;
    }
  }

  setInlineMessage(metaEl, "Sending request...");
  responseEl.textContent = "Loading...";

  try {
    const options = { method };
    if (parsedBody !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(parsedBody);
    }

    const response = await fetchWithAuth(endpoint, options);
    if (!response) {
      return;
    }

    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    responseEl.textContent = typeof body === "string" ? body : formatJson(body);
    setInlineMessage(metaEl, `Status ${response.status} ${response.ok ? "OK" : "ERROR"}`, !response.ok);
  } catch (error) {
    responseEl.textContent = `Request failed: ${error.message}`;
    setInlineMessage(metaEl, "Request failed.", true);
  }
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const endpoint = chip.getAttribute("data-endpoint") || "/health";
    const method = chip.getAttribute("data-method") || "GET";
    document.getElementById("api-endpoint").value = endpoint;
    document.getElementById("api-method").value = method;

    if (method === "GET") {
      document.getElementById("api-body").value = "";
    }
  });
});

document.getElementById("refresh-all-btn").addEventListener("click", () => {
  refreshAll();
});

refreshAll();
connectEventStream();
setInterval(refreshAll, REFRESH_INTERVAL_MS);
