# VIRA Swarm - autonomous persona agents

One script (`vira/agent/Agents/persona_agent.py`) -> N independent agents. Each agent runs its own
asyncio life-loop, announces itself with heartbeats (so it always knows how many peers are alive),
talks to peers over the agent message bus (`swarm.message`, directed or broadcast), extracts facts it
learned, and every `reflect_every` turns **evolves**: traits shift (bounded +-0.05), a new skill may be
gained, its self-description is rewritten and `generation` increments. State persists in `data/swarm/`.

Dashboard: `http://<host>:8000/swarm` (admin login) - conversation, learning, evolution, system feeds,
per-agent cards (traits, knowledge, skills), trait/knowledge charts, trust matrix, topic injection.

Configure in `config.yaml` (`agents:` -> `swarm: {count: N, personas: [...]}`); personas live in
`vira/swarm/personas.py` (cricketer, actor, politician, scientist, musician, chef, entrepreneur, philosopher).

Try it without the rest of VIRA:  `python -m vira.swarm.demo --mock`  (offline fake LLM)
or `python -m vira.swarm.demo` (uses the first model in `config.yaml`, e.g. Ollama) -> http://127.0.0.1:8765/

Local-model tips: keep `llm_concurrency: 1`, raise `speak_interval` if replies queue up.
