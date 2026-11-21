# Agent architectures

VIRA ships the five coordination topologies evaluated in
[*Towards a Science of Scaling Agent Systems*](https://arxiv.org/abs/2512.08296)
(Kim et al., 2025). The point of the paper is not "add more agents". It is that
**architecture must match the task**: performance ranged from +81% to −70%
relative to a single agent across the same models and tools.

The base classes live in `vira/agent/architectures.py` and are exported from
`vira.agent`.

## What the paper found

| Effect | Result | What VIRA does about it |
|---|---|---|
| Tool-coordination trade-off | Tool-heavy tasks pay a large coordination tax (`β ≈ −0.33`); more agents can be worse. | `recommend_architecture()` never defaults to multi-agent for tool-heavy or sequential tasks. |
| Capability ceiling | Above ~45% single-agent accuracy, extra agents usually lose (`β ≈ −0.41`). | Profiles with a baseline ≥ 0.45 select `SingleAgent`. |
| Error amplification | Independent agents amplified errors 17.2×; centralized coordination contained them to 4.4×. | `CentralizedAgentSystem` runs a validation pass before synthesis; `IndependentAgentSystem` is documented as high-risk. |
| Task contingency | Centralized gained +80.9% on parallel analysis; decentralized gained +9.2% on dynamic navigation; all variants lost 39–70% on sequential planning. | The selector is rule-based and conservative, falling back to a single agent. |

Measured coordination costs used by the profiles:

| Architecture | Topology | Overhead vs single | Error amplification |
|---|---|---|---|
| `SingleAgent` | one reasoning locus | 0% | 1.0× |
| `IndependentAgentSystem` | parallel workers, synthesis only | 58% | 17.2× |
| `CentralizedAgentSystem` | orchestrator + isolated workers | 285% | 4.4× |
| `DecentralizedAgentSystem` | peer-to-peer debate | 263% | 7.8× |
| `HybridAgentSystem` | orchestrator + peer review | 515% | 5.1× |

## Base classes

```python
from vira.agent import (
    SingleAgent,
    IndependentAgentSystem,
    CentralizedAgentSystem,
    DecentralizedAgentSystem,
    HybridAgentSystem,
    AdaptiveAgentSystem,
)
```

Every class extends `LLMAgent`, so it keeps prompts, tool policy, memory,
knowledge, progress events and response handling. Only the coordination loop
differs.

### `SingleAgent` — the default

One reasoning locus and one tool loop. Use it for sequential tasks, tool-heavy
work, high-baseline tasks, and anything without clear evidence for coordination.

```python
class SupportAgent(SingleAgent):
    name = "support"
    system_prompt = "Answer support questions from the local knowledge base."
    tools = {"allow": ["knowledge_search", "rag_search"]}
```

### `IndependentAgentSystem` — parallel ensemble

Runs `worker_count` workers with no inter-worker communication, then synthesizes.
Cheapest multi-agent option, but the paper measured the highest error
amplification. Use it for diverse first drafts, not for correctness-critical work.

```python
class Brainstorm(IndependentAgentSystem):
    name = "brainstorm"
    system_prompt = "Generate distinct, well-reasoned options."
    worker_count = 3          # clamped to 1..8
```

### `CentralizedAgentSystem` — orchestrator + validation

The orchestrator decomposes the task, workers run independently, the
orchestrator validates/corrects each output, then synthesizes. This is the
best default when a task decomposes into parallel analysis pieces.

```python
class Analyst(CentralizedAgentSystem):
    name = "analyst"
    system_prompt = "You are a careful financial analyst. Show assumptions."
    worker_count = 3
    max_subtasks = 3
    validate_outputs = True
```

### `DecentralizedAgentSystem` — peer debate

Peers answer, then read each other's answers for a bounded number of debate
rounds, then synthesize. The paper found this useful for dynamic, high-entropy
search such as web navigation.

```python
class Scout(DecentralizedAgentSystem):
    name = "scout"
    system_prompt = "Explore widely, then reconcile conflicting findings."
    worker_count = 3
    debate_rounds = 1         # clamped to 0..3
```

### `HybridAgentSystem` — hierarchy + lateral review

Orchestrator decomposition and validation, followed by peer review rounds, then
synthesis. Highest coordination cost (515% overhead in the paper). Reserve it for
high-value tasks that need both structure and cross-checking.

```python
class DeepReview(HybridAgentSystem):
    name = "deep-review"
    worker_count = 3
    debate_rounds = 1
```

### `AdaptiveAgentSystem` — select at run time

Supply a task profile in `request.metadata["task_profile"]` (or in the agent
config). Without a profile it stays on the single-agent default.

```python
class Router(AdaptiveAgentSystem):
    name = "router"
    system_prompt = "Answer the task using the selected coordination pattern."

router = Router(runtime, task_profile={
    "decomposability": 0.8,
    "sequential_dependencies": 0.1,
    "tool_count": 5,
    "single_agent_baseline": 0.35,
})
```

```json
{"message": "Compare the three plans", "task_profile": {
  "decomposability": 0.8,
  "sequential_dependencies": 0.1,
  "tool_count": 5,
  "single_agent_baseline": 0.35
}}
```

`recommend_architecture()` can also be called directly:

```python
from vira.agent import TaskProfile, recommend_architecture

rec = recommend_architecture(TaskProfile(
    decomposability=0.7,
    sequential_dependencies=0.2,
    tool_count=5,
    single_agent_baseline=0.35,
))
print(rec.architecture, rec.confidence, rec.reasons, rec.warnings)
```

## Selection rules

The implementation applies the paper's rules in this order:

1. **Sequential or non-decomposable** (`sequential_dependencies ≥ 0.6` or
   `decomposability ≤ 0.35`) → `single`.
2. **Tool-heavy** (`tool_count ≥ 12`) → `decentralized`.
3. **Capability ceiling** (`single_agent_baseline ≥ 0.45`) → `single`.
4. **Dynamic environment** with decomposable work → `decentralized`.
5. **Needs peer review** with decomposable work → `hybrid`.
6. **Decomposable analysis** (`decomposability ≥ 0.55`) → `centralized`.
7. Otherwise → `single` (conservative fallback).

Profiles are clamped to `[0, 1]`, and worker/round limits are bounded so a
misconfiguration cannot fan out without limit.

## API

Authenticated clients can inspect the catalog and ask for a recommendation:

```bash
curl -s http://localhost:8000/api/v1/agent-architectures \
  -H "Authorization: Bearer <session>"
```

```bash
curl -s -X POST http://localhost:8000/api/v1/agent-architectures/recommend \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"decomposability": 0.8, "sequential_dependencies": 0.1,
       "tool_count": 5, "single_agent_baseline": 0.35}'
```

The response includes the chosen topology, confidence, reasons, warnings and the
measured coordination profile.

## Configuration

Register an architecture class exactly like any other agent:

```yaml
agents:
  - name: Analyst
    module: my_package.agents
    class: Analyst
    enabled: true
    config:
      worker_count: 3
      max_subtasks: 3
      debate_rounds: 1
      validate_outputs: true
      max_seconds: 240
      tools:
        allow: ["knowledge_search", "database_query"]
```

Useful config keys:

| Key | Default | Meaning |
|---|---|---|
| `worker_count` | `3` | Parallel workers/peers, clamped to 1–8. |
| `max_subtasks` | `worker_count` | Maximum planner subtasks. |
| `debate_rounds` | `1` | Peer-review rounds, clamped to 0–3. |
| `validate_outputs` | `true` | Centralized/hybrid validation pass. |
| `architecture_timeout` | `max_seconds` | Per-LLM-call timeout. |
| `worker_max_tokens` | derived | Optional explicit worker token budget. |
| `worker_prompt` / `synthesis_prompt` / `orchestrator_prompt` / `validation_prompt` / `debate_prompt` | built in | Override prompt templates. |

The worker budget is derived from the agent's `max_tokens` so the total
multi-agent budget stays close to the single-agent budget.

## Observability and safety

Each run records `architecture` and a `coordination` block in `TaskResult.data`:

```json
{
  "architecture": "centralized",
  "coordination": {
    "workers": 3,
    "rounds": 1,
    "subtasks": ["revenue", "costs", "risks"],
    "validated": true,
    "corrections": 1,
    "llm_calls": 8,
    "profile": {"overhead_pct": 285, "error_amplification": 4.4}
  }
}
```

Timeline events (`architecture.start`, `architecture.plan`,
`architecture.llm`, `architecture.debate`) appear in the run trace.
`AgentMetadata.architecture` and `BaseAgent.describe()` expose the chosen
topology to the registry and dashboard.

Guidelines:

- Start with `SingleAgent`. Only move up when the task profile justifies it.
- Do not use multi-agent coordination for sequential planning or a small
  tool count with a strong single-agent baseline.
- Treat `IndependentAgentSystem` as an ensemble, not an accuracy guarantee.
- Keep `worker_count`, `debate_rounds` and `max_seconds` small on local models.
- The multi-agent classes do not add tool loops to workers by default. Override
  `_llm` or `_run_workers` if you need tool-using workers; remember the paper's
  tool-coordination trade-off.
