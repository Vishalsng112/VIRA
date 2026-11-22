# Changelog

All notable changes to VIRA are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- No unreleased changes yet.

## [0.6.1] - 2026-11-22

### Fixed

- The chat composer and send button now align with the message column when the
  context rail is expanded, instead of centering across the rail.
- Added symmetric scrollbar gutters so the message list and composer stay
  aligned on wide screens.

## [0.6.0] - 2026-11-22

### Added

- Security hardening for public deployments: persistent generated session secret,
  Secure cookies behind HTTPS, CSRF origin checks, CSP/HSTS/security headers,
  Cloudflare-aware rate-limit identities and disabled interactive API docs.
- One-tap QR/code pairing between the server dashboard and VIRA Link. The
  dashboard issues a single-use code with an inline QR and copyable
  `vira://pair` link; Android scans it and Linux pastes it. Redeeming the code
  enrolls the device and issues the user session in one step.
- Pluggable remote-access providers, with automatic **Tailscale private**
  discovery. Pairing codes and QR links use the tailnet MagicDNS address when
  available, with an explicit fallback warning instead of a localhost QR.
- Guided Tailscale setup in the dashboard: install/daemon diagnostics, browser
  login URL with QR, automatic polling, and an auth-key fallback for headless
  or Docker deployments.
- **Cloudflare named tunnel is now the default remote-access provider**, requiring
  no extra app on the phone. Pairing links include a detected LAN fallback, and
  VIRA Link now fails over between endpoints automatically.
- Guided Cloudflare setup: existing-service hostname verification, browser/QR
  login, tunnel creation, DNS routing, managed tunnel start and automatic config
  save from the dashboard.

### Fixed

- VIRA Link chat requests now send the enrolled `device_id`, so agent answers
  use the phone/desktop telemetry instead of the server-local device.
- Scheduled agents now default to the user's most recently active client device
  when no device is specified.
- The web chat agent picker only lists agents that subscribe to `user.message`;
  task-only agents remain available through schedules.
- Platform-specific collectors now default to off when unavailable: Android
  active-window/hardware and Linux active-window/battery. Linux Wayland
  active-window limitations are documented.
- Android now has a **Focus & idle** collector backed by UsageStats screen and
  interaction events. The Overview dashboard now includes toggles for agent
  notifications and crash diagnostics alongside every available device signal.

## [1.2.1] - 2026-11-22

### Fixed

- Linux desktop builds now use Flutter 3.47.9, avoiding the Flutter 3.50
  Wayland subsurface bug that rendered the UI at the wrong size or in a corner.
- The Linux Clang 22 warning workaround is applied only when the compiler
  supports the flag, so older CI toolchains build cleanly.

### Changed

- VIRA Link release builds are pinned to Flutter 3.47.9 with Dart 3.13.7.

## [0.5.0] - 2026-11-22

### Added

- Workspace-centric sandbox model: user-visible project directories under
  `workspace.root`, one shared default workspace per user, multiple agents
  attaching to the same workspace, per-request `workspace` selection injected
  into tool calls, `workspace.allow_user_paths`, and `/api/v1/workspaces` CRUD.
  Adds host execution mode (`execution_mode: host`) so agents use host-installed
  toolchains, plus `sandbox.extra_path` and read-only SDK mounts. Deleting one
  sandbox no longer deletes a shared workspace. See
  `docs/dev/designs/workspaces.md`.
- Reworked agent framework: one canonical `BaseAgent` with typed
  `TaskRequest`/`TaskResult`, lifecycle hooks, per-task identity, tool policy
  and helpers for LLM/tool/memory/knowledge/progress/response, plus a reusable
  `LLMAgent` layer for prompt + multi-step tool loops and delegation.
  `ChatAgent` is now a thin subclass connected to every registered local and MCP
  tool; qualified MCP tools can be called even when not preselected. Read-only
  tools now execute with their declared permission action instead of being
  rejected as `execute`. See `docs/dev/architecture/agent-design.md`.
- Paper-aligned agent architectures: `SingleAgent`,
  `IndependentAgentSystem`, `CentralizedAgentSystem`,
  `DecentralizedAgentSystem`, `HybridAgentSystem` and `AdaptiveAgentSystem`,
  with a conservative `recommend_architecture()` selector, measured
  coordination profiles, bounded workers/rounds and per-run coordination data.
  See `docs/dev/architecture/agent-architectures.md`.
- Proactive agent schedules: durable per-user daily/weekly/interval schedules,
  IANA timezones, quiet hours, atomic claiming and crash-safe locks, executed
  through the existing orchestrator and `RuntimeScheduler.run_task()`.
  APIs at `/api/v1/agent-schedules`; roadmap at `docs/dev/roadmap/agents.md`.
- Notification delivery: in-app notifications are delivered immediately and a
  webhook provider handles external delivery with retries, dedupe keys and
  worker-based delivery.
- Agent recipe catalog at `/api/v1/agent-recipes` for the five daily-use agents.
- Morning Brief agent (`morning-brief`): grounds each brief in configured tools,
  labels missing sources as unavailable, records source provenance, falls back
  deterministically when the model is down, and delivers through the proactive
  schedule/notification pipeline.
