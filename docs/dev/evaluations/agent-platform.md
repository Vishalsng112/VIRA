# Agent platform evaluation

Generated: 2026-11-20T20:45:10.208316+00:00 · revision `e76eb39` · VIRA `0.4.0` · Python 3.14.6

This report is deterministic and model-free. It is the comparable
baseline for tool selection, task completion, memory retrieval, failure
recovery, destructive-action guards and run recovery. Live model quality
is measured separately by `scripts/benchmark.py`.

## Summary

| Suite | Passed | Rate | Status |
|---|---|---|---|
| tool_selection | 12/12 | 100% | PASS |
| task_completion | 4/4 | 100% | PASS |
| memory_retrieval | 6/6 | 100% | PASS |
| failure_recovery | 4/4 | 100% | PASS |
| destructive_guard | 7/7 | 100% | PASS |
| run_recovery | 3/3 | 100% | PASS |

Overall: **36/36 cases passed**; repeat stability: **PASS**.

## tool_selection

Read-only tool routing over a representative catalogue. Primary metric: top-1 accuracy; top-3 is reported for recovery.

| Case | Result | Detail |
|---|---|---|
| `web_search` | PASS | expected mcp_server.web_search; got mcp_server.web_search, rag_search, filesystem |
| `web_browse` | PASS | expected mcp_server.web_browse; got mcp_server.web_browse, filesystem, database_query.database_query |
| `insights` | PASS | expected insights; got insights, utility, shell |
| `database` | PASS | expected database_query.database_query; got database_query.database_query, database_query.database_schema, user_context |
| `schema` | PASS | expected database_query.database_schema; got database_query.database_schema, user_context, insights |
| `rag` | PASS | expected rag_search; got rag_search, mcp_server.web_search, filesystem |
| `filesystem` | PASS | expected filesystem; got filesystem, sandbox, insights |
| `shell` | PASS | expected git; got git, database_query.database_query, filesystem |
| `git` | PASS | expected git; got git |
| `sandbox` | PASS | expected sandbox; got sandbox, database_query.database_query, filesystem |
| `utility` | PASS | expected utility; got utility, insights, git |
| `context` | PASS | expected user_context; got user_context, insights, database_query.database_query |

## task_completion

End-to-end agent-loop tasks for device, database, RAG and web questions.

| Case | Result | Detail |
|---|---|---|
| `device_question` | PASS | Asked for a device summary and answered from the insights tool. |
| `database_question` | PASS | Used the read-only SQL tool and answered from its row set. |
| `rag_question` | PASS | Retrieved a note with RAG before answering. |
| `web_failure_recovery` | PASS | Recovered from a failed search by browsing a result. |

## memory_retrieval

LongMemEval-inspired checks: single/multi-session recall, knowledge updates, recency, abstention and feedback.

| Case | Result | Detail |
|---|---|---|
| `single_session` | PASS | top: ['I use Adobe Photoshop for photo editing'] |
| `multi_session` | PASS | top: ['My project deadline is 12 December'] |
| `knowledge_update` | PASS | top: ['My current operating system is Linux', 'My current operating system is Windows'] |
| `recency` | PASS | top: ['My favourite editor is Vim', 'My favourite editor is Emacs'] |
| `abstention` | PASS | returned 0 unrelated memories |
| `feedback` | PASS | top: ['My preferred terminal is zsh', 'My preferred terminal is bash'] |

## failure_recovery

Recovery from tool errors, repeated calls, malformed JSON and invented tools.

| Case | Result | Detail |
|---|---|---|
| `web_failure_recovery` | PASS | Recovered from a failed search by browsing a result. |
| `repeated_call_guard` | PASS | Blocked an identical repeat and accepted a changed call. |
| `malformed_json` | PASS | Repaired fenced JSON with trailing commas. |
| `unknown_tool_recovery` | PASS | Rejected an invented tool and picked a real one. |

## destructive_guard

Destructive calls must stop at an approval gate and execute only after a single-use approval.

| Case | Result | Detail |
|---|---|---|
| `shell` | PASS | approval required |
| `filesystem_write` | PASS | approval required |
| `sandbox_execute` | PASS | approval required |
| `filesystem_read` | PASS | allowed without approval |
| `database_read` | PASS | allowed without approval |
| `executor_blocks` | PASS | APPROVAL_REQUIRED: 'filesystem' needs explicit approval (Filesystem 'write' can modify the workspace). Ask the user to a |
| `executor_after_approval` | PASS | {"written": true, "path": "eval.txt", "bytes": 2} |

## run_recovery

Interrupted runs are marked failed and visible, and the stored timeline is redacted.

| Case | Result | Detail |
|---|---|---|
| `interrupted_marked_failed` | PASS | status=failed; recovered=1 |
| `failed_run_listed` | PASS | 1 failed run(s) |
| `timeline_redacted` | PASS | 1 event(s) redacted |

## Research basis

The suite design follows published agent and memory evaluations:

- ReAct (Yao et al., 2022) — interleaved reasoning and tool actions.
- Toolformer (Schick et al., 2023) — tool selection and argument quality.
- ToolBench / ToolLLM (Qin et al., 2023) — API selection and argument correctness.
- AgentBench (Liu et al., 2023) — task completion across environments.
- τ-bench (Yao et al., 2024) — pass^k reliability and tool-agent-user interaction.
- LongMemEval (Wu et al., 2024/2025) — temporal reasoning, knowledge updates and abstention.
- RAGAS (Es et al., 2023) — context precision and faithfulness for RAG answers.

See `docs/dev/evaluations/research-basis.md` for the mapping.

