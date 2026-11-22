# Proactive agents and schedules

VIRA can run an agent on a schedule, not only when you send a chat message.
Schedules are opt-in, user-scoped and durable across restarts.

This first release ships the **scheduling, delivery and safety prerequisites**
for the five daily-use agents in the
[agent roadmap](../dev/roadmap/agents.md). You can already schedule any
installed agent; the five recommended agents are delivered next.

## Where you see results

- **Web dashboard → Inbox**: unread agent results, schedule list, schedule
  create/edit/pause/delete, run-now and run history.
- **VIRA Link → Inbox** (mobile and desktop client): unread agent updates,
  full result text, agent recipe cards, schedule creation/editing, pause/resume,
  delete, next run time, run-now and run history.
- **Native notifications** in VIRA Link while it is running, after the user
  enables the permission in Settings.
- **API**: `GET /api/v1/notifications`,
  `GET /api/v1/agent-schedules`,
  `GET /api/v1/agent-schedules/{id}/runs`.
- **Webhook or push relay** (optional): forward notifications to a desktop
  notifier, FCM/APNs gateway or automation service.

## Recommended agents

`GET /api/v1/agent-recipes` returns the onboarding catalog:

| Agent | Daily trigger | Architecture | Status |
|---|---|---|---|
| Morning Brief | morning | single | **available** |
| Focus & Wellbeing Coach | morning, mid-day, evening | single | **available** |
| Second Brain | capture + weekly consolidation | single | **available** |
| Chief of Staff | morning and evening | centralized | **available** |
| Household & Life Admin | morning, evening, weekly review | single → centralized weekly | **available** |

Each recipe includes its pitch, required tools, default schedule and current
status.

## Morning Brief

The Morning Brief agent is installed as `morning-brief`. It collects the
configured context tools (by default `vira.context` and `vira.insights` for the last
day), adds recent memory, and writes a short brief with three sections:

1. **Today** — priorities supported by the collected context.
2. **Device & focus** — battery, device health and focus summary.
3. **Do first** — at most three concrete actions.

Missing tools are shown as `UNAVAILABLE` rather than guessed. If the model is
down, a deterministic fallback still produces the brief.

To use a calendar, task or email MCP connector, add its tool name to the agent
config:

```yaml
agents:
  - name: MorningBriefAgent
    module: vira.agent.Agents.morning_brief
    class: MorningBriefAgent
    agent_id: morning-brief
    enabled: true
    config:
      context_tools:
        - name: vira.context
        - name: vira.insights
          params: {days: 1}
        - name: mcp_server.calendar_today
        - name: mcp_server.tasks_due
```

Then schedule it:

```bash
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "morning-brief", "name": "Morning brief",
       "message": "Write my morning brief.", "schedule_type": "daily",
       "time_of_day": "07:30", "timezone": "Asia/Kolkata"}'
```

## Focus & Wellbeing Coach

Installed as `focus-coach`. One agent supports four modes through the schedule
`input`:

| Mode | What it produces |
|---|---|
| `morning` | A focus plan for today with 2–4 blocks and a break rule |
| `checkin` | A two-sentence mid-day observation and nudge |
| `evening` | An evening review with one win, one adjustment and tomorrow’s first block |
| `weekly` | A weekly report with totals, category balance and three recommendations |

Recommendations cite measured numbers from `vira.insights` and `vira.context`. Goals
come from memory. Weekly mode hides specific app names by default; categories and
totals remain.

```bash
# Evening review every day
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "focus-coach", "name": "Evening review",
       "message": "Review my focus today.", "schedule_type": "daily",
       "time_of_day": "18:30", "timezone": "Asia/Kolkata",
       "input": {"mode": "evening"}}'

# Weekly report on Sunday evening, with app names hidden
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "focus-coach", "name": "Weekly focus",
       "message": "Write my weekly report.", "schedule_type": "weekly",
       "weekday": 6, "time_of_day": "19:00",
       "timezone": "Asia/Kolkata", "input": {"mode": "weekly"}}'
```

Quiet hours are applied by the scheduler, so a check-in or break reminder never
fires during the user’s quiet window.

## Second Brain

Installed as `second-brain`. It supports three modes:

