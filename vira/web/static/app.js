/* VIRA dashboard
 * Same backend endpoints as before. What changed: data is rendered as
 * readable components instead of raw JSON, views are split by topic, every
 * inserted string is escaped, and secrets are masked.
 */
(() => {
  "use strict";

  const REFRESH_MS = 30000;
  const MAX_EVENTS = 200;
  const SENSITIVE_KEY = /(secret|password|passwd|token|api[_-]?key|private|credential)/i;

  const VIEWS = {
    overview:  { title: "Overview",        sub: "Live status of your VIRA runtime." },
    devices:   { title: "Devices",         sub: "Fleet health, sync state and the latest device insight." },
    agents:    { title: "Agents",          sub: "Registered agents, scheduling and the tools they can use." },
    inbox:     { title: "Inbox",           sub: "Proactive agent results, schedules and run history." },
    extensions:{ title: "Extensions",      sub: "Plugins, MCP servers and the tool marketplace." },
    knowledge: { title: "Knowledge",       sub: "Local documents, hybrid retrieval and RAG search." },
    automations:{ title: "Automations",    sub: "Durable workflows, step state and recovery." },
    usage:     { title: "Usage",           sub: "Token spend, storage, device events and quotas." },
    organizations:{ title: "Organizations", sub: "Teams, membership roles and shared tenancy." },
    files:     { title: "Files",           sub: "Object storage for attachments and large artifacts." },
    updates:   { title: "Updates",         sub: "Server and client release channels." },
    security:  { title: "Security",        sub: "Read-only view of how VIRA authenticates, authorizes and handles events." },
    events:    { title: "Events",          sub: "Live stream from the event bus." },
    modules:   { title: "Modules",         sub: "Kernel modules that are currently loaded." },
    developer: { title: "Developer tools", sub: "Test endpoints and inspect raw runtime data." },
    configuration: { title: "Configuration", sub: "Update defaults and reload the VIRA runtime." },
  };

  const $ = (id) => document.getElementById(id);

  const state = {
    health: null, metrics: null, orchestration: null, security: null, approvals: null, generated: null, runs: null, modules: null,
    plugins: null, mcpServers: null, marketplace: null, mcpTools: null, usage: null,
    devices: null, deviceInsight: null, access: null, tailscale: null, tailscaleOpen: false,
    ragDocs: null, workflows: null, orgs: null,
    objects: null, releases: null, selectedDevice: null,
    notifications: null, schedules: null, recipes: null, unread: 0,
    scheduleRuns: null, selectedSchedule: null, editingScheduleId: null,
    events: [], eventCount: 0, paused: false, authFailed: false,
    stream: "connecting", // connecting | connected | disconnected
    loaded: false,
  };
  let eventSource = null;
  let refreshTimer = null;
  let tailscaleTimer = null;

  /* ---------- helpers ---------- */
  const esc = (v) => String(v ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

  const titleCase = (s) => String(s).replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
  const pretty = (v) => JSON.stringify(v, null, 2);

  function redact(value, key = "") {
    if (Array.isArray(value)) return value.map((v) => redact(v, key));
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redact(v, k)]));
    }
    return SENSITIVE_KEY.test(key) && value ? "••••••••" : value;
  }

  function fmtUptime(sec) {
    sec = Math.floor(Number(sec) || 0);
    const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600),
          m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function fmtBytes(n) {
    n = Number(n);
    if (!Number.isFinite(n)) return "—";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
  }

  function fmtTime(value) {
    const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString([], { hour12: false });
  }

  function fmtDate(value) {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function fmtDateTime(value) {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function fmtDurationMs(ms) {
    const minutes = Math.round((Number(ms) || 0) / 60000);
    if (minutes < 60) return `${minutes} min`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  function fmtNumber(n) {
    n = Number(n);
    if (!Number.isFinite(n)) return "—";
    return new Intl.NumberFormat([], { notation: n >= 100000 ? "compact" : "standard",
      maximumFractionDigits: n >= 1000 ? 1 : 0 }).format(n);
  }

  function fmtMoney(n) {
    n = Number(n);
    if (!Number.isFinite(n)) return "—";
    return n < 0.01 && n > 0 ? `<$0.01` : `$${n.toFixed(2)}`;
  }

  function fmtValue(v) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function kv(obj, labels = {}) {
    const rows = Object.entries(obj || {}).filter(([, v]) => v === null || typeof v !== "object" || Array.isArray(v));
    if (!rows.length) return '<p class="empty">Nothing reported.</p>';
    return rows.map(([k, v]) =>
      `<div><dt>${esc(labels[k] || titleCase(k))}</dt><dd>${esc(fmtValue(v))}</dd></div>`
    ).join("");
  }

  const chips = (items, empty = "None") =>
    items && items.length
      ? items.map((i) => `<span class="chip">${esc(i)}</span>`).join("")
      : `<span class="empty">${esc(empty)}</span>`;

  function setText(id, text) { const el = $(id); if (el) el.textContent = text; }
  function setHtml(id, html) { const el = $(id); if (el) el.innerHTML = html; }

  function setResult(el, message, isError = false) {
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.toggle("success", !isError && Boolean(message));
  }

  function setPill(el, label, tone) {
    el.textContent = label;
    el.className = `pill pill-${tone}`;
  }

  /* ---------- network ---------- */
  async function fetchWithAuth(url, options = {}) {
    if (state.authFailed) return null;
    const res = await fetch(url, { credentials: "include", ...options });
    if (res.status === 401) {
      // A stale or revoked session should stop the polling loop, not spam 401s.
      state.authFailed = true;
      if (refreshTimer) clearInterval(refreshTimer);
      window.location.href = "/login";
      return null;
    }
    return res;
  }

  async function fetchJson(url, options = {}) {
    const res = await fetchWithAuth(url, options);
    if (!res) return { ok: false, data: null, status: 401 };
    const isJson = (res.headers.get("content-type") || "").includes("application/json");
    return { ok: res.ok, status: res.status, data: isJson ? await res.json() : await res.text() };
  }

  /* ---------- theme ---------- */
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("vira-theme", theme); } catch (e) {}
    const dark = theme === "dark";
    $("theme-icon").setAttribute("href", dark ? "#i-sun" : "#i-moon");
    const label = dark ? "Switch to light theme" : "Switch to dark theme";
    $("theme-btn").setAttribute("aria-label", label);
    $("theme-btn").title = label;
  }
  $("theme-btn").addEventListener("click", () =>
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  applyTheme(document.documentElement.dataset.theme || "light");

  /* ---------- navigation (hash based) ---------- */
  function showView() {
    let id = location.hash.slice(1);
    if (!VIEWS[id]) id = "overview";
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== `view-${id}`; });
    document.querySelectorAll(".nav-link[data-view]").forEach((a) => {
      if (a.dataset.view === id) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    setText("page-title", VIEWS[id].title);
    setText("page-sub", VIEWS[id].sub);
    document.title = `${VIEWS[id].title} · VIRA`;
    closeMenu();
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", showView);
  document.querySelectorAll(".nav-link[data-view]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const view = link.dataset.view;
      if (!VIEWS[view]) return;
      event.preventDefault();
      if (location.hash === `#${view}`) showView();
      else location.hash = view;
    });
  });

  function openMenu() {
    document.body.classList.add("nav-open");
    $("menu-btn").setAttribute("aria-expanded", "true");
  }
  function closeMenu() {
    document.body.classList.remove("nav-open");
    $("menu-btn").setAttribute("aria-expanded", "false");
  }
  $("menu-btn").addEventListener("click", () =>
    document.body.classList.contains("nav-open") ? closeMenu() : openMenu());
  $("scrim").addEventListener("click", closeMenu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

  /* ---------- logout ---------- */
  $("logout-btn").addEventListener("click", async () => {
    $("logout-btn").disabled = true;
    try {
      const res = await fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" });
      if (!res.ok) throw new Error(`Logout failed (${res.status})`);
      if (eventSource) eventSource.close();
      window.location.href = "/login";
    } catch (err) {
      $("logout-btn").disabled = false;
      $("logout-btn").title = err.message;
    }
  });

  /* ---------- loaders ---------- */
  async function load(name, fn) {
    try { await fn(); } catch (err) { console.error(`Failed to load ${name}:`, err); }
  }

  async function loadUser() {
    const r = await fetchJson("/api/v1/auth/me");
    if (!r.ok || !r.data) return;
    const name = String(r.data.username || "Admin");
    setText("user-name", name);
    setText("user-avatar", name.charAt(0));
  }

  async function loadHealth() {
    const r = await fetchJson("/health");
    state.health = r.ok ? r.data : { status: "unavailable", _error: r.status };
    setText("raw-health", r.ok ? pretty(r.data) : `Request failed (${r.status})`);
  }

  async function loadMetrics() {
    const r = await fetchJson("/metrics");
    state.metrics = r.ok ? r.data : null;
    setText("raw-metrics", r.ok ? pretty(r.data) : `Request failed (${r.status})`);
  }

  async function loadContext() {
    const r = await fetchJson("/context");
    setText("raw-context", r.ok ? pretty(redact(r.data)) : `Request failed (${r.status})`);
  }

  async function loadConfig() {
    const r = await fetchJson("/config");
    setText("raw-config", r.ok ? pretty(redact(r.data)) : `Request failed (${r.status})`);
    if (r.ok && $("config-editor") && document.activeElement !== $("config-editor")) {
      $("config-editor").value = pretty(r.data);
    }
  }

  async function loadOrchestration() {
    const r = await fetchJson("/orchestration");
    state.orchestration = r.ok ? r.data : null;
  }

  async function loadSecurity() {
    const r = await fetchJson("/security");
    state.security = r.ok ? r.data : null;
  }

  async function loadApprovals() {
    const r = await fetchJson("/api/v1/admin/approvals?status=pending&limit=50");
    state.approvals = r.ok ? (r.data?.approvals || []) : null;
  }

  async function loadGenerated() {
    const r = await fetchJson("/api/v1/generated?limit=200");
    state.generated = r.ok ? (r.data?.artifacts || []) : null;
  }

  async function loadRuns() {
    const r = await fetchJson("/api/v1/runs?limit=50");
    state.runs = r.ok ? (r.data?.runs || []) : null;
  }

  async function loadInbox() {
    const [notes, unread, schedules, recipes] = await Promise.all([
      fetchJson("/api/v1/notifications?limit=100"),
      fetchJson("/api/v1/notifications/unread-count"),
      fetchJson("/api/v1/agent-schedules"),
      fetchJson("/api/v1/agent-recipes"),
    ]);
    state.notifications = notes.ok ? (notes.data?.notifications || []) : null;
    state.unread = unread.ok ? Number(unread.data?.unread || 0) : 0;
    state.schedules = schedules.ok ? (schedules.data?.schedules || []) : null;
    state.recipes = recipes.ok ? (recipes.data?.agents || []) : null;
  }

  async function loadScheduleRuns(scheduleId) {
    const r = await fetchJson(`/api/v1/agent-schedules/${encodeURIComponent(scheduleId)}/runs?limit=50`);
    state.scheduleRuns = r.ok ? (r.data?.runs || []) : null;
    state.selectedSchedule = scheduleId;
  }

  async function loadModules() {
    const r = await fetchJson("/modules");
    state.modules = r.ok && Array.isArray(r.data) ? r.data : null;
  }

  async function loadPlugins() {
    const r = await fetchJson("/api/v1/plugins");
    state.plugins = r.ok ? r.data : null;
  }

  async function loadMcp() {
    const [servers, marketplace, tools] = await Promise.all([
      fetchJson("/api/v1/mcp/servers"),
      fetchJson("/api/v1/mcp/marketplace"),
      fetchJson("/api/v1/mcp/tools"),
    ]);
    state.mcpServers = servers.ok ? (servers.data?.servers || []) : null;
    state.marketplace = marketplace.ok ? (marketplace.data?.entries || []) : null;
    state.mcpTools = tools.ok ? (tools.data?.tools || []) : null;
  }

  async function loadUsage() {
    const [usage, quotas] = await Promise.all([
      fetchJson("/api/v1/admin/usage?days=30"),
      fetchJson("/api/v1/admin/quotas"),
    ]);
    state.usage = usage.ok
      ? { ...usage.data, quotas: quotas.ok ? (quotas.data?.quotas || []) : [] }
      : null;
  }

  async function loadAccess() {
    const r = await fetchJson("/api/v1/access");
    state.access = r.ok ? r.data : null;
  }

  async function loadDevices() {
    const r = await fetchJson("/api/v1/devices");
    state.devices = r.ok ? (r.data?.devices || []) : null;
    const target = state.selectedDevice || state.devices?.[0]?.device_id;
    if (target) {
      const insight = await fetchJson(`/api/v1/insights/summary?device_id=${encodeURIComponent(target)}&days=7`);
      state.deviceInsight = insight.ok ? insight.data : null;
      state.selectedDevice = target;
    } else {
      state.deviceInsight = null;
    }
  }

  async function loadKnowledge() {
    const r = await fetchJson("/api/v1/rag/documents");
    state.ragDocs = r.ok ? (r.data?.documents || []) : null;
  }

  async function loadWorkflows() {
    const r = await fetchJson("/api/v1/workflows");
    state.workflows = r.ok ? (r.data?.workflows || []) : null;
  }

  async function loadOrganizations() {
    const r = await fetchJson("/api/v1/organizations");
    state.orgs = r.ok ? (r.data?.organizations || []) : null;
  }

  async function loadObjects() {
    const r = await fetchJson("/api/v1/objects?limit=100");
    state.objects = r.ok ? (r.data?.objects || []) : null;
  }

  async function loadReleases() {
    const r = await fetchJson("/api/v1/updates/releases?limit=50");
    state.releases = r.ok ? (r.data?.releases || []) : null;
  }

  /* ---------- derived status ---------- */
  function gauge(name) {
    const g = state.metrics && state.metrics.gauges;
    if (!g) return undefined;
    const key = Object.keys(g).find((k) => k === name || k.startsWith(`${name}{`));
    return key ? g[key] : undefined;
  }

  function agentList() { return (state.orchestration && state.orchestration.agents) || []; }
  function activeAgents() { return agentList().filter((a) => ["running", "ready", "waiting"].includes(a.state)); }

  function computeStatus() {
    const issues = [];
    let tone = "ok";
    const bump = (t) => { if (t === "bad" || tone === "ok") tone = t; };

    if (!state.health) return { loading: true };
    const h = state.health;
    if (String(h.status).toLowerCase() !== "healthy") {
      issues.push(h._error ? `The health check failed (HTTP ${h._error}).` : `Kernel reports "${h.status}".`);
      bump("bad");
    }
    if (state.modules) {
      const stopped = state.modules.filter((m) => !m.running).length;
      if (stopped) { issues.push(`${stopped} module${stopped > 1 ? "s are" : " is"} stopped.`); bump("warn"); }
    }
    const o = state.orchestration;
    if (o && o.available && !o.running) { issues.push("Agent orchestration is not running."); bump("warn"); }
    if (o && !o.available) { issues.push("Agent orchestration is not loaded."); bump("warn"); }
    const s = state.security;
    if (s && s.authentication && !s.authentication.admin_configured) {
      issues.push("No admin account is configured yet."); bump("warn");
    }
    if (state.stream === "disconnected") { issues.push("The live event stream is disconnected. Retrying…"); bump("warn"); }
    return { loading: false, tone, issues };
  }

  /* ---------- render: overview ---------- */
  function renderOverview() {
    const st = computeStatus();
    const banner = $("health-banner");
    const issuesEl = $("banner-issues");

    if (st.loading) {
      banner.dataset.state = "loading";
      setPill($("status"), "Checking…", "neutral");
    } else if (st.tone === "ok") {
      banner.dataset.state = "ok";
      $("banner-icon").setAttribute("href", "#i-ok");
      setText("banner-title", "All systems operational");
      const mods = state.modules ? `${state.modules.filter((m) => m.running).length}/${state.modules.length} modules running` : "";
      setText("banner-text", ["Kernel healthy", mods, state.stream === "connected" ? "event stream connected" : ""].filter(Boolean).join(" · ") + ".");
      issuesEl.hidden = true;
      setPill($("status"), "Operational", "ok");
    } else {
      banner.dataset.state = st.tone;
      $("banner-icon").setAttribute("href", "#i-warn");
      setText("banner-title", st.tone === "bad" ? "Something is wrong" : "Needs attention");
      setText("banner-text", st.issues.length === 1 ? "One thing to look at:" : `${st.issues.length} things to look at:`);
      issuesEl.innerHTML = st.issues.map((i) => `<li>${esc(i)}</li>`).join("");
      issuesEl.hidden = false;
      setPill($("status"), st.tone === "bad" ? "Degraded" : "Attention", st.tone);
    }
    if (st.loading) { setText("banner-title", "Checking system status…"); setText("banner-text", "Loading runtime information."); issuesEl.hidden = true; }

    // KPIs
    const h = state.health;
    if (h) {
      setText("kpi-kernel", titleCase(String(h.kernel_state || h.status || "unknown").toLowerCase()));
      setText("kpi-kernel-sub", `Health: ${h.status}`);
    }
    if (state.modules) {
      const run = state.modules.filter((m) => m.running).length;
      setText("kpi-modules", `${run} / ${state.modules.length}`);
      setText("kpi-modules-sub", run === state.modules.length ? "All running" : `${state.modules.length - run} stopped`);
    }
    if (state.orchestration) {
      setText("kpi-agents", `${activeAgents().length} / ${agentList().length}`);
      setText("kpi-agents-sub", `${(state.orchestration.tools || {}).total || 0} tools registered`);
    }
    setText("kpi-events", String(state.eventCount));
    setText("kpi-events-sub", { connected: "Stream connected", connecting: "Connecting…", disconnected: "Stream disconnected" }[state.stream]);

    // Resources
    const meters = [];
    const meter = (label, pct, detail) => {
      if (pct === undefined) return;
      const p = Math.max(0, Math.min(100, Number(pct)));
      const cls = p >= 90 ? "bad" : p >= 75 ? "warn" : "";
      meters.push(`
        <div>
          <div class="meter-head"><span>${esc(label)}</span><strong>${p.toFixed(p < 10 ? 1 : 0)}%</strong></div>
          <div class="meter-track" role="meter" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${p.toFixed(0)}"><div class="meter-fill ${cls}" style="width:${p}%"></div></div>
          ${detail ? `<div class="meter-detail">${esc(detail)}</div>` : ""}
        </div>`);
    };
    meter("CPU", gauge("cpu_usage_percent"));
    meter("Memory", gauge("memory_percent"),
      gauge("memory_used_bytes") !== undefined ? `${fmtBytes(gauge("memory_used_bytes"))} of ${fmtBytes(gauge("memory_total_bytes"))}` : "");
    meter("Disk", gauge("disk_percent"),
      gauge("disk_used_bytes") !== undefined ? `${fmtBytes(gauge("disk_used_bytes"))} of ${fmtBytes(gauge("disk_total_bytes"))}` : "");
    setHtml("resource-meters", meters.length ? meters.join("") : '<p class="empty">No resource data reported yet.</p>');

    const facts = [];
    if (state.metrics && state.metrics.uptime_seconds !== undefined) facts.push(["Uptime", fmtUptime(state.metrics.uptime_seconds)]);
    if (gauge("load_avg_1min") !== undefined) facts.push(["Load (1 min)", Number(gauge("load_avg_1min")).toFixed(2)]);
    if (gauge("process_count") !== undefined) facts.push(["Processes", gauge("process_count")]);
    if (gauge("event_queue_depth") !== undefined) facts.push(["Event queue", gauge("event_queue_depth")]);
    setHtml("resource-facts", facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join(""));

    // Services + event bus
    if (h && Array.isArray(h.services)) {
      const names = h.services.map((s) => (typeof s === "string" ? s : s.name || JSON.stringify(s)));
      setHtml("services-list", chips(names, "No services registered"));
      setText("services-count", `${names.length} registered`);
    }
    if (h && h.event_bus) setHtml("bus-facts", kv(h.event_bus));
    renderRecent();
  }

  function renderRecent() {
    const items = state.events.slice(0, 6);
    setHtml("recent-events", items.length
      ? items.map((e) => `<li><span class="t">${esc(fmtTime(e.timestamp))}</span><span class="n" title="${esc(e.type)}">${esc(e.type || "unknown.event")}</span>${badge(e.priority)}</li>`).join("")
      : '<li class="empty">Waiting for events…</li>');
  }

  /* ---------- render: agents ---------- */
  function renderAgents() {
    const o = state.orchestration;
    if (!o) { setPill($("agents-status"), "Unavailable", "bad"); return; }
    const agents = agentList();
    const tools = o.tools || {};
    const sched = o.scheduler || {};

    setPill($("agents-status"), o.available ? (o.running ? "Running" : "Stopped") : "Not loaded", o.running ? "ok" : "warn");
    setHtml("agent-facts", [
      ["Registered agents", agents.length],
      ["Active agents", activeAgents().length],
      ["Tasks running", `${sched.running_tasks || 0} / ${sched.max_concurrent || 0}`],
      ["Tools", tools.total || 0],
    ].map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join(""));

    setText("agents-count", `${agents.length} total`);
    setHtml("agent-grid", agents.length ? agents.map((a) => {
      const caps = (a.capabilities || []).map((c) => c.name || c);
      const tone = ["running", "ready", "waiting"].includes(a.state) ? "ok" : a.state === "failed" ? "bad" : "";
      return `
        <article class="agent">
          <div class="agent-top"><strong>${esc(a.name || a.id)}</strong><span class="badge ${tone ? `badge-${tone}` : ""}">${esc(titleCase(a.state || "unknown"))}</span></div>
          <p>${esc(a.description || "No description provided.")}</p>
          <div><div class="label">Capabilities</div><div class="chips">${chips(caps)}</div></div>
          <div><div class="label">Listens to</div><div class="chips">${chips(a.subscribed_events, "Nothing")}</div></div>
          <div class="agent-meta">${esc(a.interval_seconds == null ? "Event-driven" : `Runs every ${a.interval_seconds}s`)} · ${esc(a.id)}</div>
        </article>`;
    }).join("") : '<p class="empty">No agents are registered.</p>');

    const metadata = Array.isArray(tools.metadata) ? tools.metadata : [];
    const names = metadata.length ? metadata : (Array.isArray(tools.names) ? tools.names : []);
    setText("tools-count", `${names.length} total`);
    setHtml("tool-list", names.length
      ? names.map((tool) => {
        if (typeof tool === "string") return `<span class="chip">${esc(tool)}</span>`;
        const label = `${tool.name} · ${tool.provider || "local"}`;
        return `<span class="chip" title="${esc(tool.qualified_name || tool.name)}">${esc(label)}</span>`;
      }).join("")
      : '<span class="empty">No tools are registered.</span>');
    setHtml("runtime-facts", kv({
      router_running: (o.router || {}).running,
      router_subscribed: (o.router || {}).subscribed,
      max_concurrent_tasks: sched.max_concurrent,
      pending_tasks: sched.pending_tasks,
      memory_manager: (o.runtime || {}).memory_manager,
      llm_manager: (o.runtime || {}).llm_manager,
      mcp_connections: tools.mcp_connections,
    }, { router_running: "Router running", router_subscribed: "Router subscribed", mcp_connections: "MCP connections", llm_manager: "LLM manager" }));
    renderGenerated();
  }

  function renderGenerated() {
    const items = state.generated;
    if (!items) {
      setText("generated-count", "Unavailable");
      setHtml("generated-list", '<li class="empty">Could not load generated artifacts.</li>');
      return;
    }
    setText("generated-count", `${items.length} total`);
    setHtml("generated-list", items.length ? items.map((a) => {
      const tone = a.status === "enabled" ? "ok" : a.status === "approved" ? "info" : a.status === "rejected" ? "bad" : "warn";
      const actions = [];
      if (a.status === "draft") actions.push(["approve", "Approve"], ["reject", "Reject"]);
      if (a.status === "approved" || a.status === "disabled") actions.push(["enable", "Enable"]);
      if (a.status === "enabled") actions.push(["disable", "Disable"]);
      return `<li class="list-row">
        <span class="row-icon"><svg class="icon"><use href="#${a.kind === "agent" ? "i-agents" : "i-plug"}"/></svg></span>
        <div class="row-main">
          <strong>${esc(a.name)} <span class="chip">${esc(a.kind)}</span></strong>
          <span>${esc(a.description || "No description")} · v${esc(a.version || "1.0.0")}</span>
        </div>
        <div class="row-meta">
          <span class="badge badge-${tone}">${esc(titleCase(a.status))}</span>
          <span class="card-note">${esc(fmtDate(a.updated_at))}</span>
        </div>
        <div class="row-actions">
          ${actions.map(([action, label]) => `<button class="btn btn-ghost" type="button" data-generated-id="${esc(a.id)}" data-generated-action="${action}">${label}</button>`).join("")}
        </div>
      </li>`;
    }).join("") : '<li class="empty">No generated artifacts yet.</li>');
    renderRuns();
  }

  function renderRuns() {
    const runs = state.runs;
    if (!runs) {
      setText("run-count", "Unavailable");
      setHtml("run-list", '<li class="empty">Could not load runs.</li>');
      return;
    }
    setText("run-count", `${runs.length} recent`);
    setHtml("run-list", runs.length ? runs.map((run) => {
      const tone = run.status === "succeeded" ? "ok" : run.status === "failed" ? "bad" : "warn";
      const resumable = run.status === "failed" || run.status === "queued";
      return `<li class="list-row">
        <span class="row-icon"><svg class="icon"><use href="#i-activity"/></svg></span>
        <div class="row-main">
          <strong>${esc(run.status)} <span class="chip">${esc(run.agent_id || "Chatbot")}</span></strong>
          <span>${esc(fmtDate(run.created_at))}${run.error ? ` · ${esc(run.error).slice(0, 160)}` : ""}</span>
          <div class="run-timeline" id="run-timeline-${esc(run.id)}" hidden></div>
        </div>
        <div class="row-actions">
          <button class="btn btn-ghost" type="button" data-run-timeline="${esc(run.id)}">Trace</button>
          ${resumable ? `<button class="btn btn-ghost" type="button" data-run-resume="${esc(run.id)}">Resume</button>` : ""}
        </div>
      </li>`;
    }).join("") : '<li class="empty">No agent runs yet.</li>');
  }

  /* ---------- render: inbox ---------- */
  function recipeForAgent(agentId) {
    return (state.recipes || []).find((r) => r.agent_id === agentId || r.id === agentId) || null;
  }

  function scheduleCadence(s) {
    if (s.schedule_type === "weekly") {
      const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
      return `${days[s.weekday || 0] || "Weekly"} ${s.time_of_day || ""}`;
    }
    if (s.schedule_type === "interval") return `Every ${s.interval_minutes || 60} min`;
    return `Daily ${s.time_of_day || ""}`;
  }

  function renderScheduleOptions() {
    const select = $("schedule-agent");
    if (!select) return;
    const current = select.value;
    const available = (state.recipes || []).filter((r) => r.status === "implemented" && r.agent_id);
    select.innerHTML = available.length
      ? available.map((r) => `<option value="${esc(r.agent_id)}">${esc(r.name)}</option>`).join("")
      : '<option value="">No installed agents</option>';
    if (available.some((r) => r.agent_id === current)) select.value = current;
    updateScheduleModes();
  }

  function updateScheduleModes() {
    const select = $("schedule-mode");
    if (!select) return;
    const recipe = recipeForAgent($("schedule-agent").value);
    const modes = (recipe && recipe.schedule_modes) || [];
    const current = select.value;
    select.innerHTML = '<option value="">Default</option>' +
      modes.map((m) => `<option value="${esc(m)}">${esc(titleCase(m))}</option>`).join("");
    if (modes.includes(current)) select.value = current;
    else if (recipe && recipe.default_mode) select.value = recipe.default_mode;
  }

  function renderInbox() {
    const notes = state.notifications;
    setPill($("inbox-unread"), state.unread ? `${state.unread} unread` : "Up to date", state.unread ? "warn" : "ok");
    if (!notes) {
      setHtml("notification-list", '<li class="empty empty-pad">Could not load notifications.</li>');
    } else if (!notes.length) {
      setHtml("notification-list", '<li class="empty empty-pad">No agent updates yet. Create a schedule below.</li>');
    } else {
      setHtml("notification-list", notes.map((n) => {
        const unread = !n.read_at;
        const scheduleId = n.data?.schedule_id;
        return `<li class="list-row">
          <span class="row-icon"><svg class="icon"><use href="#i-info"/></svg></span>
          <div class="row-main">
            <strong>${unread ? '<span class="pill pill-warn">New</span> ' : ""}${esc(n.title)}</strong>
            <span>${esc(fmtDateTime(n.created_at))} · ${esc(n.kind)}</span>
            <div class="card-note" style="white-space:pre-wrap">${esc(n.body || "")}</div>
          </div>
          <div class="row-actions">
            ${unread ? `<button class="btn btn-ghost" type="button" data-notification-read="${esc(n.id)}">Mark read</button>` : ""}
            ${scheduleId ? `<button class="btn btn-ghost" type="button" data-schedule-run="${esc(scheduleId)}">Run again</button>` : ""}
          </div>
        </li>`;
      }).join(""));
    }

    const recipes = (state.recipes || []).filter((r) => r.status === "implemented");
    setText("recipe-count", `${recipes.length} available`);
    setHtml("recipe-list", recipes.length ? recipes.map((r) =>
      `<button class="chip" type="button" data-recipe="${esc(r.agent_id || r.id)}" title="${esc(r.pitch)}">${esc(r.name)} · ${esc(r.architecture)}</button>`
    ).join("") : '<span class="empty">No agent recipes are available.</span>');

    renderScheduleOptions();
    const schedules = state.schedules;
    setText("schedule-count", schedules ? `${schedules.length} total` : "Unavailable");
    if (!schedules) {
      setHtml("schedule-list", '<li class="empty empty-pad">Could not load schedules.</li>');
    } else if (!schedules.length) {
      setHtml("schedule-list", '<li class="empty empty-pad">No schedules yet. Pick a recipe and create one below.</li>');
    } else {
      setHtml("schedule-list", schedules.map((s) => {
        const tone = !s.enabled ? "" : s.last_error ? "warn" : "ok";
        return `<li class="list-row">
          <span class="row-icon"><svg class="icon"><use href="#i-activity"/></svg></span>
          <div class="row-main">
            <strong>${esc(s.name)} <span class="badge ${tone ? `badge-${tone}` : ""}">${esc(s.enabled ? "Active" : "Paused")}</span></strong>
            <span>${esc(s.agent_id)} · ${esc(scheduleCadence(s))} · ${esc(s.timezone)}</span>
            <span>${s.next_run_at ? `Next: ${esc(fmtDateTime(s.next_run_at))}` : "No next run"}${s.last_error ? ` · ${esc(String(s.last_error).slice(0, 120))}` : ""}</span>
          </div>
          <div class="row-actions">
            <button class="btn btn-ghost" type="button" data-schedule-run="${esc(s.id)}">Run</button>
            <button class="btn btn-ghost" type="button" data-schedule-runs="${esc(s.id)}">Runs</button>
            <button class="btn btn-ghost" type="button" data-schedule-edit="${esc(s.id)}">Edit</button>
            <button class="btn btn-ghost" type="button" data-schedule-toggle="${esc(s.id)}">${s.enabled ? "Pause" : "Resume"}</button>
            <button class="btn btn-ghost" type="button" data-schedule-delete="${esc(s.id)}">Delete</button>
          </div>
        </li>`;
      }).join(""));
    }

    renderScheduleRuns();
  }

  function renderScheduleRuns() {
    const runs = state.scheduleRuns;
    const count = $("schedule-runs-count");
    if (count) count.textContent = runs ? `${runs.length} recent` : "";
    if (!runs) return;
    setHtml("schedule-runs", runs.length ? runs.map((run) => `
      <li class="list-row">
        <span class="row-icon"><svg class="icon"><use href="#i-activity"/></svg></span>
        <div class="row-main">
          <strong>${esc(run.status)} <span class="chip">${esc(run.agent_id || "agent")}</span></strong>
          <span>${esc(fmtDateTime(run.completed_at || run.started_at))}</span>
          <div class="card-note" style="white-space:pre-wrap">${esc(run.error || run.result || "No result recorded.")}</div>
        </div>
      </li>`).join("") : '<li class="empty empty-pad">No runs for this schedule yet.</li>');
  }

  function resetScheduleForm() {
    state.editingScheduleId = null;
    const form = $("schedule-form");
    if (form) form.reset();
    setText("schedule-form-mode", "New schedule");
    setText("schedule-submit", "Create schedule");
    $("schedule-cancel").hidden = true;
    $("schedule-time").value = "08:00";
    $("schedule-timezone").value = "UTC";
    $("schedule-interval").value = "60";
    $("schedule-webhook").checked = false;
    $("schedule-push").checked = false;
    $("schedule-enabled").checked = true;
    renderScheduleOptions();
  }

  function fillScheduleForm(recipeId) {
    const recipe = (state.recipes || []).find((r) => (r.agent_id || r.id) === recipeId);
    if (!recipe) return;
    const defaults = recipe.default_schedule || {};
    $("schedule-agent").value = recipe.agent_id || recipe.id;
    $("schedule-name").value = recipe.name || "";
    $("schedule-message").value = `Generate the ${String(recipe.name || "agent").toLowerCase()}.`;
    $("schedule-type").value = defaults.schedule_type || "daily";
    $("schedule-time").value = defaults.time_of_day || "08:00";
    $("schedule-weekday").value = String(defaults.weekday ?? 0);
    $("schedule-timezone").value = defaults.timezone || "UTC";
    updateScheduleModes();
    if (defaults.input && defaults.input.mode) $("schedule-mode").value = defaults.input.mode;
    setResult($("schedule-result"), `${recipe.name} selected.`);
  }

  function fillScheduleEditor(schedule) {
    state.editingScheduleId = schedule.id;
    $("schedule-agent").value = schedule.agent_id;
    $("schedule-name").value = schedule.name || "";
    $("schedule-message").value = schedule.message || "";
    $("schedule-type").value = schedule.schedule_type || "daily";
    $("schedule-time").value = schedule.time_of_day || "08:00";
    $("schedule-weekday").value = String(schedule.weekday ?? 0);
    $("schedule-interval").value = String(schedule.interval_minutes || 60);
    $("schedule-timezone").value = schedule.timezone || "UTC";
    updateScheduleModes();
    $("schedule-mode").value = schedule.input?.mode || "";
    $("schedule-quiet-start").value = schedule.quiet_hours_start || "";
    $("schedule-quiet-end").value = schedule.quiet_hours_end || "";
    $("schedule-webhook").checked = (schedule.channels || []).includes("webhook");
    $("schedule-push").checked = (schedule.channels || []).includes("push");
    $("schedule-enabled").checked = Boolean(schedule.enabled);
    setText("schedule-form-mode", `Editing ${schedule.name}`);
    setText("schedule-submit", "Save changes");
    $("schedule-cancel").hidden = false;
    $("schedule-result").classList.remove("error", "success");
    $("schedule-result").textContent = "";
  }

  function schedulePayload() {
    const type = $("schedule-type").value;
    const mode = $("schedule-mode").value;
    const input = {};
    if (mode) input.mode = mode;
    const existing = (state.schedules || []).find((s) => s.id === state.editingScheduleId);
    if (existing?.input?.household_id) input.household_id = existing.input.household_id;
    return {
      agent_id: $("schedule-agent").value,
      name: $("schedule-name").value.trim(),
      message: $("schedule-message").value.trim(),
      schedule_type: type,
      time_of_day: type === "interval" ? null : $("schedule-time").value,
      weekday: type === "weekly" ? Number($("schedule-weekday").value) : null,
      interval_minutes: type === "interval" ? Number($("schedule-interval").value) : null,
      timezone: $("schedule-timezone").value.trim() || "UTC",
      quiet_hours_start: $("schedule-quiet-start").value || null,
      quiet_hours_end: $("schedule-quiet-end").value || null,
      channels: ["inapp", ...($("schedule-webhook").checked ? ["webhook"] : []), ...($("schedule-push").checked ? ["push"] : [])],
      input,
      enabled: $("schedule-enabled").checked,
    };
  }


  function renderSecurity() {
    const s = state.security;
    if (!s) { setPill($("security-status"), "Unavailable", "bad"); return; }
    const a = s.authentication || {}, d = s.event_dispatch || {}, r = s.agent_runtime || {}, z = s.authorization || {};

    setPill($("security-status"), a.admin_configured ? "Protected" : "Setup required", a.admin_configured ? "ok" : "warn");

    const hours = Math.round((a.session_max_age_seconds || 0) / 3600);
    const runtimeOff = Object.entries(r).filter(([, v]) => !v).map(([k]) => titleCase(k.replace("_require_permission", "")));
    const checks = [
      [a.admin_configured, "Admin account", a.admin_configured ? "An admin account is set up." : "No admin account yet. Finish setup at /setup."],
      [true, "Password storage", `Passwords are hashed with ${a.password_hashing || "bcrypt"}. Recovery codes are hashed and never shown.`],
      [true, "Sessions", `Signed "${a.session_cookie || "session"}" cookie, SameSite ${a.same_site || "lax"}, expires after ${hours || "?"} h.`],
      [a.https_only, "HTTPS", a.https_only ? "Cookies are only sent over HTTPS." : "Not enforced. Fine for local development; turn it on before exposing VIRA to a network."],
      [d.security_enabled, "Event verification", d.security_enabled ? `On. Unauthorized events: ${d.unauthorized_event_behavior}.` : "Event security checks are off."],
      [d.pipeline_enabled, "Event pipeline", d.pipeline_enabled ? "Events pass through the enrichment pipeline." : "Event pipeline is off."],
      [!runtimeOff.length, "Agent permissions", !runtimeOff.length ? "LLM, tool and memory calls all require permission." : `Permission not required for: ${runtimeOff.join(", ")}.`],
    ];
    setHtml("security-checks", checks.map(([ok, title, text]) => `
      <li class="${ok ? "ok" : "warn"}">
        <svg class="icon"><use href="#${ok ? "i-ok" : "i-warn"}"/></svg>
        <div><strong>${esc(title)}</strong><span>${esc(text)}</span></div>
      </li>`).join(""));

    setHtml("perm-granted", chips(z.granted_permissions, "None granted"));
    setHtml("perm-default", chips(z.default_permissions, "None"));
    setHtml("perm-facts", kv({ deny_rules: z.deny_rules_configured }, { deny_rules: "Deny rules configured" }));

    const tools = (s.tools && s.tools.registered) || [];
    setHtml("tool-policies", tools.length ? tools.map((t) =>
      `<li><strong>${esc(t.name)}</strong><span class="chips">${chips(t.actions, "No actions declared")}</span></li>`).join("")
      : '<li class="empty">No registered tools.</li>');

    setHtml("security-notices", (s.visibility_limits || []).map((n) =>
      `<li><svg class="icon"><use href="#i-info"/></svg><span>${esc(n)}</span></li>`).join("") || '<li class="empty">Nothing to report.</li>');

    renderApprovals();
  }

  function renderApprovals() {
    const items = state.approvals;
    if (!items) {
      setPill($("approval-count"), "Unavailable", "bad");
      setHtml("approval-list", '<li class="empty">Could not load approvals.</li>');
      return;
    }
    setPill($("approval-count"), `${items.length} pending`, items.length ? "warn" : "ok");
    setHtml("approval-list", items.length ? items.map((a) => {
      let args = "";
      try { args = JSON.stringify(a.arguments || {}); } catch (e) { args = ""; }
      return `<li class="warn">
        <svg class="icon"><use href="#i-warn"/></svg>
        <div>
          <strong>${esc(a.tool_name)} · ${esc(a.action || "execute")}</strong>
          <span>${esc(a.reason || "Destructive tool call")} · expires ${esc(a.expires_at || "")}</span>
          <span class="mono">${esc(args.slice(0, 500))}</span>
          <span style="display:flex;gap:.4rem;margin-top:.45rem">
            <button class="btn btn-ghost" type="button" data-approval-id="${esc(a.id)}" data-approval-decision="approve">Approve</button>
            <button class="btn btn-ghost" type="button" data-approval-id="${esc(a.id)}" data-approval-decision="deny">Deny</button>
          </span>
        </div>
      </li>`;
    }).join("") : '<li class="empty">No pending approvals.</li>');
  }

  /* ---------- render: modules ---------- */
  function renderModules() {
    const mods = state.modules;
    if (!mods) { setHtml("module-list", '<li class="empty">Could not load modules.</li>'); return; }
    setText("module-count", `${mods.filter((m) => m.running).length} of ${mods.length} running`);
    setHtml("module-list", mods.length ? mods.map((m) =>
      `<li><span class="name">${esc(m.name)}</span><span class="badge ${m.running ? "badge-ok" : "badge-bad"}">${m.running ? "Running" : "Stopped"}</span></li>`).join("")
      : '<li class="empty">No modules loaded.</li>');
  }

  /* ---------- render: extensions ---------- */
  function statusTone(status) {
    const value = String(status || "").toLowerCase();
    if (["active", "loaded", "connected", "enabled", "ok"].includes(value)) return "ok";
    if (["error", "failed", "bad"].includes(value)) return "bad";
    if (["disabled", "stopped", "missing"].includes(value)) return "warn";
    return "";
  }

  function renderExtensions() {
    const plugins = state.plugins && Array.isArray(state.plugins.plugins) ? state.plugins.plugins : null;
    const loaded = plugins ? plugins.filter((p) => p.loaded || p.status === "active").length : null;
    setText("kpi-plugins", plugins ? `${loaded} / ${plugins.length}` : "—");
    setText("kpi-plugins-sub", plugins ? "Discovered extensions" : "Admin access required");
    setText("plugin-count", plugins ? `${plugins.length} total` : "");

    if (!plugins) {
      setHtml("plugin-list", '<li class="empty empty-pad">Sign in as an administrator to manage plugins.</li>');
    } else if (!plugins.length) {
      setHtml("plugin-list", '<li class="empty empty-pad">No plugins discovered. Add a manifest to a configured plugin directory.</li>');
    } else {
      setHtml("plugin-list", plugins.map((p) => {
        const tone = statusTone(p.status);
        const perms = (p.permissions || []).slice(0, 4);
        return `<li class="ext-item">
          <span class="ext-icon" aria-hidden="true">${esc(String(p.name || p.id || "P").charAt(0).toUpperCase())}</span>
          <div class="ext-body">
            <strong>${esc(p.name || p.id)}</strong>
            <p>${esc(p.description || "No description provided.")}</p>
            <div class="ext-meta">
              <span class="badge ${tone ? `badge-${tone}` : ""}">${esc(titleCase(p.status || "discovered"))}</span>
              <span class="chip">v${esc(p.version)}</span>
              ${p.author ? `<span class="card-note">${esc(p.author)}</span>` : ""}
            </div>
            ${perms.length ? `<div class="chips" style="margin-top:.45rem">${perms.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}</div>` : ""}
          </div>
          <div class="row-actions">
            <button class="btn btn-ghost" type="button" data-plugin-id="${esc(p.id)}" data-plugin-action="${p.enabled ? "disable" : "enable"}">${p.enabled ? "Disable" : "Enable"}</button>
            <button class="btn btn-ghost" type="button" data-plugin-id="${esc(p.id)}" data-plugin-action="reload">Reload</button>
          </div>
        </li>`;
      }).join(""));
    }

    const servers = state.mcpServers;
    setText("kpi-mcp", servers ? `${servers.filter((s) => s.enabled).length} / ${servers.length}` : "—");
    setText("kpi-mcp-sub", servers ? "Enabled / installed" : "Admin access required");
    setText("mcp-count", servers ? `${servers.length} installed` : "");
    if (!servers) {
      setHtml("mcp-list", '<li class="empty empty-pad">Sign in as an administrator to inspect MCP servers.</li>');
    } else if (!servers.length) {
      setHtml("mcp-list", '<li class="empty empty-pad">No MCP servers installed yet. Choose one from the marketplace.</li>');
    } else {
      setHtml("mcp-list", servers.map((s) => `
        <li class="ext-item">
          <span class="ext-icon" aria-hidden="true"><svg class="icon"><use href="#i-server"/></svg></span>
          <div class="ext-body">
            <strong>${esc(s.name)}</strong>
            <p>${esc(s.description || `${titleCase(s.transport || "stdio")} transport`)}</p>
            <div class="ext-meta">
              <span class="badge ${s.enabled ? "badge-ok" : "badge-warn"}">${s.enabled ? "Enabled" : "Disabled"}</span>
              <span class="chip">${esc(s.transport || "stdio")}</span>
              ${(s.categories || []).slice(0, 2).map((c) => `<span class="chip">${esc(c)}</span>`).join("")}
            </div>
          </div>
          <div class="row-actions">
            <button class="btn btn-ghost" type="button" data-mcp-id="${esc(s.id)}" data-mcp-action="${s.enabled ? "disable" : "enable"}">${s.enabled ? "Disable" : "Enable"}</button>
            <button class="btn btn-ghost" type="button" data-mcp-id="${esc(s.id)}" data-mcp-action="connect">Connect</button>
            <button class="btn btn-ghost" type="button" data-mcp-id="${esc(s.id)}" data-mcp-action="delete">Remove</button>
          </div>
        </li>`).join(""));
    }

    const tools = state.mcpTools;
    setText("kpi-mcp-tools", tools ? String(tools.length) : "—");
    setText("kpi-mcp-tools-sub", tools ? "Registered from MCP" : "Admin access required");

    const market = state.marketplace;
    setText("kpi-marketplace", market ? String(market.length) : "—");
    if (!market) {
      setHtml("marketplace-list", '<p class="empty">Sign in as an administrator to browse the marketplace.</p>');
    } else if (!market.length) {
      setHtml("marketplace-list", '<p class="empty">No marketplace entries available.</p>');
    } else {
      setHtml("marketplace-list", market.map((entry) => `
        <article class="market-item">
          <strong>${esc(entry.display_name || entry.name)}</strong>
          <p>${esc(entry.description || "")}</p>
          <div class="chips" style="margin-top:.55rem">${(entry.categories || []).map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
          <button class="btn btn-ghost" type="button" style="margin-top:.7rem" data-install-mcp="${esc(entry.id)}">Install</button>
        </article>`).join(""));
    }
  }

  /* ---------- render: devices ---------- */
  function renderDeviceInsight() {
    const d = state.deviceInsight;
    if (!d) {
      setHtml("device-insight", '<p class="empty">No insight data yet. Capture a few events from VIRA Link, then select a device.</p>');
      return;
    }
    const totals = d.totals || {};
    const battery = d.battery || {};
    const health = d.health || {};
    const facts = [
      ["Screen time", fmtDurationMs(totals.screen_ms)],
      ["App time", fmtDurationMs(totals.app_ms)],
      ["Focus score", `${totals.focus_score || 0}%`],
      ["Unlocks", fmtNumber(totals.unlocks)],
      ["Battery", battery.level_percent != null ? `${battery.level_percent}%${battery.charging ? " · charging" : ""}` : "—"],
      ["Warnings", (health.warnings || []).length ? health.warnings.join("; ") : "None"],
    ];
    const apps = (d.top_apps || []).slice(0, 5).map((app) => `
      <div><dt>${esc(app.label || app.package)}</dt><dd>${fmtDurationMs(app.foreground_ms)}</dd></div>`).join("");
    setHtml("device-insight", `
      <p class="insight-copy">${esc(d.summary || "No summary available.")}</p>
      <dl class="kv kv-inline">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
      <h3>Top apps</h3>
      ${apps ? `<dl class="kv">${apps}</dl>` : '<p class="empty">No app usage captured.</p>'}`);
  }

  function renderAccess() {
    const access = state.access;
    const box = $("access-status");
    if (!box) return;
    if (!access) {
      setText("access-mode", "Unavailable");
      box.innerHTML = '<p class="empty">Could not load access provider status.</p>';
      return;
    }
    const resolved = access.resolved || {};
    const warnings = access.warnings || [];
    const providers = (access.providers || []).map((provider) => {
      const tone = provider.available ? "ok" : "warn";
      const endpoint = provider.endpoint?.url || provider.reason || "Unavailable";
      return `<li class="access-provider">
        <span class="badge badge-${tone}">${esc(provider.label || provider.kind)}</span>
        <span class="access-provider-detail">${esc(endpoint)}</span>
      </li>`;
    }).join("");
    setText("access-mode", titleCase(String(access.mode || "auto")));
    box.innerHTML = `
      <div class="access-head">
        <div>
          <span class="kpi-label">Pairing address</span>
          <strong class="access-url">${esc(resolved.url || "—")}</strong>
          <p class="pairing-meta">${esc(resolved.label || "")}${resolved.detail ? ` · ${esc(resolved.detail)}` : ""}</p>
        </div>
        <span class="chip">${esc(resolved.kind || "unknown")}</span>
      </div>
      <ul class="access-providers">${providers}</ul>
      ${warnings.length ? `<div class="access-warning">${warnings.map((warning) => `<p>${esc(warning)}</p>`).join("")}</div>` : ""}
      ${(resolved.kind === "tailscale") ? '<p class="card-note">Private tailnet only. Nothing is published to the public internet.</p>' : ""}
      <div class="row-actions" style="justify-content:flex-start;margin-top:.8rem">
        <button class="btn btn-ghost" type="button" data-tailscale-open>${access.providers?.some((p) => p.kind === "tailscale" && p.available) ? "Manage Tailscale" : "Set up Tailscale"}</button>
      </div>`;
  }

  function stopTailscalePoll() {
    if (tailscaleTimer) clearInterval(tailscaleTimer);
    tailscaleTimer = null;
  }

  function startTailscalePoll() {
    stopTailscalePoll();
    let attempts = 0;
    tailscaleTimer = setInterval(async () => {
      attempts += 1;
      await loadTailscaleStatus(false);
      const status = state.tailscale;
      if (!status || status.state === "running" || status.state === "not_installed" || attempts >= 200) {
        stopTailscalePoll();
      }
      if (status?.state === "running") await onTailscaleConnected();
    }, 3000);
  }

  async function onTailscaleConnected() {
    stopTailscalePoll();
    await loadAccess();
    renderAccess();
    if ($("pairing-result") && !$("pairing-result").hidden) {
      document.querySelector("[data-pair-device]")?.click();
    }
  }

  function tailscaleStateLabel(status) {
    return {
      running: "Connected",
      needs_login: "Sign-in required",
      stopped: "Stopped",
      starting: "Starting",
      not_installed: "Not installed",
      daemon_unavailable: "Service unavailable",
      error: "Needs attention",
    }[status.state] || titleCase(String(status.state || "unknown"));
  }

  function tailscaleAuthKeyForm() {
    return `<details class="tailscale-advanced">
      <summary>Use an auth key instead</summary>
      <p class="card-note">For headless servers and Docker. Create a key in the Tailscale admin console. It is used once and never stored by VIRA.</p>
      <div class="tailscale-key-row">
        <input id="tailscale-auth-key" type="password" placeholder="tskey-auth-…" autocomplete="off" spellcheck="false">
        <button class="btn btn-ghost" type="button" data-tailscale-authkey>Connect</button>
      </div>
    </details>`;
  }

  function renderTailscalePanel() {
    const box = $("tailscale-panel");
    if (!box) return;
    if (!state.tailscaleOpen) { box.hidden = true; return; }
    box.hidden = false;
    const status = state.tailscale;
    if (!status) {
      box.innerHTML = '<p class="empty">Checking Tailscale…</p>';
      return;
    }
    const label = tailscaleStateLabel(status);
    const steps = (status.next_steps || []).map((step) => `<li>${esc(step)}</li>`).join("");
    let body = "";
    if (status.state === "running") {
      body = `<p class="insight-copy">This server is connected to your private tailnet. Pairing uses the address below.</p>
        <span class="kpi-label">Private address</span>
        <strong class="access-url">${esc(status.address || "—")}</strong>
        ${status.tailnet ? `<p class="pairing-meta">Tailnet · ${esc(status.tailnet)}</p>` : ""}
        <div class="row-actions" style="justify-content:flex-start;margin-top:.7rem">
          <button class="btn btn-ghost" type="button" data-tailscale-copy-address="${esc(status.address || "")}">Copy address</button>
          <button class="btn btn-ghost" type="button" data-tailscale-close>Done</button>
        </div>`;
    } else if (status.state === "not_installed") {
      body = `<p class="insight-copy">Install Tailscale on the machine that runs VIRA, then come back and refresh.</p>
        <pre class="code">${esc(status.install_command || "Install Tailscale for your platform.")}</pre>
        ${steps ? `<ul class="tailscale-steps">${steps}</ul>` : ""}
        <div class="row-actions" style="justify-content:flex-start;margin-top:.7rem">
          <button class="btn btn-ghost" type="button" data-tailscale-copy-install="${esc(status.install_command || "")}">Copy command</button>
          <button class="btn btn-ghost" type="button" data-tailscale-refresh>Refresh</button>
        </div>`;
    } else if (status.state === "needs_login" && status.auth_url) {
      body = `<p class="insight-copy">Sign in to Tailscale or create an account. VIRA detects the connection automatically.</p>
        <div class="tailscale-login">
          <img class="pairing-qr" src="${esc(status.auth_qr)}" alt="Tailscale login QR code" width="168" height="168">
          <div>
            <a class="btn" href="${esc(status.auth_url)}" target="_blank" rel="noopener noreferrer">Open Tailscale login</a>
            <p class="pairing-meta">Scan the QR or open the link, then finish in the browser.</p>
            <p class="card-note">${status.login_in_progress ? "Waiting for Tailscale…" : "Not connected yet."}</p>
          </div>
        </div>
        ${tailscaleAuthKeyForm()}`;
    } else if (status.state === "needs_login") {
      body = `<p class="insight-copy">Waiting for Tailscale to provide a login URL. Keep this panel open.</p>
        ${steps ? `<ul class="tailscale-steps">${steps}</ul>` : ""}
        <div class="row-actions" style="justify-content:flex-start;margin-top:.7rem">
          <button class="btn btn-ghost" type="button" data-tailscale-refresh>Refresh</button>
        </div>
        ${tailscaleAuthKeyForm()}`;
    } else {
      body = `<p class="insight-copy">${esc(status.reason || (status.state === "stopped" ? "Tailscale is installed but not connected." : "Tailscale needs attention."))}</p>
        ${steps ? `<ul class="tailscale-steps">${steps}</ul>` : ""}
        <div class="row-actions" style="justify-content:flex-start;margin-top:.7rem">
          ${status.can_connect ? '<button class="btn" type="button" data-tailscale-connect>Connect Tailscale</button>' : ""}
          <button class="btn btn-ghost" type="button" data-tailscale-refresh>Refresh</button>
        </div>
        ${tailscaleAuthKeyForm()}`;
    }
    box.innerHTML = `<div class="tailscale-panel-head">
        <div>
          <span class="kpi-label">Tailscale</span>
          <strong>${esc(label)}</strong>
        </div>
        <span class="badge badge-${status.state === "running" ? "ok" : status.state === "not_installed" || status.state === "daemon_unavailable" ? "warn" : "info"}">${esc(label)}</span>
      </div>${body}`;
  }

  async function loadTailscaleStatus(startPoll = false) {
    const previous = state.tailscale ? JSON.stringify(state.tailscale) : null;
    const r = await fetchJson("/api/v1/access/tailscale");
    state.tailscale = r.ok ? r.data : {
      state: "error",
      installed: false,
      reason: r.data?.detail || "Could not load Tailscale status.",
      next_steps: [],
      can_connect: false,
    };
    if (JSON.stringify(state.tailscale) !== previous) renderTailscalePanel();
    if (startPoll && (state.tailscale.login_in_progress || state.tailscale.state === "needs_login" || state.tailscale.state === "starting")) {
      startTailscalePoll();
    }
  }

  async function startTailscaleConnection() {
    const r = await fetchJson("/api/v1/access/tailscale/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    state.tailscale = r.ok ? r.data : {
      state: "error",
      installed: true,
      reason: r.data?.detail || "Could not start Tailscale.",
      next_steps: [],
      can_connect: true,
    };
    renderTailscalePanel();
    if (state.tailscale.state === "running") await onTailscaleConnected();
    else if (state.tailscale.login_in_progress || state.tailscale.state === "needs_login") startTailscalePoll();
  }

  async function openTailscalePanel() {
    state.tailscaleOpen = true;
    await loadTailscaleStatus(false);
    renderTailscalePanel();
    if (state.tailscale?.installed && state.tailscale.can_connect && !state.tailscale.login_in_progress) {
      await startTailscaleConnection();
    } else if (state.tailscale?.state === "needs_login" || state.tailscale?.state === "starting") {
      startTailscalePoll();
    }
    $("tailscale-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderPairingCode(data) {
    const box = $("pairing-result");
    if (!box) return;
    const expires = data.expires_at ? new Date(data.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "soon";
    box.hidden = false;
    box.innerHTML = `
      <div class="pairing-body">
        <img class="pairing-qr" src="${esc(data.qr_svg)}" alt="Pairing QR code" width="168" height="168">
        <div>
          <span class="kpi-label">Pairing code</span>
          <strong class="pairing-code">${esc(data.code)}</strong>
          <p class="pairing-meta">Server ${esc(data.server)} · expires ${esc(expires)}</p>
          <p class="pairing-meta">${esc(data.access_label || "Access")}${data.access_detail ? ` · ${esc(data.access_detail)}` : ""}</p>
          ${(data.access_warnings || []).length ? `<p class="access-warning-inline">${esc(data.access_warnings[0])}</p>` : ""}
          <div class="row-actions" style="justify-content:flex-start;margin-top:.6rem">
            <button class="btn btn-ghost" type="button" data-copy-pairing="${esc(data.pairing_uri)}">Copy pairing link</button>
          </div>
        </div>
      </div>`;
  }

  function renderDevices() {
    const devices = state.devices;
    if (!devices) {
      ["kpi-devices", "kpi-devices-active", "kpi-devices-local", "kpi-devices-seen"].forEach((id) => setText(id, "—"));
      setText("kpi-devices-sub", "Sign in to view devices");
      setHtml("device-list", '<li class="empty empty-pad">Could not load devices.</li>');
      renderDeviceInsight();
      return;
    }
    const active = devices.filter((d) => d.status === "active").length;
    const local = devices.filter((d) => d.is_server_local).length;
    const latest = devices.map((d) => d.last_seen_at).filter(Boolean).sort().pop();
    setText("kpi-devices", String(devices.length));
    setText("kpi-devices-sub", `${devices.length === 1 ? "endpoint" : "endpoints"} registered`);
    setText("kpi-devices-active", String(active));
    setText("kpi-devices-active-sub", active ? "Connected or ready" : "None active");
    setText("kpi-devices-local", String(local));
    setText("kpi-devices-local-sub", local ? "This server" : "Remote only");
    setText("kpi-devices-seen", latest ? fmtDate(latest) : "—");
    setText("kpi-devices-seen-sub", latest ? fmtTime(latest) : "No contact yet");
    setText("device-count", `${devices.length} total`);

    setHtml("device-list", devices.length ? devices.map((d) => {
      const tone = d.status === "active" ? "ok" : d.status === "pending" ? "warn" : "bad";
      return `<li class="list-row">
        <span class="row-icon"><svg class="icon"><use href="#i-server"/></svg></span>
        <div class="row-main">
          <strong>${esc(d.display_name)}${d.is_server_local ? ' <span class="chip">server</span>' : ""}</strong>
          <span>${esc(d.platform || "unknown")} · ${esc(d.device_type || "device")} · ${esc(d.os_version || "—")}</span>
        </div>
        <div class="row-meta">
          <span class="badge badge-${tone}">${esc(titleCase(d.status || "unknown"))}</span>
          <span class="card-note">${d.last_seen_at ? `Seen ${fmtDate(d.last_seen_at)}` : "Never seen"}</span>
        </div>
        <div class="row-actions">
          <button class="btn btn-ghost" type="button" data-device-select="${esc(d.device_id)}">Inspect</button>
        </div>
      </li>`;
    }).join("") : '<li class="empty empty-pad">No devices yet. Pair one from VIRA Link.</li>');
    renderDeviceInsight();
  }

  /* ---------- render: knowledge ---------- */
  function renderKnowledge() {
    const docs = state.ragDocs;
    if (!docs) {
      setText("kpi-docs", "—");
      setText("kpi-docs-sub", "Could not load documents");
      setHtml("document-list", '<li class="empty empty-pad">Could not load the knowledge base.</li>');
      return;
    }
    const chunks = docs.reduce((sum, d) => sum + Number(d.chunks || 0), 0);
    setText("kpi-docs", String(docs.length));
    setText("kpi-docs-sub", "Indexed local documents");
    setText("kpi-chunks", fmtNumber(chunks));
    setText("kpi-chunks-sub", "Searchable vector chunks");
    setText("document-count", `${docs.length} documents`);
    setHtml("document-list", docs.length ? docs.map((d) => `
      <li class="list-row">
        <span class="row-icon"><svg class="icon"><use href="#i-info"/></svg></span>
        <div class="row-main">
          <strong>${esc(d.title)}</strong>
          <span>${esc(d.source || "manual")} · ${esc(d.chunks || 0)} chunks · ${fmtDate(d.created_at)}</span>
        </div>
        <div class="row-actions">
          <button class="btn btn-ghost" type="button" data-delete-doc="${esc(d.id)}">Delete</button>
        </div>
      </li>`).join("") : '<li class="empty empty-pad">No documents yet. Add your first reference document.</li>');
  }

  /* ---------- render: automations ---------- */
  function renderWorkflows() {
    const workflows = state.workflows;
    if (!workflows) {
      setText("kpi-workflows", "—");
      setText("kpi-workflows-sub", "Could not load workflows");
      setHtml("workflow-list", '<li class="empty empty-pad">Could not load workflows.</li>');
      return;
    }
    const count = (status) => workflows.filter((w) => w.status === status).length;
    setText("kpi-workflows", String(workflows.length));
    setText("kpi-workflows-sub", "Durable runs");
    setText("kpi-workflows-running", String(count("running")));
    setText("kpi-workflows-running-sub", "In progress");
    setText("kpi-workflows-done", String(count("completed")));
    setText("kpi-workflows-done-sub", "Finished successfully");
    setText("kpi-workflows-failed", String(count("failed")));
    setText("kpi-workflows-failed-sub", "Needs a retry or fix");
    setText("workflow-count", `${workflows.length} total`);
    setHtml("workflow-list", workflows.length ? workflows.map((w) => {
      const tone = w.status === "completed" ? "ok" : w.status === "failed" ? "bad" : w.status === "running" ? "info" : "warn";
      return `<li class="list-row workflow-row">
        <div class="row-main"><strong>${esc(w.name)}</strong><span class="mono">${esc(w.id)}</span></div>
        <span class="badge badge-${tone}">${esc(titleCase(w.status || "pending"))}</span>
        <span class="card-note">${esc(w.error || "No errors")}</span>
        <span class="card-note">${w.updated_at ? fmtDate(w.updated_at) + " " + fmtTime(w.updated_at) : "—"}</span>
        <div class="row-actions">
          ${w.status === "failed" || w.status === "running" ? `<button class="btn btn-ghost" type="button" data-resume-workflow="${esc(w.id)}">Resume</button>` : ""}
          ${w.status === "running" || w.status === "pending" ? `<button class="btn btn-ghost" type="button" data-cancel-workflow="${esc(w.id)}">Cancel</button>` : ""}
        </div>
      </li>`;
    }).join("") : '<li class="empty empty-pad">No workflows yet. Create one through the API to see durable execution here.</li>');
  }

  /* ---------- render: organizations ---------- */
  function renderOrganizations() {
    const orgs = state.orgs;
    if (!orgs) {
      setText("kpi-orgs", "—");
      setText("kpi-orgs-sub", "Could not load organizations");
      setHtml("org-list", '<li class="empty empty-pad">Could not load organizations.</li>');
      return;
    }
    const members = orgs.reduce((sum, o) => sum + Number(o.member_count || 0), 0);
    setText("kpi-orgs", String(orgs.length));
    setText("kpi-orgs-sub", "Teams you belong to");
    setText("kpi-org-members", String(members));
    setText("kpi-org-members-sub", "Across your teams");
    setText("kpi-org-role", orgs[0]?.my_role ? titleCase(orgs[0].my_role) : "—");
    setText("kpi-org-role-sub", orgs.length ? "In your first team" : "Create a team to start");
    setText("org-count", `${orgs.length} teams`);
    setHtml("org-list", orgs.length ? orgs.map((o) => `
      <li class="list-row">
        <span class="row-icon">${esc(String(o.name || "O").charAt(0).toUpperCase())}</span>
        <div class="row-main"><strong>${esc(o.name)}</strong><span>${esc(o.slug)} · ${esc(o.member_count || 0)} members</span></div>
        <span class="badge badge-info">${esc(titleCase(o.my_role || "member"))}</span>
        <div class="row-actions"><span class="chip">${esc(String(o.id).slice(0, 8))}</span></div>
      </li>`).join("") : '<li class="empty empty-pad">No organizations yet. Create your first team.</li>');
  }

  /* ---------- render: files ---------- */
  function renderObjects() {
    const objects = state.objects;
    if (!objects) {
      setText("kpi-objects", "—");
      setText("kpi-objects-sub", "Could not load files");
      setHtml("object-list", '<li class="empty empty-pad">Could not load stored files.</li>');
      return;
    }
    const bytes = objects.reduce((sum, o) => sum + Number(o.size_bytes || 0), 0);
    setText("kpi-objects", String(objects.length));
    setText("kpi-objects-sub", "Stored objects");
    setText("kpi-object-bytes", fmtBytes(bytes));
    setText("kpi-object-bytes-sub", "Total content size");
    setText("object-count", `${objects.length} objects`);
    setHtml("object-list", objects.length ? objects.map((o) => `
      <li class="list-row">
        <span class="row-icon"><svg class="icon"><use href="#i-box"/></svg></span>
        <div class="row-main"><strong>${esc(o.metadata?.filename || o.object_key || o.id)}</strong><span>${esc(o.content_type)} · ${fmtBytes(o.size_bytes)} · ${fmtDate(o.created_at)}</span></div>
        <div class="row-actions">
          <a class="btn btn-ghost" href="/api/v1/objects/${esc(o.id)}" download>Download</a>
          <button class="btn btn-ghost" type="button" data-delete-object="${esc(o.id)}">Delete</button>
        </div>
      </li>`).join("") : '<li class="empty empty-pad">No files stored yet.</li>');
  }

  /* ---------- render: updates ---------- */
  function renderUpdates() {
    const releases = state.releases;
    if (!releases) {
      setText("kpi-releases", "—");
      setHtml("release-list", '<li class="empty empty-pad">Could not load releases.</li>');
      return;
    }
    setText("kpi-releases", String(releases.length));
    setText("kpi-releases-sub", "Published releases");
    setText("release-count", `${releases.length} releases`);
    const latestFor = (product) => releases.filter((r) => r.product === product)
      .sort((a, b) => new Date(b.published_at) - new Date(a.published_at))[0];
    const client = latestFor("client");
    const server = latestFor("server");
    setText("kpi-client-latest", client ? client.version : "—");
    setText("kpi-client-latest-sub", client ? `${titleCase(client.channel)} · ${fmtDate(client.published_at)}` : "No client release");
    setText("kpi-server-latest", server ? server.version : "—");
    setText("kpi-server-latest-sub", server ? `${titleCase(server.channel)} · ${fmtDate(server.published_at)}` : "No server release");
    setHtml("release-list", releases.length ? releases.map((r) => `
      <li class="list-row">
        <span class="row-icon">${r.product === "server" ? "S" : "C"}</span>
        <div class="row-main"><strong>${esc(r.version)} <span class="chip">${esc(r.channel)}</span></strong><span>${esc(r.product)} · ${fmtDate(r.published_at)}</span></div>
        <div class="row-main"><span>${esc(r.notes || "No release notes")}</span>${r.min_version ? `<span>Requires ≥ ${esc(r.min_version)}</span>` : ""}</div>
      </li>`).join("") : '<li class="empty empty-pad">No releases published yet.</li>');
  }

  /* ---------- render: usage ---------- */
  function breakdown(rows, labelKey) {
    if (!rows || !rows.length) return '<p class="empty">Nothing recorded yet.</p>';
    return `<dl class="kv">${rows.map((row) => `
      <div><dt>${esc(row[labelKey] || "unknown")}</dt>
      <dd>${fmtNumber(row.tokens)} tok · ${fmtMoney(row.cost)}</dd></div>`).join("")}</dl>`;
  }

  function renderUsage() {
    const u = state.usage;
    if (!u) {
      setPill($("usage-status"), "Admin access required", "warn");
      setHtml("usage-totals", '<p class="empty">An administrator session is required to view cost and quota data.</p>');
      setHtml("usage-chart", '<p class="empty">No usage data available.</p>');
      setHtml("usage-models", '<p class="empty">No usage data available.</p>');
      setHtml("usage-agents", '<p class="empty">No usage data available.</p>');
      setHtml("usage-quotas", '<li class="empty">No usage data available.</li>');
      setText("quota-count", "");
      return;
    }
    setPill($("usage-status"), "Last 30 days", "ok");
    const totals = u.totals || {};
    const storage = u.storage || {};
    const cards = [
      ["Tokens", fmtNumber(totals.tokens), `${fmtNumber(totals.calls)} LLM calls`],
      ["Estimated cost", fmtMoney(totals.cost_usd), "Provider rates"],
      ["Object storage", fmtBytes(storage.bytes), `${fmtNumber(storage.objects)} objects`],
      ["Device events", fmtNumber(u.device_events), "Visible to you"],
    ];
    setHtml("usage-totals", cards.map(([label, value, note]) => `
      <article class="usage-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`).join(""));

    const daily = u.daily || [];
    if (!daily.length) {
      setHtml("usage-chart", '<p class="empty">No usage recorded yet.</p>');
    } else {
      const max = Math.max(...daily.map((d) => Number(d.tokens) || 0), 1);
      setHtml("usage-chart", daily.map((d) => {
        const pct = Math.max(2, (Number(d.tokens) || 0) / max * 100);
        return `<div class="bar" title="${esc(d.day)} · ${fmtNumber(d.tokens)} tokens">
          <div class="bar-fill" style="height:${pct}%"></div>
          <span class="bar-label">${esc(String(d.day).slice(5))}</span>
        </div>`;
      }).join(""));
    }

    setHtml("usage-models", breakdown(u.models, "model"));
    setHtml("usage-agents", breakdown(u.agents, "agent_id"));

    const quotas = u.quotas || [];
    setText("quota-count", `${quotas.length} configured`);
    setHtml("usage-quotas", quotas.length ? quotas.map((q) => {
      const current = q.current || {};
      const parts = [];
      if (q.token_limit != null) parts.push(`${fmtNumber(current.tokens)} / ${fmtNumber(q.token_limit)} tokens`);
      if (q.cost_limit_usd != null) parts.push(`${fmtMoney(current.cost_usd)} / ${fmtMoney(q.cost_limit_usd)}`);
      return `<li><strong>${esc(q.scope)} · ${esc(q.subject_id)}</strong><span class="card-note">${esc(parts.join(" · ") || "No limit")} / ${esc(q.period)}</span></li>`;
    }).join("") : '<li class="empty">No quotas configured yet. Use the admin API to add token or cost limits.</li>');
  }

  function renderAll() {
    renderOverview(); renderAccess(); renderDevices(); renderAgents(); renderExtensions(); renderKnowledge();
    renderWorkflows(); renderUsage(); renderOrganizations(); renderObjects(); renderUpdates();
    renderSecurity(); renderModules(); renderInbox();
  }

  /* ---------- refresh ---------- */
  async function refreshAll() {
    if (state.authFailed) return;
    $("refresh-btn").classList.add("is-busy");
    await Promise.allSettled([
      load("user", loadUser), load("health", loadHealth), load("metrics", loadMetrics),
      load("context", loadContext), load("config", loadConfig), load("orchestration", loadOrchestration),
      load("security", loadSecurity), load("approvals", loadApprovals), load("generated", loadGenerated), load("runs", loadRuns), load("modules", loadModules), load("plugins", loadPlugins),
      load("mcp", loadMcp), load("usage", loadUsage), load("access", loadAccess), load("devices", loadDevices),
      load("knowledge", loadKnowledge), load("workflows", loadWorkflows),
      load("organizations", loadOrganizations), load("objects", loadObjects),
      load("releases", loadReleases), load("inbox", loadInbox),
    ]);
    state.loaded = true;
    renderAll();
    setText("last-updated", `Updated ${new Date().toLocaleTimeString([], { hour12: false })}`);
    $("refresh-btn").classList.remove("is-busy");
  }
  $("refresh-btn").addEventListener("click", refreshAll);

  /* ---------- events ---------- */
  function normPriority(p) { return String(p || "NORMAL").toUpperCase(); }
  function badge(p) {
    const pr = normPriority(p);
    const tone = { CRITICAL: "bad", HIGH: "warn", NORMAL: "info" }[pr];
    return `<span class="badge ${tone ? `badge-${tone}` : ""}">${esc(titleCase(pr.toLowerCase()))}</span>`;
  }

  function matchesFilter(e) {
    const pr = $("event-filter").value;
    if (pr !== "ALL" && normPriority(e.priority) !== pr) return false;
    const q = $("event-search").value.trim().toLowerCase();
    if (!q) return true;
    return `${e.type} ${JSON.stringify(e.data ?? {})}`.toLowerCase().includes(q);
  }

  function eventNode(e, isNew) {
    const d = document.createElement("details");
    d.className = `event${isNew ? " event-new" : ""}`;
    const json = JSON.stringify(e.data ?? {});
    d.innerHTML = `
      <summary>
        <span class="ev-time">${esc(fmtTime(e.timestamp))}</span>
        <span class="ev-type" title="${esc(e.type)}">${esc(e.type || "unknown.event")}</span>
        ${badge(e.priority)}
        <span class="ev-data">${esc(json)}</span>
      </summary>
      <pre class="code">${esc(pretty(e))}</pre>`;
    return d;
  }

  function updateEventMeta() {
    const shown = $("event-log").children.length;
    $("event-empty").hidden = shown > 0;
    $("event-empty").textContent = state.events.length ? "No events match your filter." : "No events yet. They appear here as they arrive.";
    setText("events-meta", `Showing ${shown} of ${state.events.length} events${state.paused ? " · paused" : ""}`);
  }

  function renderEventLog() {
    const log = $("event-log");
    log.replaceChildren(...state.events.filter(matchesFilter).map((e) => eventNode(e, false)));
    updateEventMeta();
  }

  function addEvent(e) {
    state.eventCount += 1;
    state.events.unshift(e);
    if (state.events.length > MAX_EVENTS) state.events.length = MAX_EVENTS;
    setText("kpi-events", String(state.eventCount));

    if (!state.paused && matchesFilter(e)) {
      const log = $("event-log");
      log.prepend(eventNode(e, true));
      while (log.children.length > MAX_EVENTS) log.removeChild(log.lastChild);
    }
    updateEventMeta();
    renderRecent();
  }

  function setStream(status) {
    state.stream = status;
    const map = { connected: ["Connected", "ok"], connecting: ["Connecting…", "neutral"], disconnected: ["Disconnected, retrying", "bad"] };
    setPill($("stream-pill"), map[status][0], map[status][1]);
    if (state.loaded) renderOverview();
  }

  function connectStream() {
    if (eventSource) eventSource.close();
    setStream("connecting");
    eventSource = new EventSource("/events/stream", { withCredentials: true });
    eventSource.onopen = () => setStream("connected");
    eventSource.onmessage = (m) => { try { addEvent(JSON.parse(m.data)); } catch (e) { /* ignore malformed packets */ } };
    eventSource.onerror = () => {
      setStream("disconnected");
      eventSource.close();
      setTimeout(connectStream, 3000);
    };
  }

  $("event-filter").addEventListener("change", renderEventLog);
  $("event-search").addEventListener("input", renderEventLog);
  $("pause-btn").addEventListener("click", () => {
    state.paused = !state.paused;
    $("pause-icon").setAttribute("href", state.paused ? "#i-play" : "#i-pause");
    setText("pause-label", state.paused ? "Resume" : "Pause");
    if (!state.paused) renderEventLog(); else updateEventMeta();
  });
  $("clear-btn").addEventListener("click", () => {
    state.events = [];
    renderEventLog(); renderRecent();
  });

  /* ---------- forms ---------- */
  $("publish-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const out = $("publish-result");
    let data;
    try { data = JSON.parse($("event-data").value.trim()); }
    catch { setResult(out, "Event data must be valid JSON.", true); return; }

    try {
      const r = await fetchJson("/events/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: $("event-type").value.trim(), data, source: "webui", priority: "NORMAL" }),
      });
      if (r.ok) {
        setResult(out, `Published. Delivered to ${r.data?.subscribers ?? "n/a"} subscriber(s).`);
      } else {
        const detail = typeof r.data === "object" ? r.data?.detail : "";
        setResult(out, `Publish failed (${r.status})${detail ? `: ${detail}` : ""}`, true);
      }
    } catch (err) { setResult(out, `Publish error: ${err.message}`, true); }
  });

  $("load-module-btn").addEventListener("click", async () => {
    const input = $("module-path"), out = $("module-action-result");
    const path = input.value.trim();
    if (!path) { setResult(out, "Enter a module path first.", true); return; }
    setResult(out, "Loading module…");
    try {
      const r = await fetchJson("/modules/load", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_path: path }),
      });
      if (r.ok) {
        setResult(out, `Loaded ${path}`);
        input.value = "";
        await loadModules(); renderModules(); renderOverview();
      } else {
        const detail = typeof r.data === "object" ? r.data?.detail : "";
        setResult(out, `Failed to load module (${r.status})${detail ? `: ${detail}` : ""}`, true);
      }
    } catch (err) { setResult(out, `Error: ${err.message}`, true); }
  });

  $("api-test-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const method = $("api-method").value.toUpperCase();
    const endpoint = $("api-endpoint").value.trim();
    const bodyRaw = $("api-body").value.trim();
    const meta = $("api-response-meta"), box = $("api-response");

    let body;
    if (method !== "GET" && bodyRaw) {
      try { body = JSON.parse(bodyRaw); }
      catch { setResult(meta, "Body must be valid JSON.", true); return; }
    }
    setResult(meta, "Sending…");
    box.textContent = "Loading…";
    try {
      const options = { method };
      if (body !== undefined) { options.headers = { "Content-Type": "application/json" }; options.body = JSON.stringify(body); }
      const res = await fetchWithAuth(endpoint, options);
      if (!res) return;
      const isJson = (res.headers.get("content-type") || "").includes("application/json");
      const payload = isJson ? await res.json() : await res.text();
      box.textContent = typeof payload === "string" ? payload : pretty(redact(payload));
      setResult(meta, `${res.status} ${res.ok ? "OK" : "Error"}`, !res.ok);
    } catch (err) {
      box.textContent = `Request failed: ${err.message}`;
      setResult(meta, "Request failed.", true);
    }
  });

  $("config-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const out = $("config-result");
    let config;
    try { config = JSON.parse($("config-editor").value); }
    catch { setResult(out, "Configuration must be valid JSON.", true); return; }
    setResult(out, "Saving and reloading runtime…");
    try {
      const r = await fetchJson("/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      if (!r.ok) {
        const detail = typeof r.data === "object" ? r.data?.detail : "";
        setResult(out, `Reload failed (${r.status})${detail ? `: ${detail}` : ""}`, true);
        return;
      }
      $("config-editor").value = pretty(r.data.config);
      setResult(out, "Configuration saved and runtime reloaded.");
      await refreshAll();
    } catch (err) { setResult(out, `Reload error: ${err.message}`, true); }
  });

  document.querySelectorAll("button.chip[data-endpoint]").forEach((c) => c.addEventListener("click", () => {
    $("api-endpoint").value = c.dataset.endpoint || "/health";
    $("api-method").value = c.dataset.method || "GET";
    if ($("api-method").value === "GET") $("api-body").value = "";
  }));

  /* ---------- P4 actions ---------- */
  async function refreshAfter(action, loaders = []) {
    await Promise.allSettled(loaders.map((fn) => load(fn.name || "refresh", fn)));
    renderAll();
  }

  $("workflow-refresh").addEventListener("click", async () => {
    await loadWorkflows();
    renderWorkflows();
  });

  $("plugin-discover").addEventListener("click", async () => {
    const r = await fetchJson("/api/v1/plugins/discover", { method: "POST" });
    if (!r.ok) { window.alert("Could not rescan plugins."); return; }
    await loadPlugins(); renderExtensions();
  });

  $("quota-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("quota-result");
    const scope = $("quota-scope").value;
    const subject = $("quota-subject").value.trim() || "*";
    const tokens = $("quota-tokens").value;
    setResult(out, "Saving quota…");
    try {
      const r = await fetchJson("/api/v1/admin/quotas", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope, subject_id: subject, period: $("quota-period").value,
          token_limit: tokens ? Number(tokens) : null,
        }),
      });
      if (!r.ok) throw new Error(r.data?.detail || "Could not save quota");
      setResult(out, "Quota saved.");
      await loadUsage(); renderUsage();
    } catch (err) { setResult(out, err.message, true); }
  });

  $("schedule-cancel").addEventListener("click", resetScheduleForm);
  $("schedule-agent").addEventListener("change", () => {
    updateScheduleModes();
    if (!state.editingScheduleId) fillScheduleForm($("schedule-agent").value);
  });

  $("schedule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("schedule-result");
    const payload = schedulePayload();
    if (!payload.agent_id || !payload.name || !payload.message) {
      setResult(out, "Agent, name and instruction are required.", true);
      return;
    }
    setResult(out, "Saving schedule…");
    try {
      const editing = state.editingScheduleId;
      const r = await fetchJson(
        editing ? `/api/v1/agent-schedules/${encodeURIComponent(editing)}` : "/api/v1/agent-schedules",
        {
          method: editing ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!r.ok) throw new Error(r.data?.detail || "Could not save the schedule");
      setResult(out, editing ? "Schedule updated." : "Schedule created.");
      await loadInbox();
      renderInbox();
      resetScheduleForm();
      setResult(out, editing ? "Schedule updated." : "Schedule created.");
    } catch (err) {
      setResult(out, err.message, true);
    }
  });


  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-tailscale-open],[data-tailscale-connect],[data-tailscale-refresh],[data-tailscale-close],[data-tailscale-copy-install],[data-tailscale-copy-address],[data-tailscale-authkey],[data-pair-device],[data-copy-pairing],[data-device-select],[data-delete-doc],[data-resume-workflow],[data-cancel-workflow],[data-delete-object],[data-plugin-action],[data-mcp-action],[data-install-mcp],[data-approval-id],[data-generated-id],[data-run-resume],[data-run-timeline],[data-notification-read],[data-schedule-run],[data-schedule-runs],[data-schedule-edit],[data-schedule-toggle],[data-schedule-delete],[data-recipe]");
    if (!target) return;

    try {
      if (target.dataset.tailscaleOpen !== undefined) {
        await openTailscalePanel();
      } else if (target.dataset.tailscaleConnect !== undefined) {
        target.disabled = true;
        try {
          await startTailscaleConnection();
        } finally {
          target.disabled = false;
        }
      } else if (target.dataset.tailscaleAuthkey !== undefined) {
        const input = $("tailscale-auth-key");
        const key = input?.value?.trim() || "";
        if (!key) return;
        target.disabled = true;
        try {
          const r = await fetchJson("/api/v1/access/tailscale/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ auth_key: key }),
          });
          if (input) input.value = "";
          state.tailscale = r.ok ? r.data : { state: "error", reason: r.data?.detail || "Could not use the auth key." };
          renderTailscalePanel();
          if (state.tailscale.state === "running") await onTailscaleConnected();
          else if (state.tailscale.login_in_progress || state.tailscale.state === "needs_login") startTailscalePoll();
        } finally {
          target.disabled = false;
        }
      } else if (target.dataset.tailscaleRefresh !== undefined) {
        await loadTailscaleStatus(true);
      } else if (target.dataset.tailscaleClose !== undefined) {
        stopTailscalePoll();
        state.tailscaleOpen = false;
        renderTailscalePanel();
      } else if (target.dataset.tailscaleCopyInstall !== undefined) {
        await navigator.clipboard.writeText(target.dataset.tailscaleCopyInstall);
        target.textContent = "Copied";
        setTimeout(() => { target.textContent = "Copy command"; }, 1600);
      } else if (target.dataset.tailscaleCopyAddress !== undefined) {
        await navigator.clipboard.writeText(target.dataset.tailscaleCopyAddress);
        target.textContent = "Copied";
        setTimeout(() => { target.textContent = "Copy address"; }, 1600);
      } else if (target.dataset.pairDevice !== undefined) {
        target.disabled = true;
        try {
          const r = await fetchJson("/api/v1/devices/pairing-code", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ttl_minutes: 10 }),
          });
          if (!r.ok) throw new Error(r.data?.detail || "Could not create a pairing code");
          renderPairingCode(r.data);
        } finally {
          target.disabled = false;
        }
      } else if (target.dataset.copyPairing) {
        await navigator.clipboard.writeText(target.dataset.copyPairing);
        target.textContent = "Copied";
        setTimeout(() => { target.textContent = "Copy pairing link"; }, 1800);
      } else if (target.dataset.notificationRead) {
        const r = await fetchJson(`/api/v1/notifications/${encodeURIComponent(target.dataset.notificationRead)}/read`, { method: "POST" });
        if (!r.ok) throw new Error("Could not mark the notification as read");
        await loadInbox(); renderInbox();
      } else if (target.dataset.scheduleRun) {
        const r = await fetchJson(`/api/v1/agent-schedules/${encodeURIComponent(target.dataset.scheduleRun)}/run`, { method: "POST" });
        if (!r.ok) throw new Error(r.data?.detail || "Could not run the schedule");
        setResult($("schedule-result"), "Schedule queued. It will run on the next scheduler tick.");
      } else if (target.dataset.scheduleRuns) {
        await loadScheduleRuns(target.dataset.scheduleRuns);
        renderScheduleRuns();
        $("schedule-runs")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } else if (target.dataset.scheduleEdit) {
        const schedule = (state.schedules || []).find((s) => s.id === target.dataset.scheduleEdit);
        if (schedule) {
          fillScheduleEditor(schedule);
          $("schedule-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      } else if (target.dataset.scheduleToggle) {
        const schedule = (state.schedules || []).find((s) => s.id === target.dataset.scheduleToggle);
        if (!schedule) return;
        const r = await fetchJson(`/api/v1/agent-schedules/${encodeURIComponent(schedule.id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: !schedule.enabled }),
        });
        if (!r.ok) throw new Error(r.data?.detail || "Could not update the schedule");
        await loadInbox(); renderInbox();
      } else if (target.dataset.scheduleDelete) {
        if (!window.confirm("Delete this schedule and its run history?")) return;
        const r = await fetchJson(`/api/v1/agent-schedules/${encodeURIComponent(target.dataset.scheduleDelete)}`, { method: "DELETE" });
        if (!r.ok) throw new Error(r.data?.detail || "Could not delete the schedule");
        await loadInbox(); renderInbox();
      } else if (target.dataset.recipe) {
        fillScheduleForm(target.dataset.recipe);
        $("schedule-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (target.dataset.runResume) {

        const r = await fetchJson(`/api/v1/runs/${encodeURIComponent(target.dataset.runResume)}/resume`, { method: "POST" });
        if (!r.ok) throw new Error(r.data?.detail || "Could not resume the run");
        await loadRuns(); renderAgents();
      } else if (target.dataset.runTimeline) {
        const id = target.dataset.runTimeline;
        const box = document.getElementById(`run-timeline-${id}`);
        if (box) {
          box.hidden = false;
          const r = await fetchJson(`/api/v1/runs/${encodeURIComponent(id)}/timeline`);
          if (!r.ok) throw new Error("Could not load the timeline");
          const timeline = r.data?.timeline || [];
          box.innerHTML = timeline.length
            ? `<pre>${esc(timeline.map((e) => `${e.type}: ${JSON.stringify(e.data)}`).join("\n"))}</pre>`
            : '<span class="card-note">No trace events.</span>';
        }
      } else if (target.dataset.generatedId) {
        const action = target.dataset.generatedAction;
        const r = await fetchJson(`/api/v1/generated/${encodeURIComponent(target.dataset.generatedId)}/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: action === "reject" ? JSON.stringify({ reason: "Rejected in dashboard" }) : undefined,
        });
        if (!r.ok) throw new Error(r.data?.detail || `Could not ${action} artifact`);
        await loadGenerated(); renderAgents();
      } else if (target.dataset.approvalId) {
        const r = await fetchJson(`/api/v1/approvals/${encodeURIComponent(target.dataset.approvalId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: target.dataset.approvalDecision === "approve" }),
        });
        if (!r.ok) throw new Error("Approval decision failed");
        await loadApprovals(); renderSecurity();
      } else if (target.dataset.deviceSelect) {
        state.selectedDevice = target.dataset.deviceSelect;
        await loadDevices();
        renderDevices();
      } else if (target.dataset.deleteDoc) {
        const r = await fetchJson(`/api/v1/rag/documents/${encodeURIComponent(target.dataset.deleteDoc)}`, { method: "DELETE" });
        if (!r.ok) throw new Error("Delete failed");
        await loadKnowledge(); renderKnowledge();
      } else if (target.dataset.resumeWorkflow) {
        const r = await fetchJson(`/api/v1/workflows/${encodeURIComponent(target.dataset.resumeWorkflow)}/resume?retry_failed=true`, { method: "POST" });
        if (!r.ok) throw new Error("Resume failed");
        await loadWorkflows(); renderWorkflows();
      } else if (target.dataset.cancelWorkflow) {
        const r = await fetchJson(`/api/v1/workflows/${encodeURIComponent(target.dataset.cancelWorkflow)}/cancel`, { method: "POST" });
        if (!r.ok) throw new Error("Cancel failed");
        await loadWorkflows(); renderWorkflows();
      } else if (target.dataset.deleteObject) {
        const r = await fetchJson(`/api/v1/objects/${encodeURIComponent(target.dataset.deleteObject)}`, { method: "DELETE" });
        if (!r.ok) throw new Error("Delete failed");
        await loadObjects(); renderObjects();
      } else if (target.dataset.pluginId) {
        const id = encodeURIComponent(target.dataset.pluginId);
        const action = target.dataset.pluginAction;
        const r = await fetchJson(`/api/v1/plugins/${id}/${action}`, { method: "POST" });
        if (!r.ok) throw new Error(`Plugin ${action} failed`);
        await loadPlugins(); renderExtensions();
      } else if (target.dataset.mcpId) {
        const id = encodeURIComponent(target.dataset.mcpId);
        const action = target.dataset.mcpAction;
        const options = { method: action === "delete" ? "DELETE" : "POST" };
        const url = action === "delete" ? `/api/v1/mcp/servers/${id}` : `/api/v1/mcp/servers/${id}/${action}`;
        const r = await fetchJson(url, options);
        if (!r.ok) throw new Error(`MCP ${action} failed`);
        await loadMcp(); renderExtensions();
      } else if (target.dataset.installMcp) {
        const r = await fetchJson("/api/v1/mcp/servers", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ marketplace_id: target.dataset.installMcp }),
        });
        if (!r.ok) throw new Error("Install failed");
        await loadMcp(); renderExtensions();
      }
    } catch (err) {
      window.alert(err.message || "Action failed");
    }
  });

  $("rag-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("rag-result");
    setResult(out, "Indexing…");
    try {
      const r = await fetchJson("/api/v1/rag/documents", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: $("rag-title").value.trim(),
          source: $("rag-source").value.trim() || "manual",
          content: $("rag-content").value,
        }),
      });
      if (!r.ok) throw new Error(r.data?.detail || "Indexing failed");
      setResult(out, `Indexed ${r.data.chunks} chunk(s).`);
      $("rag-form").reset();
      $("rag-source").value = "manual";
      await loadKnowledge(); renderKnowledge();
    } catch (err) { setResult(out, err.message, true); }
  });

  $("rag-search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = $("rag-query").value.trim();
    if (!query) return;
    setHtml("rag-search-results", '<p class="empty">Searching…</p>');
    const r = await fetchJson(`/api/v1/rag/search?q=${encodeURIComponent(query)}&limit=8`);
    if (!r.ok) {
      setHtml("rag-search-results", '<p class="empty">Search failed.</p>');
      return;
    }
    const results = r.data?.results || [];
    setText("kpi-rag-search", String(results.length));
    setText("kpi-rag-search-sub", `For “${query}”`);
    setText("rag-search-meta", `${results.length} result(s)`);
    setHtml("rag-search-results", results.length ? results.map((item) => `
      <article class="search-result">
        <div class="row-main"><strong>${esc(item.title)}</strong><span>${esc(item.source)} · score ${Number(item.score || 0).toFixed(3)}</span></div>
        <p>${esc(item.content)}</p>
      </article>`).join("") : '<p class="empty">No matching chunks.</p>');
  });

  $("org-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("org-result");
    setResult(out, "Creating…");
    try {
      const r = await fetchJson("/api/v1/organizations", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: $("org-name").value.trim() }),
      });
      if (!r.ok) throw new Error(r.data?.detail || "Could not create organization");
      setResult(out, "Organization created.");
      $("org-form").reset();
      await loadOrganizations(); renderOrganizations();
    } catch (err) { setResult(out, err.message, true); }
  });

  $("object-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("object-result");
    const file = $("object-file").files[0];
    if (!file) return;
    setResult(out, "Uploading…");
    const form = new FormData();
    form.append("file", file);
    if ($("object-key").value.trim()) form.append("key", $("object-key").value.trim());
    try {
      const res = await fetchWithAuth("/api/v1/objects", { method: "POST", body: form });
      if (!res) return;
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setResult(out, `Uploaded ${file.name}.`);
      $("object-form").reset();
      await loadObjects(); renderObjects();
    } catch (err) { setResult(out, err.message, true); }
  });

  $("release-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("release-result");
    setResult(out, "Publishing…");
    try {
      const r = await fetchJson("/api/v1/updates/releases", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: $("release-product").value,
          channel: $("release-channel").value,
          version: $("release-version").value.trim(),
          notes: $("release-notes").value.trim(),
          url: $("release-url").value.trim(),
        }),
      });
      if (!r.ok) throw new Error(r.data?.detail || "Publish failed");
      setResult(out, "Release published.");
      $("release-form").reset();
      await loadReleases(); renderUpdates();
    } catch (err) { setResult(out, err.message, true); }
  });

  /* ---------- start ---------- */
  showView();
  updateEventMeta();
  refreshAll();
  connectStream();
  refreshTimer = setInterval(() => { if (!document.hidden && !state.authFailed) refreshAll(); }, REFRESH_MS);
})();
