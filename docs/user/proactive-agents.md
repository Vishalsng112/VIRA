# Proactive agents and schedules

VIRA can run an agent on a schedule, not only when you send a chat message.
Schedules are opt-in, user-scoped and durable across restarts.

This first release ships the **scheduling, delivery and safety prerequisites**
for the five daily-use agents in the
[agent roadmap](../dev/roadmap/agents.md). You can already schedule any
installed agent; the five recommended agents are delivered next.

## Recommended agents

`GET /api/v1/agent-recipes` returns the onboarding catalog:

| Agent | Daily trigger | Architecture | Status |
|---|---|---|---|
| Morning Brief | morning | single | **available** |
| Focus & Wellbeing Coach | morning, mid-day, evening | single | planned |
| Second Brain | capture + weekly consolidation | single | planned |
| Chief of Staff | morning and evening | centralized | planned |
| Household & Life Admin | morning, evening, weekly review | single | planned |

Each recipe includes its pitch, required tools, default schedule and current
status.

## Morning Brief

The Morning Brief agent is installed as `morning-brief`. It collects the
configured context tools (by default `user_context` and `insights` for the last
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
        - name: user_context
        - name: insights
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

## See what can be scheduled

```bash
curl -s http://localhost:8000/api/v1/agent-schedules/agents \
  -H "Authorization: Bearer <session>"
```

This lists installed agents with their coordination architecture.

## Create your first schedule

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

External delivery uses a JSON webhook, which can be an FCM/APNs gateway, a
desktop notifier or an automation service. Configure it in `config.yaml`:

```yaml
notifications:
  webhook_url: "https://notify.example.com/vira"
  webhook_timeout_seconds: 10
  max_attempts: 3
```

Then add `"webhook"` to the schedule's `channels`. The worker retries pending
deliveries and records the last error.

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