| Mode | What it does |
|---|---|
| `capture` | Saves the note as verified personal knowledge |
| `ask` | Answers from stored notes with numbered citations and dates |
| `correct` | Creates a superseding revision of an existing item |
| `consolidate` | Reports duplicates, stale items and low-confidence items without deleting anything |

Capture is normally done from chat: “Remember that the vendor contract renews
in March.” The important rule is that capture only stores what the user
explicitly asked to remember.

```bash
# Weekly consolidation report
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "second-brain", "name": "Second brain review",
       "message": "Consolidate my notes.", "schedule_type": "weekly",
       "weekday": 6, "time_of_day": "19:00",
       "timezone": "Asia/Kolkata", "input": {"mode": "consolidate"}}'
```

Capture writes to the existing scoped knowledge base, so the knowledge API,
export and delete flows continue to apply. Corrections create a new revision via
`PATCH /api/v1/knowledge/items/{item_id}`; the previous revision is retained and
marked deprecated.

## Chief of Staff

Installed as `chief-of-staff`. It collects configured email, calendar and task
connectors in parallel, extracts source-linked action items, and drafts replies.
It does **not** send anything; `sent` is always `0` and drafts are returned for a
human to approve.

VIRA includes a local, read-only reference connector at
`examples/mcp/office_server.py`. It reads:

```
data/office/emails.json
data/office/calendar.json
data/office/tasks.json
```

Register it as the MCP server `office`, then configure the tools:

```yaml
agents:
  - name: ChiefOfStaffAgent
    module: vira.agent.Agents.chief_of_staff
    class: ChiefOfStaffAgent
    agent_id: chief-of-staff
    enabled: true
    config:
      mode: morning
      context_tools:
        - {name: office.email_inbox, role: email}
        - {name: office.calendar_today, role: calendar}
        - {name: office.tasks_due, role: tasks}
```

Schedule a morning triage:

```bash
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "chief-of-staff", "name": "Morning triage",
       "message": "Triage my day.", "schedule_type": "daily",
       "time_of_day": "08:00", "timezone": "Asia/Kolkata",
       "input": {"mode": "morning"}}'
```

If a connector is unavailable, the brief lists it under **Unavailable** and
continues with the sources that worked.

## Household & Life Admin

Installed as `household`. It reads the shared household notes, reminders and
open chores, then produces a morning plan, evening check or weekly review.
Weekly mode fans out meals, budget and chores to parallel workers.

```bash
# Get the household id
curl -s http://localhost:8000/api/v1/households \
  -H "Authorization: Bearer <session>"

# Morning plan for every member, each with their own quiet hours
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "household", "name": "Household morning",
       "message": "Plan the household day.", "schedule_type": "daily",
       "time_of_day": "07:00", "timezone": "Asia/Kolkata",
       "quiet_hours_start": "22:00", "quiet_hours_end": "06:30",
       "input": {"mode": "morning", "household_id": "<household-id>"}}'
```

Each member creates their own schedule, so the weekly review respects each
person’s quiet hours. Household reads are membership-checked; non-members get a
permission error rather than partial data.

## See what can be scheduled

```bash
curl -s http://localhost:8000/api/v1/agent-schedules/agents \
  -H "Authorization: Bearer <session>"
```

This lists installed agents with their coordination architecture.

## Create your first schedule

The easiest path is **VIRA Link → Inbox → Schedules → Add schedule**. Pick an
agent recipe, choose the time, timezone, mode and quiet hours, then save.

The same flow is available over the API:

```bash
curl -s -X POST http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "morning-brief",
    "name": "Morning brief",
    "message": "Summarise my day: priorities, device health and focus context. Keep it short.",
    "schedule_type": "daily",
    "time_of_day": "07:30",
    "timezone": "Asia/Kolkata",
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "channels": ["inapp"],
    "task_profile": {"decomposability": 0.7, "sequential_dependencies": 0.2}
  }'
```

The response includes `next_run_at` in UTC. The scheduler evaluates daily and
weekly times in the schedule's IANA timezone.

### Schedule types

| Type | Fields | Example |
|---|---|---|
| `daily` | `time_of_day` (`HH:MM`) | Every day at 07:30 |
| `weekly` | `weekday` (0=Monday) + `time_of_day` | Sunday at 19:00 |
| `interval` | `interval_minutes` | Every 90 minutes |

