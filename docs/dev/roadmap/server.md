# VIRA Server Roadmap

Status: design + implementation plan for the server side of VIRA.

The client is now a mature collector and the server accepts device events,
aggregates insights and exposes an admin control panel. The next work is to turn
the server from a strong single-process local runtime into a durable, secure and
agent-ready platform.

---

## 1. Current server baseline

Already implemented:

- Kernel with event bus, dispatcher, scheduler, state manager, metrics, security
- FastAPI API, authenticated dashboard/chat, sessions, users and roles
- Multi-device platform: enrollment, credentials, heartbeat, event ingestion,
  idempotency, rate limits, fleet inventory and audit
- Device event storage with policy classes, retention and outbox
- ChatAgent tool loop, agents, registry, router, scheduler, lessons and sub-agents
- Local/MCP tools with permissions and audit
- Memory store, conversations, runs and incognito conversations
- Device insight aggregation API and ChatAgent `insights` tool
- Admin APIs for users, devices, audit, health, agents, tools and metrics
- SQLite persistence with versioned migrations

The main gaps are durability, scale, consent enforcement, background work,
agent quality, and operational hardening.

---

## 2. Guiding principles

1. **Server is the policy authority.** Clients propose / capture; the server
   enforces consent, access, retention and purpose.
2. **Event-first.** Facts are immutable events; derived views are rebuildable.
3. **Durable by default.** Acknowledged work survives process restart.
4. **Least privilege.** Users, devices, agents, tools and admin actions each have
   explicit scopes.
5. **Observable.** Every important action has a metric, log and audit trail.
6. **Local-first compatible.** Postgres/Redis are optional production upgrades,
   not a requirement for a single-machine install.
7. **Agent safety.** Agents get bounded tools, budgets, approvals and audit.

---

## 3. Priority roadmap

### P0 — Production foundation (must do first)

- [x] **PostgreSQL adapter** with schema (`vira/db/postgres_schema.sql`) and query
  translation while keeping SQLite for local installs. Live PostgreSQL validation
  remains a deployment check.
- [x] **Separate worker process** for retention, rollups, backups and cleanup
  (`python -m vira.worker`). Outbox publication stays in the API process until an
  external broker is added.
- [x] **Durable database-backed job queue** with retries, dead-letter, dedupe and
  periodic jobs. External Redis/Celery can replace it later.
- [~] **Schema migration runner** now covers jobs, rollups and the existing
  versioned tables; legacy baseline DDL still lives in `init_db`.
- [x] **Secrets management**: never store provider keys in plain config; support
  env/file/OS keyring and redaction in every API response.
- [x] **Encryption at rest** for device credentials, provider keys, tokens and
  sensitive payloads; key rotation plan.
- [x] **Rate limiting** for login, chat, admin, tools and insights, not only
  device ingestion/heartbeat.
- [x] **Structured logs, request timing metrics, request IDs and `/ops/alerts`**;
  Prometheus-compatible endpoint remains the metrics API.
- [x] **Backup/restore scripts** and retention jobs for SQLite.
- [x] **OpenAPI contract** generated from FastAPI with a compatibility test for
  the critical `/api/v1` paths.

**Exit criteria:** restart-safe jobs, Postgres option, no secrets in responses,
load test with concurrent device ingestion + chat + admin.

### P1 — Device platform and consent

- [x] **Consent registry** per user/device/collector with purpose, retention,
  revoked_at and ingestion enforcement (`consent_denied`).
- [x] **Purpose and retention fields** on consent rows; retention overrides
  event TTL at ingestion. Event-class purpose policy can be refined per type.
- [x] **Event schema registry** with seeded schemas, validation on ingestion and
  `/api/v1/event-schemas` discovery.
- [x] **Server-to-device command channel**: create/list commands, device claim,
  result reporting, expiry and cleanup (capture pause/resume, config, queue,
  update, export, consent).
- [x] **Pairing backend**: short-lived single-use pairing codes, dashboard QR
  and deep-link issuance, redeem to create a device credential and user session,
  device rename/revoke/re-enrollment APIs.
- [x] **Pluggable private access**: access-provider resolver, automatic Tailscale
  MagicDNS discovery for pairing addresses, request and custom-URL fallbacks.
- [x] **Guided Tailscale setup**: status diagnostics, browser/QR login polling and
  a non-persistent auth-key fallback.
- [x] **Cloudflare named tunnel and LAN access providers**: LAN auto-discovery,
  public tunnel URL, endpoint lists in pairing links and client-side failover.
