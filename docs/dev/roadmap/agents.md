# Agent roadmap — daily-use agents

Status: active implementation plan
Last updated: 2026-11-21
Scope: proactive, recurring agents that make VIRA useful every day.

**Current status:** P0 prerequisites and P1 Morning Brief are implemented and
tested. P2 Focus & Wellbeing Coach is next.

This roadmap turns the paper-aligned agent architectures and VIRA's device,
memory, knowledge and tool platform into five daily-use agents. It deliberately
puts **shared prerequisites first**: without scheduling, delivery, safety and
discovery, every agent would become a one-off demo.

Related documents:

- [Agent architectures](../architecture/agent-architectures.md)
- [Agent design](../architecture/agent-design.md)
- [Product roadmap](../../../ROADMAP.md)
- [Server roadmap](server.md)

---

## Principles

1. **Proactive but opt-in.** A recurring agent only runs after the user creates
   or enables a schedule.
2. **Local-first and permissioned.** Agents use the same user/device scopes,
   consent, approvals and audit as chat.
3. **Bounded.** Every run has worker, round, time and token limits.
4. **Observable.** Every scheduled run has a durable run record, timeline and
   notification.
5. **Architecture-aware.** The agent's coordination topology is explicit
   (`single`, `centralized`, etc.) and recorded with the run.
6. **One useful output per trigger.** A daily agent should produce a short
   result the user can act on, not a wall of text.

---

## P0 — Prerequisites (must ship first)

These are shared by all five agents. None of them is agent-specific.

### P0.1 Durable agent schedule store

- [x] `agent_schedules` table: owner, agent, schedule spec, timezone,
      quiet hours, channels, task profile, enabled state, next run and lock.
- [x] `agent_schedule_runs` table: per-run status, result/error, run id,
      notification id and timestamps.
- [x] SQLite migration and PostgreSQL schema parity.
- [x] Strict user/organization scoping on every read and write.

**Acceptance:** a schedule survives restart; another user cannot read, change,
run or delete it.

### P0.2 Proactive scheduler loop

- [x] In-process scheduler owned by the agent orchestrator (not a second
      runtime).
- [x] Atomic claim of due schedules with lock expiry, so a crash retries
      instead of losing the run or double-running forever.
- [x] Bounded concurrency, timeouts and failures recorded per run.
- [x] Daily, weekly and interval schedules with IANA timezones and quiet hours.
- [x] `next_run_at` advanced using the schedule's timezone, not server-local
      time.

**Acceptance:** a daily 08:00 schedule runs once per day in its timezone; a
server restart does not silently lose a due schedule.

### P0.3 Proactive task contract

- [x] `RuntimeScheduler.run_task()` executes a `TaskRequest` with the same
      identity, lifecycle and error handling as chat.
- [x] Scheduled requests carry `user_id`, `organization_id`, `run_id`, trigger
      metadata and an optional task profile.
- [x] The agent's architecture and coordination data are recorded in the run.
- [x] Proactive runs appear in the durable run timeline.

**Acceptance:** any registered `BaseAgent` can be scheduled without a new
adapter or a special "cron agent" implementation.

### P0.4 Notification delivery

- [x] In-app notifications are delivered immediately and remain unread until
      opened.
- [x] External delivery uses a provider interface; webhook is the first
      provider.
- [x] Retries, attempts and last error are stored; duplicates are suppressed
      with a dedupe key.
- [x] Worker periodically delivers pending notifications.
- [x] Quiet hours suppress or defer scheduled notifications.

**Acceptance:** a scheduled run creates an in-app notification; a configured
webhook receives the same payload; a failed webhook is retried and then marked
failed.

### P0.5 Discovery and onboarding metadata

- [x] A machine-readable catalog of the five recommended agents: pitch, daily
      trigger, required tools, default schedule, architecture and status.
- [x] API endpoint for the catalog and for schedule CRUD/run-now.
- [x] Documentation that explains the first useful setup in under five minutes.

**Acceptance:** a client can list the recommended agents, create a schedule for
an installed agent, and show the next run time without reading source code.

### P0.6 Safety and control

- [x] Schedules are user-scoped and require an authenticated user.
- [x] Mutation endpoints are rate-limited by the existing middleware.
- [x] Proactive runs use the same tool permissions, approvals and audit as chat.
- [x] Users can disable or delete a schedule at any time.
- [x] Notification content is not exposed across users.

**Acceptance:** disabling a schedule stops future runs; destructive tools still
require approval during a proactive run.

---

### P0 implementation notes

- Schedule store and math: `vira/agent/schedules.py`.
- In-process scheduler: `vira/agent/proactive.py`, owned by
  `AgentOrchestratorModule`.
- Typed proactive runs: `RuntimeScheduler.run_task()`.
- Delivery: `vira/notifications.py` plus the `notifications.deliver` worker job.
- API: `vira/api/routes_schedules.py` (`/api/v1/agent-schedules`,
  `/api/v1/agent-recipes`).
