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
    agents:    { title: "Agents",          sub: "Registered agents, scheduling and the tools they can use." },
    security:  { title: "Security",        sub: "Read-only view of how VIRA authenticates, authorizes and handles events." },
    events:    { title: "Events",          sub: "Live stream from the event bus." },
    modules:   { title: "Modules",         sub: "Kernel modules that are currently loaded." },
    developer: { title: "Developer tools", sub: "Test endpoints and inspect raw runtime data." },
  };

  const $ = (id) => document.getElementById(id);

  const state = {
    health: null, metrics: null, orchestration: null, security: null, modules: null,
    events: [], eventCount: 0, paused: false,
    stream: "connecting", // connecting | connected | disconnected
    loaded: false,
  };
  let eventSource = null;

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
    const res = await fetch(url, { credentials: "include", ...options });
    if (res.status === 401) { window.location.href = "/login"; return null; }
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
  }

  async function loadOrchestration() {
    const r = await fetchJson("/orchestration");
    state.orchestration = r.ok ? r.data : null;
  }

  async function loadSecurity() {
    const r = await fetchJson("/security");
    state.security = r.ok ? r.data : null;
  }

  async function loadModules() {
    const r = await fetchJson("/modules");
    state.modules = r.ok && Array.isArray(r.data) ? r.data : null;
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

    const names = Array.isArray(tools.names) ? tools.names : [];
    setText("tools-count", `${names.length} total`);
    setHtml("tool-list", chips(names, "No tools are registered."));
    setHtml("runtime-facts", kv({
      router_running: (o.router || {}).running,
      router_subscribed: (o.router || {}).subscribed,
      max_concurrent_tasks: sched.max_concurrent,
      pending_tasks: sched.pending_tasks,
      memory_manager: (o.runtime || {}).memory_manager,
      llm_manager: (o.runtime || {}).llm_manager,
      mcp_connections: tools.mcp_connections,
    }, { router_running: "Router running", router_subscribed: "Router subscribed", mcp_connections: "MCP connections", llm_manager: "LLM manager" }));
  }

  /* ---------- render: security ---------- */
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

  function renderAll() {
    renderOverview(); renderAgents(); renderSecurity(); renderModules();
  }

  /* ---------- refresh ---------- */
  async function refreshAll() {
    $("refresh-btn").classList.add("is-busy");
    await Promise.allSettled([
      load("user", loadUser), load("health", loadHealth), load("metrics", loadMetrics),
      load("context", loadContext), load("config", loadConfig), load("orchestration", loadOrchestration),
      load("security", loadSecurity), load("modules", loadModules),
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

  document.querySelectorAll("button.chip[data-endpoint]").forEach((c) => c.addEventListener("click", () => {
    $("api-endpoint").value = c.dataset.endpoint || "/health";
    $("api-method").value = c.dataset.method || "GET";
    if ($("api-method").value === "GET") $("api-body").value = "";
  }));

  /* ---------- start ---------- */
  showView();
  updateEventMeta();
  refreshAll();
  connectStream();
  setInterval(refreshAll, REFRESH_MS);
})();
