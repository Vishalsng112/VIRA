# VIRA agent design (v2)

Claude-style agents, built for small local models.

| Piece | File | What it does |
|---|---|---|
| Agent loop | `vira/agent/loop.py` | think -> one tool call -> observe -> repeat, with a step budget, repeat/unknown-tool guards, errors fed back for self-correction, forced final answer, context compaction |
| Tolerant parsing | `vira/agent/toolcalls.py` | accepts fenced/quoted/trailing-comma JSON and common key variants, so 3B-8B models rarely break the protocol |
| Sub-agents | `vira/agent/definitions/*.md` | one markdown file per specialist (frontmatter: name, description, tools, max_steps). The chat agent gets a `delegate(agent, task)` tool; the sub-agent runs in a fresh small context with only its allowed tools |
| Self-improvement | `vira/agent/lessons.py` | failed/recovered tool calls become per-user `lesson` memories, recalled into the next prompt. No extra LLM call |
| Chat agent | `vira/agent/Agents/chat_agent.py` | recall lessons -> loop (+delegation) -> learn -> reply |
| Autonomous agent | `vira/agent/Agents/autonomus_agent.py` | unchanged statistical detector; `llm_triage: true` adds severity + explanation from the local LLM |

Add your own sub-agent: drop `my_agent.md` in `vira/agent/definitions/` or in `definitions_dir` (config). Tuning for small contexts: lower `max_prompt_chars`, `max_tool_chars`, `max_steps` in `config.yaml`.