- [x] **Guided Cloudflare setup**: existing-service hostname verification,
  browser/QR login, tunnel/DNS creation and managed tunnel execution.
- [x] **Per-user data export and deletion** across devices, events, insights,
  conversations, memories, notifications, consents and commands.
- [x] **Retention jobs** for events, sessions, jobs, commands and pairing codes;
  consent retention overrides event TTL.
- [x] **Insight rollups**: `insight_daily` table and `/api/v1/insights/daily`.
- [x] **Fleet operations**: `/api/v1/admin/fleet/ops` for stale devices,
  expiring credentials, command status and consent gaps.
- [~] **Push notification queue and device token registration** are implemented;
  actual FCM/APNs provider delivery remains deployment work.

**Exit criteria:** a user can revoke a collector and the server stops accepting
that data; daily summaries load from rollups; export/delete covers all stores.

### P2 — Agent platform

- [x] **Durable agent runs**: run timeline events are persisted and exposed at
  `/api/v1/runs/{id}/events`; workflow replay/resume is also available.
- [x] **Durable workflows / task graph**: persisted steps, retries, compensation,
  replay and resume; completed steps are never re-run. API at `/api/v1/workflows`.
- [x] **Agent catalog and versioning**: versioned markdown definitions exposed
  at `/api/v1/agent-definitions`; registry metadata is versioned.
- [x] **Specialist agents**: insight coach, study coach and device doctor
  definitions over the `insights` tool; security/anomaly remains next.
- [x] **Context assembly tool**: `user_context` returns devices, consent,
  battery/health and a compact usage summary.
- [x] **Persistent vector store and RAG backend**: `rag_documents`, `rag_chunks`,
  `memory_embeddings`, cosine search, optional Ollama embeddings and a `rag_search` tool.
- [~] **Model router**: provider failover and local-first routing exist; token
  budgets/cost accounting remain.
- [~] **Versioned agent prompts**: definitions carry versions; a general prompt
  registry/rollback is next.
- [ ] **Guardrails**: prompt injection handling, tool allow-lists, secret
  redaction, output validation, destructive-action approval.
- [x] **Evaluation tests** for tool selection, dynamic expansion, memory ranking,
  specialist definitions and run events; golden conversations remain next.
- [ ] **Agent scheduler**: daily/weekly reviews, reminders, anomaly checks,
  budgeted background reasoning.

**Exit criteria:** an agent run survives restart; every tool call is attributable
and auditable; specialist agents answer common insight questions reliably.

### P3 — Insight product

- [ ] **Insight API v2**: daily/weekly summaries, trends, comparisons, top apps,
  categories, focus, health, device fleet, explanation references.
- [ ] **Explainability**: every recommendation links to aggregate metrics and
  the events/rollups that produced it.
- [ ] **Feedback loop**: useful/not useful, mute a recommendation, tune
  thresholds; store per user and per insight type.
- [ ] **Goal and preference model**: study goals, screen-time limits, focus
  windows, quiet hours, notification preferences.
- [ ] **Action layer**: start focus session, suggest app limits, schedule break,
  create reminder, ask user for approval.
- [ ] **Weekly review generation** with server-side scheduling and delivery.
- [ ] **Admin fleet insights**: aggregate health, privacy-safe trends.

### P4 — Ecosystem and scale

- [x] **Plugin/extension API**: manifest-discovered plugins, versioned SDK,
  declared permissions, tools, routes, sensors, agents, prompt specialists,
  events, jobs and namespaced state. Enable/disable/reload via
  `/api/v1/plugins`; guide in `docs/dev/plugin-sdk.md`.
- [x] **MCP tool marketplace** and remote tool allow-list policies: curated
  catalogue, install/enable/connect lifecycle and `default`/`user`/`role`/`org`
  policies enforced by the tool executor.
- [x] **Multi-tenant organizations/teams**: organizations, membership roles and
  optional `X-Organization-ID` scoping for workflows, RAG, objects and usage.
- [x] **Object storage**: local SHA-256 store plus S3-compatible SigV4 backend;
  `/api/v1/objects` upload/list/download/delete.
- [x] **Horizontal API/worker scaling**: stateless API, durable multi-worker job
  queue, optional Redis/NATS broker adapter and PostgreSQL read-replica helper.
- [x] **Update channel** for server and client versions with semver checks,
  channels and minimum-version gates.
- [x] **Cost/quota dashboard** for LLM calls, storage and device events: usage
  ledger, daily/model/agent summaries, resource usage and user/org/global token
  and cost quotas.