- Schema: migration 17 and PostgreSQL parity.
- Tests: `vira/tests/test_agent_schedules.py`.

## P1 — Morning Brief — implemented

**Pitch:** "Open VIRA with your coffee. It already knows what matters today."

**Daily trigger:** daily at a user-selected time (default 07:30).

**Output:** a short brief covering calendar, tasks, device/fleet health,
yesterday's focus context and the first three actions.

**Architecture:** `SingleAgent` with tools by default. Switch to
`CentralizedAgentSystem` only when the user connects many sources and the
profile justifies the coordination cost.

**Uses:** `insights`, `user_context`, device events, memory, knowledge,
optional MCP calendar/task/email connectors.

**Implementation:**
- Agent: `vira/agent/Agents/morning_brief.py`, registered as `morning-brief`
  in `config.yaml`.
- Collects configured `context_tools`, labels missing/erroring sources as
  `UNAVAILABLE`, and synthesizes with the LLM.
- Deterministic fallback brief when the model is unavailable.
- Returns source names and unavailable reasons in `TaskResult.data`.
- End-to-end schedule delivery is covered by `vira/tests/test_morning_brief.py`.

- [x] One notification per day, deduplicated across restarts.
- [x] Every claim is traceable to a tool result or labelled as unavailable.
- [x] The user can mute, pause or change the time from the API/client.
- [x] Deterministic fallback keeps the habit working without a model.
- [x] Optional calendar/task/email MCP tools via `context_tools`.

**Acceptance evidence:** `python3 -m unittest vira.tests.test_morning_brief -v`.

**Metrics:** daily active briefs, open rate, 7/30-day retention.

## P2 — Focus and Wellbeing Coach

**Pitch:** "Your agent sees your actual screen time, focus and device signals —
privately."

**Daily triggers:** a morning focus plan, optional mid-day check-in and an
evening review. Weekly report on demand or scheduled.

**Architecture:** `SingleAgent` for coaching. Weekly report may use
`CentralizedAgentSystem` when there are multiple devices or categories.

**Uses:** VIRA Link app usage, screen sessions, focus sessions, battery/idle
signals, `insights`, memory of goals.

**Acceptance:**
- Recommendations reference measured data, not generic advice.
- Break reminders respect quiet hours and notification settings.
- Weekly report can be exported without raw app titles.

**Metrics:** daily active coaching users, focus sessions started, weekly report
views.

---

## P3 — Second Brain and Memory Curator

**Pitch:** "Tell VIRA once. It remembers — locally, with your permission."

**Daily triggers:** capture is user-initiated; a weekly consolidation runs on a
schedule.

**Architecture:** `SingleAgent` for capture and retrieval; consolidation stays
single-agent because it is sequential.

**Uses:** scoped knowledge base, memory ranking/feedback, RAG, conversation
history, export/delete.

**Acceptance:**
- "What did I decide about X?" returns the source item and date.
- Users can inspect, correct and delete what VIRA remembers.
- Weekly consolidation reports duplicates and stale items without deleting
  anything automatically.

**Metrics:** captures per active user, retrieval success, 30-day retention,
memory items per user.

---

## P4 — Chief of Staff (inbox, calendar, tasks)

**Pitch:** "Your agent triages the day and drafts the boring replies — you
approve what sends."

**Daily triggers:** morning triage and evening follow-up.

**Architecture:** `CentralizedAgentSystem` for parallel thread/category triage
with an orchestrator validation pass; `SingleAgent` for quick replies.

**Uses:** MCP email/calendar/task connectors, memory of people and preferences,
approval gates, audit.

**Acceptance:**
- Drafts never send without explicit approval.
- Action items are extracted with source links.
- Connector failures degrade gracefully and are reported in the brief.

**Metrics:** drafts accepted, time saved, connector adoption, daily active
users.

---

## P5 — Household and Life Admin

**Pitch:** "The family operations agent that lives on your own server."

**Daily triggers:** morning plan and evening check; weekly household review.

**Architecture:** `SingleAgent` for everyday questions;
`CentralizedAgentSystem` for the weekly plan (meals, budget, chores in
parallel).

**Uses:** family/household data, memory, local files, MCP tools, reminders.

**Acceptance:**
- Multiple household members can share schedules and lists.
- Family data is scoped to the household; non-members cannot read it.
- Weekly review is delivered to each member according to their own quiet hours.

**Metrics:** households with 2+ active members, weekly review open rate,
retention.

---

## Delivery order

1. P0 prerequisites.
2. P1 Morning Brief — fastest daily habit and the best demo.
3. P2 Focus Coach — strongest VIRA Link differentiator.
4. P3 Second Brain — compounding retention.
5. P4 Chief of Staff — largest time saving, integration-heavy.
6. P5 Household — multi-user growth.

---

## Non-goals

- Unbounded autonomous loops.
- Multi-agent coordination by default.
- Sending messages, spending money or changing settings without approval.
- Always-on sensing or notification permission without an explicit user action.
- A hosted multi-tenant SaaS control plane.