Quiet hours apply to all types. A run scheduled inside the quiet window moves to
the end of the window instead of being dropped.

## Manage schedules

```bash
# List
curl -s http://localhost:8000/api/v1/agent-schedules \
  -H "Authorization: Bearer <session>"

# Change the time or pause it
curl -s -X PATCH http://localhost:8000/api/v1/agent-schedules/<id> \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"time_of_day": "08:00", "enabled": true}'

# Run now (queued for the next scheduler tick)
curl -s -X POST http://localhost:8000/api/v1/agent-schedules/<id>/run \
  -H "Authorization: Bearer <session>"

# Inspect runs and results
curl -s http://localhost:8000/api/v1/agent-schedules/<id>/runs \
  -H "Authorization: Bearer <session>"

# Delete
curl -s -X DELETE http://localhost:8000/api/v1/agent-schedules/<id> \
  -H "Authorization: Bearer <session>"
```

Deleting a schedule stops future runs. It does not delete runs already recorded
or notifications already delivered.

## Notifications

Every scheduled run creates an in-app notification with the agent result. In-app
notifications are available immediately:

```bash
curl -s http://localhost:8000/api/v1/notifications \
  -H "Authorization: Bearer <session>"

curl -s -X POST http://localhost:8000/api/v1/notifications/<id>/read \
  -H "Authorization: Bearer <session>"
```

### Native notifications in VIRA Link

VIRA Link keeps a live notification stream open while it is running and shows
native alerts for new agent results. Enable the OS permission from
**Settings → Permissions and notifications → Agent notifications → Enable**.
Tapping an alert opens the Agent Inbox.

This covers foreground and desktop use. Delivery while the app is fully closed
needs a remote push gateway (next section). The live stream is held by the API
process serving the client; if you run several API replicas, use the push relay
or webhook for cross-process delivery.

### External delivery

External delivery uses a JSON webhook or a push provider. Two push modes are
supported:

- `push_provider: "relay"` forwards `{tokens, notification}` to a gateway.
- `push_provider: "fcm"` sends directly through Firebase Cloud Messaging HTTP v1
  using a service account. FCM also delivers to iOS/macOS when APNs is configured
  in the Firebase project.

```yaml
notifications:
  webhook_url: "https://notify.example.com/vira"
  webhook_timeout_seconds: 10
  max_attempts: 3
  push_provider: "fcm"                 # relay | fcm
  push_relay_url: ""
  push_relay_token: ""
  push_timeout_seconds: 10
  fcm_service_account_file: "secrets/firebase-service-account.json"
  fcm_project_id: "your-firebase-project"
```

For FCM, build VIRA Link with the Firebase app values:

```bash
flutter run \
  --dart-define=VIRA_FIREBASE_API_KEY=... \
  --dart-define=VIRA_FIREBASE_APP_ID=... \
  --dart-define=VIRA_FIREBASE_MESSAGING_SENDER_ID=... \
  --dart-define=VIRA_FIREBASE_PROJECT_ID=...
```

The client registers its FCM token through
`POST /api/v1/devices/{id}/push-registration`. Android receives notifications
when the app is fully closed. iOS/macOS additionally need an APNs key uploaded to
the Firebase project and the app built with the Push Notifications capability.

The relay mode is still available for other push gateways and for deployments
that do not want a Firebase project:

```json
{"tokens": [{"device_id": "...", "platform": "android", "token": "..."}],
 "notification": {"id": "...", "title": "...", "body": "...", "data": {}}}
```

## Safety and limits

- Schedules are scoped to the authenticated user. Another user cannot read,
  change, run or delete them.
- Scheduled runs use the same tool permissions, approval gates and audit trail
  as chat.
- A run has a timeout (`agent_scheduler.run_timeout_seconds`) and the scheduler
  bounds concurrency (`max_concurrent`) and runs per tick.
- If the server restarts, due schedules are retried instead of lost; locks
  expire so a crashed run does not block forever.
- Missed days are not backfilled: after downtime the schedule runs once and
  advances to the next future occurrence, so a returning user is not flooded
  with old briefs.
- Disable a schedule with `"enabled": false` instead of deleting it if you only
  want a pause.
