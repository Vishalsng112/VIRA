# Tool-use benchmark

Generated: 2026-11-21 · revision `f2407c8`

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

## Live run (10 repetitions)

Server: `http://localhost:8000` · model: `ornith-1.5:9b` (the recommended local model).

| Scenario | Result | Runs passed | Tools observed | Detail |
|---|---|---|---|---|
| `device_question` | PASS | 10/10 | database_account_summary | tool calls: database_account_summary |
| `database_question` | PASS | 10/10 | database_query, database_schema, database_tables | tool calls: database_query |
| `rag_question` | PASS | 9/10 | filesystem, rag_search, tool_search | tool calls: rag_search, filesystem, filesystem, filesystem · failures: rag_search (recovered) |
| `web_question` | PASS | 10/10 | web_browse, web_search | tool calls: web_search, web_browse |

## Reproduce

```bash
python3 scripts/benchmark.py --offline
python3 -m unittest vira.tests.test_benchmark -v
```