- Focus & Wellbeing Coach (`focus-coach`): morning/checkin/evening/weekly modes,
  measured insights and goals, privacy-safe weekly reports and deterministic
  fallback.
- Second Brain (`second-brain`): chat and scheduled capture, cited recall,
  non-destructive weekly consolidation and superseding corrections over
  personal knowledge. Adds `PATCH /api/v1/knowledge/items/{item_id}`.
- Structured schedule `input` payloads (migration 18) for agent modes.
- Knowledge corrections via `PATCH /api/v1/knowledge/items/{item_id}` and the
  `second-brain` `correct` mode; superseded revisions are retained.
- Chief of Staff agent (`chief-of-staff`): parallel email/calendar/task
  extraction, source-linked action items, approval-safe drafts (`sent=0`),
  preference memory and graceful connector failures.
- Household & Life Admin agent (`household`): membership-checked household
  snapshots, morning/evening plans, and a weekly meals/budget/chores fan-out.
- Read-only local office MCP connector (`examples/mcp/office_server.py`) for
  demonstrating the Chief of Staff without external credentials.
- VIRA Link **Agent Inbox**: unread notifications, full result text, schedule
  list with next run, run-now, run history and scheduled-run timeline.
- VIRA Link **schedule management**: agent recipe cards, create/edit, pause/
  resume, delete, timezone, quiet hours, mode selection and webhook channel.
- VIRA Link **native agent notifications**: live NDJSON notification stream,
  local OS notifications, Settings permission flow and tap-to-open Agent Inbox.
- VIRA Link **remote push**: optional Firebase Messaging token registration from
  dart-defines, with Android delivery while the app is closed.
- Server **push delivery channel**: device tokens sent via a configurable relay
  or directly through FCM HTTP v1 with a service account.
- Android build configuration for notifications (compileSdk 37, desugaring,
  POST_NOTIFICATIONS).
- FCM sender tests with JWT exchange and message payload validation.
- Web dashboard **Inbox** view: agent notifications, recipe shortcuts, schedule
  create/edit/pause/delete, run-now and recent run history.
- Backend recipe metadata (`schedule_modes`, `default_mode`) for client forms.
- Backend support for the client: unread notification count and
  `GET /api/v1/agent-schedules/{id}/runs/{run_id}` with a redacted timeline.
- Authorized `knowledge_list` service/runtime helper for scoped knowledge review.
- Scoped knowledge base for agents: a single `knowledge_items` store with
  `conversation`/`personal`/`agent`/`org`/`global` scopes, append-only revisions,
  deduplication, promotion policy and a `knowledge.*` event trail. Adds
  `knowledge_search`/`knowledge_write` agent tools, a `/api/v1/knowledge` API,
  merged retrieval over knowledge/documents/memories, and a
  `knowledge.consolidate` worker job stub that the future AGI consolidation
  algorithm can replace. See `docs/dev/designs/knowledge-base.md`.
- Pluggable knowledge storage: `KnowledgeStore`/`KnowledgeRepository`/
  `VectorIndex`/`KnowledgeCache` ports, a config-selected factory, an in-memory
  backend, capability flags, a TTL cache with generation-based invalidation and
  a conformance suite that runs the same contract against every backend.
- Mature sandbox execution environments: persistent per-agent/per-user
  workspaces, shell and argv execution, multi-file project creation, background
  jobs with logs/kill, pip/npm dependency installs, archives with safe restore,
  policy updates, usage/quota reporting and disk-backed recovery after restart.
- ChatAgent per-agent tool permissions (`allow`/`deny`/`pinned`) and per-tool
  timeouts; the shipped Chatbot pins the `sandbox` tool for code/build work.
- Plugin examples and MCP server examples with end-to-end tests.
- Contributor guide, decision log, release cadence and issue templates.
- Showcase page for deployment patterns and community demos.
- VIRA Link first-run permission setup: notifications use Android's in-app
  runtime prompt, activity insights are opt-in and off by default, and Android
  Usage Access guidance adapts to sideloaded installs. Developers can run
  `client/tool/grant_android_permissions.sh` after installing a debug APK.

### Removed

- Legacy agent implementations and their examples: `AutonomousAgent`,
  `LoadMonitorAgent`, `SimpleAgent`, the duplicate
  `vira/agent_orchestration/base.py`, the unused `vira/agent/messaging.py`, the
  `think/plan/act/reflect` execution pipeline and their tests. `BaseAgent` now
  requires `execute`; `ChatAgent` is the only shipped agent.
- Unused scaffolding that had no callers and (in several cases) crashed on
  import: `vira/actions`, `vira/cognition`, `vira/content`, `vira/artifacts`,
  `vira/memory/schemas.py`, `vira/agent_runtime/context.py`, and the dead
  `AgentManager`/`Planner` pair.

### Fixed

- `/health` now returns a public minimal status without a session, so stale or
  unauthenticated dashboard tabs cannot spam 401s. Administrators still receive
  the detailed payload.
