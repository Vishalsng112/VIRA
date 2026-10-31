# VIRA Missions - brief in, product out

Give one high-level task ("Build a labour-payment app in Flutter", "TallyPrime-style accounting software", anything).
The **Master agent** decides how many expert sub-agents are needed, writes each persona, splits the work into a
dependency graph, spawns the agents, and they build the product together.

```
brief -> Master plan (roles + personas + stack + architecture + tasks)      vira/mission/plan.py
      -> N CrewAgents start in parallel, each pulls the ready tasks it owns   vira/mission/crew.py
      -> agents talk ([QUESTION] [DECISION] [BLOCKER] [REVIEW] [REQUEST] [DONE]),
         share a decision log, keep notes, write whole files into a sandbox     vira/mission/workspace.py
      -> broken files (syntax/JSON, cut-off output, no files) go back to their author
      -> Master review: missing deliverables + checks + LLM integration review -> fix tasks
      -> README.md + MISSION_REPORT.md, project downloadable as .zip
```

## Use it
* In VIRA: log in as admin -> `http://<host>:8000/mission`, type the brief, **Start mission**.
* Standalone: `python -m vira.mission "your brief"` -> `http://127.0.0.1:8766/` (`--mock` = offline fake model).
* API: `POST /api/mission/start {brief}`, `GET /api/mission/{id}/state`, `/stream` (SSE), `/files`, `/file?path=`,
  `/download`, `POST /{id}/say` (steer the team), `POST /{id}/stop`.

The page shows the team (persona, current activity, notes), team chat, task board, activity log, decisions and a live
file browser. Steer the team any time from the input box.

## Safe by design
Agents only write inside `data/missions/<id>/project` (no `..`, no absolute paths, no hidden dirs, size caps).
Nothing generated is ever executed; only `ast.parse` / `json.loads` checks run. A hard `max_llm_calls` budget and
`max_minutes` stop runaway missions gracefully (status `budget_exhausted` / `timeout`, files kept).

## Tuning
Local small model: `llm_concurrency: 1`, `max_agents: 4-5`, `max_tokens` 3000-4096.
Hosted model: `llm_concurrency: 4`, `max_agents: 8`, `max_llm_calls: 300`.
Config lives under `mission:` in `config.yaml`. The older `/swarm` personas (vira/swarm) are untouched.

## Limits (honest)
Output quality = the model's quality; the framework adds structure, review and retries, not intelligence.
Agents cannot compile/run the product (e.g. `flutter build`) - run it yourself from the downloaded zip.
