# Agent and tool platform

Phase 5 makes the agent platform measurable and reviewable. This page is the
developer reference for generated artifacts, budgets, memory ranking, run
recovery, cost budgets and observability.

Research basis and evaluation design: [evaluation research basis](evaluations/research-basis.md).
Current results: [agent platform evaluation](evaluations/agent-platform.md).

## Generated tools and agents

Generated artifacts always follow:

```text
draft → approved → enabled
        ↘ rejected
enabled → disabled → enabled
```

**A draft never executes.** Both the tool runtime and the agent runner re-check
the stored status and `approved_at` on every invocation, so disabling or rejecting
an artifact takes effect immediately even if a registry still holds an old tool
object.

### Create a draft

```bash
curl -s -X POST http://localhost:8000/api/v1/generated \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "tool",
    "name": "weather_lookup",
    "version": "1.0.0",
    "description": "Look up a city forecast",
    "spec": {
      "type": "http",
      "method": "GET",
      "url": "https://api.example.com/weather",
      "allowed_hosts": ["api.example.com"],
      "parameters": {"city": {"type": "string", "required": true}},
      "query": {"city": "{city}"},
      "response_format": "json"
    }
  }'
```

Generated tools are intentionally narrow:

- one HTTPS `GET`;
- no custom headers, tokens or request bodies;
- an explicit host allow-list;
- public-address SSRF checks;
- JSON output validation when `response_format` is `json`;
- bounded response size.

### Create a draft agent

```json
{
  "kind": "agent",
  "name": "brief_writer",
  "version": "1.0.0",
  "description": "Writes a short evidence-based brief",
  "spec": {
    "system_prompt": "You are a careful briefing agent. Use the allowed tools and never invent facts.",
    "tools": ["rag_search", "web_search"],
    "max_steps": 4,
    "temperature": 0.2
  }
}
```

An enabled agent runs through `POST /api/v1/generated/{id}/run` with a bounded
`AgentLoop`, the allow-listed tools and the configured step budget.

### Review and enable (administrator)

```bash
POST /api/v1/generated/{id}/approve
POST /api/v1/generated/{id}/enable
POST /api/v1/generated/{id}/disable
POST /api/v1/generated/{id}/reject   {"reason": "..."}
GET  /api/v1/generated
```

Every transition is audited. The dashboard **Agents → Generated tools and agents**
view exposes the same actions.

## Tool budgets and safety

| Control | Where | Default |
|---|---|---|
| Max tool steps | `agents[].config.max_steps` | 6 |
| Per-tool timeout | `tool_timeout` | 90 s |
| Whole-run observation budget | `max_total_tool_chars` | 30,000 chars |
| Wall-clock budget | `max_seconds` | 240 s |
| Per-run tool-call budget | `max_steps` + loop repeat guard | — |
| Destructive approval | `security.approvals` | enabled |
| Output clipping | loop + generated JSON validation | — |

When a budget is exhausted the loop stops calling tools and writes the best
answer from the observations it has. It never silently continues forever.

## Memory ranking and user controls

Memory retrieval uses a transparent score:

```text
0.55 * relevance
+ 0.20 * importance
+ 0.15 * recency (30-day half-life)
+ 0.10 * agreement
+ feedback bonus (useful +0.15, not_useful -0.35)
```

Muted memories are excluded from both lexical and vector retrieval. Retrieval
marks `last_used_at` and increments `use_count`.

User controls:

```bash
POST /api/v1/memories/{id}/feedback   {"useful": true, "note": "current"}
POST /api/v1/memories/{id}/feedback   {"useful": false}
POST /api/v1/memories/{id}/feedback   {"muted": true}
DELETE /api/v1/memories/{id}
```

The evaluation suite covers single-session recall, multi-session recall,
knowledge updates, recency, abstention and feedback.

## Run recovery and observability

`GET /api/v1/runs?status=failed` lists a user's runs. A failed or interrupted run
can be resumed without duplicating the original user message:

```bash
POST /api/v1/runs/{run_id}/resume
```

At API startup, queued/running runs are marked failed with
`interrupted by server restart`, so they become visible and resumable instead of
looking active forever. The dashboard **Agents → Recent agent runs** view shows
status, failure reason, a redacted trace and a Resume action.

`GET /api/v1/runs/{run_id}/timeline` returns:

- run status and failure reason;
- thinking/tool/check events;
- tool inputs and results with secret-looking values redacted;
- bounded previews.

Chat already streams the same events live and stores the trace with the answer.

## Cost and token budgets

Quota scopes are `user`, `agent`, `org` and `global`, with `day` or `month`
periods. Agent quotas let you cap a specific agent independently of the user.

```bash
PUT /api/v1/admin/quotas
{
  "scope": "agent",
  "subject_id": "chat",
  "period": "month",
  "token_limit": 500000,
  "cost_limit_usd": 5
}
```

The usage dashboard shows token/cost totals, per-model and per-agent breakdowns,
quota consumption and the quota form (including `agent` scope).

## Agent templates

Built-in specialist definitions now include:

- `incident_triage` — evidence-based server/device triage;
- `research_brief` — local RAG + public web evidence with citations;
- `data_steward` — read-only inventory and data-quality answers;
- plus the existing `researcher`, `critic`, `insight_coach`, `study_coach` and
  `device_doctor`.

## Evaluation

```bash
python3 scripts/evaluate.py --write
python3 -m unittest vira.tests.test_phase5 -v
```

The report includes tool-selection top-1/top-3, task completion, memory
abilities, failure recovery, destructive-action guards and run recovery. It is
deterministic, runs twice for repeat stability, and records the git revision so
releases can be compared.
