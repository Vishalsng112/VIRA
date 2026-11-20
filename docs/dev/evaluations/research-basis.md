# Evaluation research basis

Phase 5's evaluation harness applies published agent-evaluation ideas to a
local-first, tool-using assistant. The goal is not to reproduce a benchmark
leaderboard; it is to make **tool selection, task completion, memory retrieval,
failure recovery and safety** measurable on every commit without a model or
network.

## Papers and what VIRA adopts

| Paper | Idea adopted | VIRA implementation |
|---|---|---|
| **ReAct** — Yao et al., 2022 (arXiv:2210.03629) | Interleave reasoning with actions; observations drive the next step. | The agent loop already emits `thought` + one tool call + observation per step. Evaluation checks multi-step completion and failure recovery. |
| **Toolformer** — Schick et al., 2023 (arXiv:2302.04761) | The model decides *whether* and *which* tool to call. | `tool_selection` measures top-1 and top-3 routing over a representative catalogue. |
| **ToolBench / ToolLLM** — Qin et al., 2023 (arXiv:2307.16789) | API selection and argument correctness in a large tool space. | `tool_selection` checks routing; generated tools validate parameters and only support one safe HTTPS GET shape. |
| **AgentBench** — Liu et al., 2023 (arXiv:2308.03688) | Multi-environment task completion rather than single-turn QA. | `task_completion` runs device, database, RAG and web agent-loop tasks end to end. |
| **τ-bench** — Yao et al., 2024 (arXiv:2406.12045) | Tool-agent-user interaction and pass^k reliability. | The harness runs every suite twice and reports `repeat_stable`; the live benchmark supports `--runs 10`. |
| **LongMemEval** — Wu et al., 2024/2025 (arXiv:2410.10813) | Long-term memory includes information extraction, multi-session reasoning, temporal reasoning, knowledge updates and abstention. | `memory_retrieval` covers single-session, multi-session, knowledge update, recency, abstention and user feedback. |
| **RAGAS** — Es et al., 2023 (arXiv:2309.15217) | RAG quality needs context relevance, faithfulness and answer relevance. | `task_completion` checks that RAG questions call `rag_search` and answer from the retrieved note; the RAG service enforces per-user scoping. |
| **Reflexion** — Shinn et al., 2023 (arXiv:2303.11366) | Learn from failed attempts rather than repeating them. | The loop blocks repeated calls and stores lessons; `failure_recovery` covers error correction, repeated calls, malformed JSON and invented tools. |
| **SWE-bench** — Jimenez et al., 2023 (arXiv:2310.06770) | Task completion is only credible when an executable check passes. | Every case is deterministic and executable; CI runs the full evaluation in `vira/tests/test_phase5.py`. |
| **WebArena** — Zhou et al., 2023 (arXiv:2307.13854) | Realistic tool environments expose failure modes that toy prompts miss. | Web cases are deterministic scripts that simulate search failure and recovery, rather than depending on network availability. |

## What this harness does not claim

- It is **not** a model-quality leaderboard. The deterministic suites use
  scripted replies so they can run in CI. Real model quality is measured by
  `scripts/benchmark.py --runs N`.
- It does **not** prove prompt-injection resistance. It verifies approval gates,
  safe tool schemas and scoped retrieval; adversarial model behaviour remains a
  research problem.
- It does **not** reproduce LongMemEval's full dataset. It adopts its five memory
  abilities as test categories and uses small, inspectable fixtures.
- It does **not** replace penetration testing or a formal security review.

## Reproducing

```bash
python3 scripts/evaluate.py
python3 scripts/evaluate.py --json
python3 scripts/evaluate.py --write
python3 -m unittest vira.tests.test_phase5 -v
```

Results are recorded in:

- `docs/dev/evaluations/agent-platform.md`
- `docs/dev/evaluations/agent-platform.json`

The JSON report includes the git revision, VIRA version, Python/platform, per-case
results and whether the deterministic suites were stable across a repeat run, so
two releases can be compared directly.
