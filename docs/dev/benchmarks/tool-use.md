# Tool-use benchmark

Generated: 2026-11-20 · revision `f2407c8`

This benchmark has two layers. The deterministic layer runs without a
model and checks the agent loop's tool selection and recovery behaviour.
The live layer measures a real model and is intentionally run on the
machine that will serve users.

## Deterministic baseline (offline)

| Scenario | Category | Result | Tool calls | Steps | What it checks |
|---|---|---|---|---|---|
| `device_question` | device | PASS | insights | 1 | Asked for a device summary and answered from the insights tool. |
| `database_question` | database | PASS | database_query.database_query | 1 | Used the read-only SQL tool and answered from its row set. |
| `rag_question` | rag | PASS | rag_search | 1 | Retrieved a note with RAG before answering. |
| `web_failure_recovery` | web | PASS | mcp_server.web_search, mcp_server.web_browse | 2 | Recovered from a failed search by browsing a result. |
| `repeated_call_guard` | robustness | PASS | insights, insights | 3 | Blocked an identical repeat and accepted a changed call. |
| `malformed_json` | robustness | PASS | database_query.database_query | 1 | Repaired fenced JSON with trailing commas. |
| `unknown_tool_recovery` | robustness | PASS | insights | 2 | Rejected an invented tool and picked a real one. |

Offline result: **7/7 scenarios passed**.

## Live run

The current live result is recorded separately in the
[live tool-use benchmark](tool-use-live.md) because it depends on the host and
the model. Against the recommended `ornith-1.5:9b` model on the maintainer
server, 10 repetitions produced:

| Scenario | Runs passed |
|---|---|
| Device question | 10/10 |
| Database question | 10/10 |
| RAG question | 9/10 |
| Web question | 10/10 |

Run it against your own server and model:

```bash
VIRA_USERNAME=you VIRA_PASSWORD=... python3 scripts/benchmark.py --runs 10 \
  --write docs/dev/benchmarks/tool-use-live.md
```

The Phase 2 target is at least 9/10 successful runs on the recommended
local model, with device, database and RAG questions answered from tools.

## Reproduce

```bash
python3 scripts/benchmark.py --offline
python3 -m unittest vira.tests.test_benchmark -v
```