Full design notes: [P4_ECOSYSTEM.md](../designs/p4-ecosystem.md).

### P5 — Operations and security

- [ ] TLS termination, CSRF protection, secure cookie settings, CORS policy.
- [ ] Dependency/security scanning and signed release artifacts.
- [ ] Alerting for failed outbox, credential expiry, queue backlog, agent
  failures and disk/database pressure.
- [ ] Disaster recovery drill and documented RPO/RTO.
- [ ] Tenant/user isolation tests and fuzzing for ingestion, auth and tools.
- [ ] Accessibility and localization of server-rendered UI.

---

## 4. Data model additions

| Table | Purpose |
|---|---|
| `device_consents` | per-device/collector consent, purpose, TTL, revoked_at |
| `event_schemas` | event type, schema version, validation rules |
| `device_commands` | server-to-device queued commands and results |
| `insight_daily` | per-device/day app, category, screen, focus, health rollup |
| `insight_weekly` | weekly aggregates and generated summaries |
| `agent_runs_v2` | durable plan/steps/status/budget and resumability |
| `agent_approvals` | human approval for destructive actions |
| `prompt_versions` | prompt registry and rollback |
| `model_usage` | tokens, latency, provider, user/agent cost attribution |
| `user_data_requests` | export/delete jobs and completion state |
| `notification_queue` | push/email/in-app delivery and retries |
| `insight_feedback` | useful/not useful and reason |
| `device_pairing_codes` | short-lived pairing tokens |

Add indexes for:
`device_events(device_id, occurred_at)`,
`device_events(event_type, occurred_at)`,
`agent_runs(user_id, created_at)`,
`insight_daily(device_id, date)`.

---

## 5. API additions

- `GET/PUT /api/v1/consent/{device_id}` — collector consent and purpose
- `POST /api/v1/devices/{id}/commands` — queued device command
- `GET /api/v1/devices/{id}/commands` — device polls commands
- `POST /api/v1/devices/pairing-code` / redeem — pairing
- `GET /api/v1/insights/daily?device_id=&from=&to=`
- `GET /api/v1/insights/trends`
- `POST /api/v1/insights/feedback`
- `GET/POST /api/v1/goals`
- `POST /api/v1/agents/{id}/runs` / `GET /runs/{id}` — durable runs
- `POST /api/v1/agents/{id}/approvals/{approval_id}` — approve/deny
- `GET /api/v1/admin/jobs` — outbox, rollups, retention, failed work
- `POST /api/v1/admin/jobs/{id}/retry`
- `GET /api/v1/admin/audit` — already present; add filters
- `POST /api/v1/account/export` / `DELETE /api/v1/account/data`

All new APIs must include scopes, cursor pagination, idempotency keys for
mutations and structured error codes.

---

## 6. Security and privacy checklist

- Consent is checked before storage, not only in the client UI.
- Device credentials are hashed, expiring, revocable, rotated and scoped.
- Raw event payloads are never exposed to admins by default.
- Insight endpoints return aggregates only unless `include_payload` is explicitly
  authorized and audited.
- Agent context is filtered by the same consent and access rules as the user.
- Every admin, agent, tool and device action is audited with correlation IDs.
- Sensitive data has a retention TTL and a deletion path.
- Secrets never appear in `/config`, logs, tool results or chat responses.
- Backups are encrypted and access-controlled.

---

## 7. Suggested delivery order

### First 30 days
1. Postgres adapter + full migration runner
2. Worker process + durable job queue
3. Consent registry + schema registry
4. Insight daily rollups + job status admin
5. Secrets/key handling and rate limits

### Next 60 days
1. Durable agent runs + approvals
2. Memory/RAG v2 and model router budgets
3. Specialist student/wellbeing agents over insight context
4. Export/delete and retention jobs
5. Observability and alerting

### Next 90 days
1. Device command channel + pairing
2. Push notifications and weekly reviews
3. Plugin/extension API
4. Scale-out worker topology and object storage
5. Security review, load tests and DR drill

---

## 8. Definition of done for the server

- Acknowledged events survive restart and are never lost silently.
- A revoked consent stops ingestion and deletes/ages out derived data.
- An admin can see health, jobs, agents, users, devices and audit in the UI/API.
- A user can export and delete all their data.
- An agent run is resumable, budgeted, explainable and auditable.
- Insights load from rollups, not raw event scans.
- The system passes a concurrent load test on Postgres with workers.
- Secrets, TLS, backups and alerting are documented and tested.