- The dashboard script is cache-busted so the updated 401 handling is loaded.
- Stale dashboard sessions no longer poll protected endpoints forever: the
  dashboard stops its refresh timer and redirects to login on the first 401.
- A revoked or expired device credential now stops the command poller and sync
  loop, clears the stale device credential and returns to sign-in with an
  actionable message instead of repeating 401s every 30 seconds.
- Cancelling services now also cancels the device command timer.
- The docs build now works on Python 3.12 by installing `setuptools` for
  `distutils`, and the agent roadmap no longer links outside the docs tree.
- Updated `mcp` to 1.30.0, `aiohttp` to 3.14.4 and `python-multipart` to
  0.0.31 to clear the `pip-audit` findings.
- `AgentMessageBus.unsubscribe()` now removes the registered callback instead of
  silently keeping the wrapper; bound methods can be unsubscribed too.
- OpenAI and Anthropic `generate_structured()` now return a parsed `dict` (and
  OpenAI `tool_call()` returns a plain `{"name", "arguments"}` dict) instead of
  raw strings or provider objects.

### Changed

- Reorganized `config.yaml` into documented sections covering every supported
  key, including sensors, plugins, security, sandbox, workspaces, knowledge,
  MCP, LLM, agents, scheduling, notifications and worker jobs.
- Server-local hardware, process, network, filesystem, idle and user-activity
  sensors are explicitly disabled. The server heartbeat remains active.
- Release tooling now uses standard product tags (`vX.Y.Z` for the server,
  `vira-link-vX.Y.Z` for VIRA Link), versioned asset names, generated release
  notes, verified checksums and a release manifest. Build numbers are no longer
  part of public tags or titles.
- Release workflows are linted with actionlint and yamllint.
- Default local model is now `qwen3.5:9b`, with better tool-protocol support
  than the previous default. Installers, Compose defaults, the doctor and the
  model guidance all use the same value.
- Documentation navigation now includes the platform matrix, evaluations,
  agent platform, release process and showcase.
- The shipped configuration auto-approves the isolated `sandbox` tool via
  `security.approvals.safe_tools`, so the ChatAgent can write and execute code
  without a per-call approval. Shell and host-filesystem writes remain gated.
- VIRA Link now uses a shared responsive layout system: phone-width typography,
  padding, controls and cards are tighter; stat cards use two columns on
  phones; the navigation rail starts at tablet width instead of leaving web and
  tablet layouts in a stretched phone shell; and desktop content is capped at a
  readable width.
- Page headers no longer duplicate the mobile app-bar title, and the Insights
  focus card lays out its session total and action buttons cleanly on phones.
- The server dashboard, sign-in and chat pages now share VIRA Link's
  indigo→violet→pink palette, aurora background and glass surfaces. The server
  dashboard keeps two KPI columns on phones, and the chat composer/sidebar were
  tightened for small screens.
- The chat workspace now lists the real registered agents with `ChatAgent`
  selected by default, adds a one-click **Clear all** action backed by
  `DELETE /conversations`, uses concrete starter prompts, replaces the footer
  links with compact Dashboard/Sign out actions, and renders the send/stop
  controls as proper SVG icons.
- Added a reusable VIRA logo set (SVG plus 32/64/128/192/512px PNGs, favicon,
  Android launcher icons and Flutter assets) and applied it across the server
  and VIRA Link.

## [0.4.0] - 2026-11-21

### Added

- **Phase 1 positioning and proof:** README rewrite, five-minute demo, demo
  recording, security overview and reproducible demo guide.
- **Phase 2 first-run reliability:** `vira doctor`, model tier guidance, a
  tool-use benchmark, chat recovery UI (retry, switch model, trace), Stop/cancel
  support and model discovery/switching APIs.
- **Phase 3 trust evidence:** threat model, approval gates for destructive tools,
  cross-user isolation tests, CI secret/dependency scanning, backup/restore drill
  with RPO/RTO, hardened Compose services, redacted audit export and client
  diagnostics.
- **Phase 4 cross-platform client:** native macOS Apple Silicon target, macOS
  CI artifact, platform capability matrix, release checksums/notes and uninstall
  paths, opt-in diagnostics and first-run permissions UX.
- **Phase 5 agent platform:** deterministic evaluation harness with recorded
  results, approval-gated generated tools/agents, run budgets, run resume,
  redacted run timelines, memory ranking/feedback, agent quotas, new specialist
  templates and dashboard observability.
- **Phase 6 community:** three complete plugin/MCP examples with tests, release
  cadence and changelog, decision log, contributor guide, curated good-first
  issues, issue templates and a showcase page.

### Changed

- Default local model is `nemotron-3.5-bolt:e4b`; model selection is persisted and
  can be changed without restarting.
- Docker images run with all capabilities dropped, a read-only root filesystem,
  `no-new-privileges`, process limits and a small `noexec` `/tmp`.

### Security

- Approval gates for destructive shell, filesystem and sandbox calls.
- Generated artifacts require administrator approval and remain re-checked at
  execution time.
- Redacted audit export and client diagnostic uploads.
- Gitleaks and pip-audit run in CI.

## [0.3.0] and earlier

Earlier history is available in the git log and release tags.
