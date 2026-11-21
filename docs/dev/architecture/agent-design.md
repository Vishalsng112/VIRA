# VIRA agent design (v2)

Agent code is split into three layers.  Developers should only need the top
layer for most agents and the middle layer for LLM/tool agents.

| Layer | File | Responsibility |
|---|---|---|
| `BaseAgent` | `vira/agent/base.py` | lifecycle, task contract, per-task identity, tool/memory/knowledge/progress/response helpers, safe concurrency |
| `LLMAgent` | `vira/agent/llm_agent.py` | prompt construction, tool selection, multi-step loop, retry, specialist delegation, lesson learning |
| `ChatAgent` | `vira/agent/Agents/chat_agent.py` | chat event mapping, conversation history, `agent.response` emission |

Supporting pieces:

| Piece | File | What it does |
|---|---|---|
| Agent loop | `vira/agent/loop.py` | think -> one tool call -> observe -> repeat, with a step budget, repeat/unknown-tool guards, errors fed back for self-correction, forced final answer, context compaction. Any permitted tool can now be called by name even if it was not in the small prompt selection |
| Tool policy + discovery | `vira/agent/toolbox.py` | allow/deny/pinned globs, local **and** qualified MCP tools, catalog selection, correct permission action per tool |
| Tolerant parsing | `vira/agent/toolcalls.py` | accepts fenced/quoted/trailing-comma JSON and common key variants, so 3B-8B models rarely break the protocol |
| Sub-agents | `vira/agent/definitions/*.md` | one markdown file per specialist (frontmatter: name, description, tools, max_steps). Delegation runs a fresh, small context |
| Self-improvement | `vira/agent/lessons.py` | failed/recovered tool calls become per-user `lesson` memories, recalled into the next prompt. No extra LLM call |

## Write a task agent

```python
from vira.agent import BaseAgent


class InboxAgent(BaseAgent):
    name = "inbox"
    role = "inbox"                 # stable knowledge scope, not the runtime id

    async def setup(self):
        self._seen = set()

    async def execute(self, request):
        # request.message / request.input / request.user_id / request.run_id
        self.emit_progress("status", label="Reading inbox")
        items = await self.call_tool("database_query", query="select * from ...")
        return {"response": f"found {len(items)} items"}
```

`run_task`/`handle` normalise the return value into a `TaskResult`, attach
identity in context variables (so concurrent users never leak into each other)
and run the error hook on failure.

## Chat-facing agents

`ConversationalAgent` owns the `user.message` -> `agent.response` protocol,
history fallback and routing. Subclass it for a chat-selectable specialist:

```python
class MyChatAgent(ConversationalAgent):
    role = "my-specialist"
    is_default_agent = False       # only answers an explicit agent_id
    default_system_prompt = "..."
```

The API includes `agent_id` in the event and validates it; without a target,
only the default `ChatAgent` answers. This prevents duplicate replies when
several chat agents are registered.

## Shipped agent

| Agent | Selection | Purpose |
|---|---|---|
| `ChatAgent` | default, `agent_id: chatbot` | general assistant |

Everything else is an extension point: create a `BaseAgent`/`LLMAgent`/
`ConversationalAgent` subclass and register it in `config.yaml`. Tools are
general capabilities granted through `tools.allow`; there are no per-agent
private tools.

### Workspaces and host tools

The durable unit is a user-visible **workspace**; agent sandboxes attach to it.
All agents for a user share the default workspace, and several agents can attach
to the same project without sharing a process namespace. A chat request may pass
`workspace: "<name-or-absolute-path>"`, which is injected into every `sandbox`
tool call for that run.

Host-installed tools are available in two ways:

* `workspace.default_execution_mode: host` (or per-workspace `execution_mode`)
  runs commands in the workspace with the host `PATH`;
* `sandbox.readonly_mounts` + `sandbox.extra_path` keep bubblewrap isolation and
  expose host tool directories read-only.

See `docs/dev/designs/workspaces.md`.


## Write an LLM agent

```python
from vira.agent import LLMAgent


class Researcher(LLMAgent):
    role = "researcher"

    def __init__(self, runtime, **config):
        config.setdefault("system_prompt", "Research carefully and cite sources.")
        config.setdefault("tools", {"allow": ["web", "web_*", "rag_search"]})
        super().__init__(runtime, **config)
```

Set `delegation: true` to expose markdown specialists as a `delegate` tool.

## Helpers available on every agent

| Helper | Purpose |
|---|---|
| `call_llm` / `ask_llm` | LLM call with task identity and usage accounting |
| `call_tool` | Execute a tool with the declared permission action; injects the caller for local tools and only declared args for MCP tools |
| `recall` / `remember` | Episodic memory |
| `knowledge_search` / `knowledge_write` | Scoped knowledge base |
| `emit_progress` | Streaming + durable run timeline |
| `respond` | Emit the agent's response event to the requesting user |
| `send_event` | Message another agent |

## Rules

* There is exactly one shipped chat agent: `ChatAgent`, connected to the chat
  webpage. Every other agent is written by extending `BaseAgent` (or `LLMAgent`)
  and registering it in `config.yaml`.
* `execute` is the single required method. `initialize` rejects a class that does
  not implement it, so a half-written agent fails at startup instead of silently
  doing nothing.
* Choose a coordination topology from `vira/agent/architectures.py`:
  `SingleAgent` (default), `IndependentAgentSystem`, `CentralizedAgentSystem`,
  `DecentralizedAgentSystem`, `HybridAgentSystem` or `AdaptiveAgentSystem`.
  The selection rules and the evidence behind them are in
  [Agent architectures](agent-architectures.md).
* There is one `BaseAgent` implementation. The old orchestration copy and the
  example/sensor agents were removed; scheduler, router, workflows and plugins
  all use `vira.agent.base.BaseAgent`.
* `ChatAgent` keeps its public config (`tools.allow/deny/pinned`,
  `tool_timeouts`, `delegation`, `history_limit`) and its `user.message` ->
  `agent.response` contract.

Tuning for small contexts: lower `max_prompt_chars`, `max_tool_chars`,
`max_steps` in `config.yaml`.
