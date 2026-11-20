# Contributing to VIRA

Thank you for helping build VIRA. Contributions are open to everyone: code,
tests, docs, examples, bug reports and design review.

VIRA is modular. You can improve one sensor, one agent, one plugin or one page
without understanding the whole runtime.

---

## Quick start

Requirements: Python 3.11+, Git, and either Ollama (recommended) or an
OpenAI/Anthropic key. Docker is only needed for the container path.

Source install:

```bash
git clone https://github.com/Vishalsng112/VIRA.git
cd VIRA

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

ollama pull ornith-1.5:9b
python3 run.py
```

Open <http://localhost:8000>; the first visit creates the administrator.
For Docker, GPU, native Ollama and Windows/Mac instructions, follow
[docs/user/getting-started.md](docs/user/getting-started.md).

Before your first chat:

```bash
python3 -m vira doctor
```

---

## VIRA in plain language

VIRA has four layers:

1. **Server** — FastAPI, dashboard/chat, SQLite/PostgreSQL, auth, devices,
   storage, jobs and the operator UI.
2. **Kernel** — an event bus, dispatcher, scheduler, state and metrics. Sensors
   and devices publish events; agents and background jobs subscribe.
3. **Agent runtime** — a bounded reasoning loop that can call permissioned tools,
   use memory/RAG, delegate to specialists and ask for approval before
   destructive actions.
4. **VIRA Link** — the Flutter device companion that captures consent-gated
   signals, stores them in an offline outbox and syncs to the server.

Useful mental model:

```text
device/sensor -> validated event -> stored fact -> agent context -> tool call -> answer
```

The server is the policy authority. Clients propose or capture; the server
enforces consent, access, retention and approval.

---

## Repository map

| Path | What lives there |
|---|---|
| `vira/api/` | FastAPI app and route modules |
| `vira/kernel/` | event bus, dispatcher, scheduler, state, security |
| `vira/agent/` | agent loop, definitions, lessons, examples |
| `vira/agent_runtime/`, `vira/agent_orchestration/` | runtime, runs, workflows |
| `vira/memory/`, `vira/rag/`, `vira/insights/` | memory ranking, RAG, device insights |
| `vira/tools/` | tool registry, built-ins, MCP, sandbox, database tools |
| `vira/security/` | approvals and redaction |
| `vira/generated/` | approval-gated generated tools/agents |
| `vira/evaluation/` | deterministic platform evaluation |
| `vira/web/static/` | dashboard, chat, auth UI |
| `client/` | VIRA Link (Flutter) |
| `examples/plugins/`, `examples/mcp/` | copyable extension examples |
| `docs/` | user manual, developer manual, reference |
| `scripts/` | installers, demo, doctor, benchmarks, evaluation, release tools |

---

## Your first change in 15 minutes

Start with the curated [good first issues](docs/dev/good-first-issues.md). A good
first task has one outcome, one or two files and a runnable check.

A reliable pattern:

1. Reproduce or read the target code.
2. Add or update a focused test.
3. Make the smallest change.
4. Run the focused test, then the relevant suite.
5. Update docs if behaviour, config, an API route or an extension point changed.

Example focused run:

```bash
python3 -m unittest vira.tests.test_security_phase3 -v
cd client && flutter test
```

---

## Testing

| What | Command |
|---|---|
| Full server suite | `python3 -m unittest $(ls vira/tests/test_*.py \| sed 's#/#.#g; s#\\.py$##')` |
| Tool-use benchmark | `python3 scripts/benchmark.py --offline` |
| Agent platform evaluation | `python3 scripts/evaluate.py` |
| Doctor | `python3 -m vira doctor --no-docker` |
| Client analyze/test | `cd client && flutter analyze && flutter test` |
| Docs strict build | `./scripts/docs.sh build` |

Some tests need no model or network by design. Keep new tests deterministic and
offline unless they are explicitly live benchmarks.

Known environment note: `test_load_monitor` can fail on some hosts when the
memory store is unavailable; state that in the PR rather than hiding it.

---

## Extension examples

Three complete plugin/MCP examples are maintained and tested:

- [`examples/plugins/hello_world`](examples/plugins/hello_world) — tool, route,
  state.
- [`examples/plugins/reading_list`](examples/plugins/reading_list) — read/write
  tools, route, state and a prompt specialist.
- [`examples/plugins/focus_budget`](examples/plugins/focus_budget) — event
  subscription, scheduled work, tool and route.
- [`examples/mcp/notes_server.py`](examples/mcp/notes_server.py) — a real MCP
  stdio server with a client handshake test.

Run them with:

```bash
python3 -m unittest vira.tests.test_examples -v
```

Plugin SDK: [docs/dev/plugin-sdk.md](docs/dev/plugin-sdk.md).

---

## Adding an agent

Prompt-defined specialists are the cheapest and safest extension:

```markdown
---
name: reading_coach
description: Use when the user asks what to read next.
tools: [reading_list]
max_steps: 3
---
You are VIRA's reading coach. Use reading_list before answering and never invent
entries.
```

Drop the file in `vira/agent/definitions/` or a plugin-provided definition.
Runtime agents subclass `BaseAgent` and implement `think`, `plan`, `act` and
`reflect`; see [docs/dev/agent-platform.md](docs/dev/agent-platform.md).

---

## Adding a sensor

1. Add `vira/sensors/my_sensor.py`, subclassing `BaseSensor`.
2. Publish through the validated dispatcher, not the event bus.
3. Use a `domain.entity.action` event name.
4. Add a factory registration and a `config.yaml` entry.
5. Add a unit test with a fake source.

See [docs/dev/architecture/framework.md](docs/dev/architecture/framework.md).

---

## Event naming rules

All events use **`domain.entity.action`**:

| Pattern | Example | Valid |
|---|---|---|
| Three-part lowercase namespace | `sensor.battery.state` | Yes |
| Agent result | `agent.my_agent.result` | Yes |
| No namespace | `batterysensor` | No |
| CamelCase | `BatteryEvent` | No |

Reserved prefixes: `kernel.*`, `agent.registered`, `agent.unregistered`,
`workflow.*`.

---

## Pull request checklist

- [ ] The change has a focused test or a documented reason it cannot.
- [ ] I ran the relevant tests and pasted the result.
- [ ] New events follow `domain.entity.action`.
- [ ] New tools declare the smallest permission set and redact secrets.
- [ ] New config keys are documented.
- [ ] Public behaviour/API/plugin changes update `docs/`.
- [ ] New docs pages are added to `mkdocs.yml` nav.
- [ ] I updated `CHANGELOG.md` under `Unreleased` for user-visible changes.
- [ ] Architecture/product changes link a [decision log](docs/dev/decision-log.md)
      entry or proposal.
- [ ] No credentials, real device data, session transcripts or generated docs
      are committed.

---

## Review, cadence and response targets

- Weekly roadmap review; monthly metrics/release review.
- Releases target the **first Tuesday of each month**; see
  [release process](docs/dev/releases.md).
- Security reports: private triage within **2 business days**.
- Bugs/install failures: initial response within **3 business days**.
- Good first issues/features: initial response within **5 business days**.

These are targets, not contractual SLAs.

---

## Community standards

Be respectful, assume good intent and critique the change, not the person. The
[Code of Conduct](CODE_OF_CONDUCT.md) applies in issues, pull requests,
discussions and any project space.

---

## Getting help

- Open a bug/feature issue using the templates.
- Ask in Discussions for open-ended questions.
- For security issues use private reporting from `SECURITY.md`, never a public
  issue.
- Not sure an idea fits? Open a short issue before investing time.
