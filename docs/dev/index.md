# VIRA Developer Manual

This manual is for people who **build, extend or operate VIRA from source**.

## Start here

- [Contributing](contributing.md) — workflow, coding standards and docs rules
- [Architecture overview](architecture/framework.md) — kernel, events, agents, sensors
- [System design](architecture/system-design.md) — requirements, persistence and boundaries
- [Agent design](architecture/agent-design.md) — agent loop and sub-agents
- [Tool search](architecture/tool-search.md) — relevance ranking and prompt budgeting

## Extend VIRA

- [Plugin SDK](plugin-sdk.md) — manifest, lifecycle, permissions and extension points
- [Server roadmap](roadmap/server.md) — priorities from P0 to P5
- [Client roadmap](roadmap/client.md) — VIRA Link delivery plan
- [Agent roadmap](roadmap/agents.md) — prerequisites and the five daily-use agents

## Design documents

- [Client system design](designs/client-system-design.md)
- [Multi-device design](designs/multi-device-design.md)
- [Multi-device implementation notes](designs/multi-device-implementation.md)
- [P4 ecosystem and scale](designs/p4-ecosystem.md)
- [Wayland sensor design](designs/wayland-sensor.md)

## Reference

- [HTTP API reference](../reference/api.md)
- [Event reference](../reference/events.md)
- [Configuration reference](../reference/configuration.md)

## Repository map

| Path | Purpose |
|---|---|
| `vira/` | Python kernel, agents, tools, sensors, API, storage |
| `vira/kernel/` | Event bus, dispatcher, scheduler, state, config, security |
| `vira/api/` | FastAPI application and route modules |
| `vira/agent/` | Agent loop, tool-call parsing, lessons, sub-agent definitions |
| `vira/plugins/` | Plugin discovery and SDK runtime |
| `client/` | Flutter VIRA Link application |
| `scripts/` | Installers, backup and restore helpers |
| `docs/` | This documentation site |

## Local development loop

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The server starts on <http://localhost:8000>. API docs are available live at
`/docs` and `/redoc`.

To preview this documentation site locally:

```bash
./scripts/docs.sh serve
```

The script creates a project-local `.venv` with the docs toolchain, so it does
not depend on a system-wide `mkdocs`. Open <http://127.0.0.1:8001>. Use
`./scripts/docs.sh build` for a strict build and `./scripts/docs.sh pdf` for both
PDF manuals.
