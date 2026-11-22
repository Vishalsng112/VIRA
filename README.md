<div align="center">

# VIRA

**A self-hosted, local-first context and tool server for AI agents.**

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](#license)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#quick-start)
[![Server: Docker](https://img.shields.io/badge/server-Docker-blue.svg)](#quick-start)
[![Model: qwen3.5:9b](https://img.shields.io/badge/default%20model-qwen3.5%3A9b-green.svg)](#the-default-model)

[Quick start](#quick-start) · [Five-minute proof](#see-it-working) · [Product roadmap](ROADMAP.md) · [Security](docs/user/security.md) · [Docs](#documentation)

</div>

VIRA gives AI agents private access to your devices, memory, data and MCP tools.
It runs on your own hardware, keeps permissions and audit in your hands, and ships
a dashboard, chat workspace, agent runtime and device companion. Ollama is the
default provider; cloud models are optional.

### What works today

- **Self-hosted server** with authenticated dashboard, chat, memory, agents,
  workflows, RAG, users, MCP tools and audit.
- **Device context** through VIRA Link on Android, iOS, web/PWA, Linux, Windows and
  macOS (Apple Silicon build), with per-collector consent and offline sync.
- **Agent tools** including web research, filesystem/shell with permissions, RAG,
  insights, MCP servers and read-only database queries.
- **Reviewable agent platform**: approval-gated generated tools/agents, tool and
  time budgets, run resume, redacted run timelines, memory feedback and
  per-user/agent cost quotas.
- **Reproducible evaluation**: deterministic tool-selection, task, memory,
  recovery and safety results recorded for every release.
- **Operational controls**: non-root, capability-dropped Docker deployment,
  field-level encryption for sensitive values, rate limits, approval gates for
  destructive tools, a Bubblewrap sandbox, a redacted audit export and a tested
  backup/restore drill.
- **Published releases** with Android, iOS (unsigned), web, Linux AppImage,
  Windows and macOS (unsigned, Apple Silicon) artifacts plus checksums.

### What is not built yet

- Verified AI-generated tools or agents. This remains research.
- Signed macOS/iOS store builds. The artifacts exist and are unsigned; signing
  needs your Apple credentials.
- OS notification scheduling. In-app reminders work; notification permission is
  requested only when scheduled notifications ship.
- A hosted SaaS version. VIRA is local-first.

See the **[product roadmap](ROADMAP.md)** for the maturity plan and acceptance
criteria.

### See it working

The fastest proof is the reproducible five-minute demo: sign in, ask about your
own devices, watch the agent call a database tool, and verify that write queries
are rejected.

```bash
cd ~/vira
VIRA_USERNAME="your-user" VIRA_PASSWORD="your-password" python3 scripts/demo.py
```

[![VIRA five-minute demo](docs/assets/demo.gif)](docs/assets/demo.mp4)

*Click the demo to watch the MP4. The terminal transcript is also in the
[five-minute proof guide](docs/user/demo.md).*

Full guide: **[Five-minute proof](docs/user/demo.md)**.

The one-command installer gets a local server running in minutes. The source
workflow remains available for development.

---

## Quick start

VIRA has two pieces:

- **VIRA Server** — the API, dashboard, chat, agents, tools, memory and scheduler.
  This is the part that runs as a Linux container and works on Linux, macOS and
  Windows through Docker.
- **VIRA Link** — the native device companion that collects usage, focus, battery
  and health signals. It connects to VIRA Server. You can use the dashboard and
  chat without installing VIRA Link.

[![VIRA Server and VIRA Link client](docs/assets/VIRA_server_client.svg)](docs/assets/VIRA_server_client.svg)

*VIRA Server is installed once — usually in Docker on a computer or NAS. VIRA Link
is installed only on devices whose signals you want to collect: phones, tablets
and desktops. The dashboard and chat open in any browser and do not require the
client.*

### One-command install (recommended)

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.ps1 | iex
```

The installer detects the OS, architecture, RAM, disk and GPU; installs/checks
Docker; chooses an Ollama model; downloads VIRA; starts the server and worker;
and pulls the model.

Open <http://localhost:8000> when it finishes. The first visit creates the admin
account. Full install options and safety notes: **[docs/user/install/one-command.md](docs/user/install/one-command.md)**.

### Manual Docker install

Requirements: Docker Engine or Docker Desktop with Compose v2, and about 8 GB RAM.

```bash
git clone https://github.com/Vishalsng112/VIRA.git
cd VIRA
cp .env.example .env

docker compose up -d --build
docker compose --profile setup run --rm model-pull
```

Open <http://localhost:8000>. The first visit creates the admin account.

This starts VIRA Server, the durable worker and a bundled Ollama service. Edit
`.env` if you want a different model, port or bind address. To use Ollama that is
already installed on the host — recommended on macOS for Metal acceleration — use:

```bash
docker compose -f compose.host-ollama.yaml up -d --build
```

Full install, server/client, native-Ollama, GPU, backup and troubleshooting
instructions: **[docs/user/install/docker.md](docs/user/install/docker.md)**.

### Run from source (development)

Requirements:

- Python 3.11+
- Git
- [Ollama](https://ollama.com/download)
- Bubblewrap (`bubblewrap`) if you want agent sandboxes

```bash
git clone https://github.com/Vishalsng112/VIRA.git
cd VIRA

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

ollama pull qwen3.5:9b
ollama serve                       # if it is not already running

python run.py
```

Open <http://localhost:8000>. The first visit creates the admin account.

Optional sandbox setup:

```bash
sudo apt-get install bubblewrap
sudo mkdir -p /AgentWorkspace
sudo chown "$USER":"$USER" /AgentWorkspace
```

For local HTTP, keep `auth.https_only: false` in `config.yaml`. Turn it on before
exposing VIRA through HTTPS or a trusted reverse proxy.

### PostgreSQL (optional)

SQLite remains the default. To use PostgreSQL, install `psycopg[binary]` and
start VIRA with:

```bash
VIRA_DATABASE_URL=postgresql://vira:password@localhost/vira python run.py
```

The schema is applied automatically (`vira/db/postgres_schema.sql`). Validate
the deployment against a real PostgreSQL instance before production use.

### Background worker

Retention, insight rollups and database backups run in a separate durable worker:

```bash
python -m vira.worker --once      # one batch
python -m vira.worker             # keep running
```

Jobs are stored in the database and survive restarts.

### Backups

```bash
scripts/backup.sh                 # data/backups/vira-<timestamp>.sqlite3
scripts/restore.sh <backup>       # stop the API and worker first
```

Sensitive config values and device event payloads are encrypted with a master
key at `data/.vira_master_key` (or `VIRA_MASTER_KEY`). Back up that key separately;
without it encrypted values cannot be recovered.

Request rate limits are enabled in `config.yaml` under `rate_limits`.


---

## The default model

VIRA ships with **`qwen3.5:9b`** through Ollama. This is the framework's final
default model choice, and the agents and prompts are tuned around it.

```bash
ollama pull qwen3.5:9b
```

You can still use other Ollama models, OpenAI or Anthropic. Change
`llm.default_model` and the `llm.models` list in `config.yaml`.

Local model tiers, by memory:

| RAM | Model | Tool reliability |
|---|---|---|
| 8–16 GB | `qwen3.5:9b` (default) | Good |
| 16–32 GB | `qwen2.5:14b` | Better |
| 32 GB+ | `qwen2.5:32b` | Best local |
| 4–8 GB | `llama3.2:3b` | Experimental |

Tool use may be unreliable below about 8 GB RAM or a 4B-parameter model. A
cloud provider is a supported fallback, and administrators can switch the active
Ollama model from the chat recovery panel after a failure.

Check the whole first-run path with the doctor:

```bash
python -m vira doctor
```

It checks Docker/Compose, Ollama, the selected model and context size, port
conflicts, the Chatbot agent, database writability and the master key, and prints
a fix for each problem. Full guidance: **[Choose a local model](docs/user/models.md)**.

The deterministic tool-use benchmark runs without a model; the live layer
measures a real one:

```bash
python3 scripts/benchmark.py --offline
VIRA_USERNAME=you VIRA_PASSWORD=... python3 scripts/benchmark.py --runs 10
```

Current results: 7/7 deterministic scenarios, and 39/40 live runs on the
recommended local model (device 10/10, database 10/10, RAG 9/10, web 10/10).
See the **[tool-use benchmark](docs/dev/benchmarks/tool-use.md)** and the
**[live result](docs/dev/benchmarks/tool-use-live.md)**.

---

## What you can do

### Chat and tools

The chat workspace keeps conversations and memory locally. The agent can use the
built-in tools: filesystem, shell, git, utility, web search/browse/research, and a
Bubblewrap-backed sandbox. Tool calls go through permissions and are audited.

### Web console

The server ships an Apple-inspired control center at `/dashboard` with grouped
navigation for workspace, intelligence, operations and system views. It covers
runtime health, devices, agents, extensions (plugins + MCP), knowledge/RAG,
durable automations, usage/cost and quotas, organizations, object storage,
security, updates, events, modules and configuration. Plugin/MCP install,
enable, reload, connect and delete actions work from the page.

The chat workspace at `/chat` has a conversation sidebar, search, agent picker,
live tool traces, a runtime context rail (status, tools, specialists), privacy
notes and light/dark themes. Sign-in, setup and password recovery share the same
design language.

### Operations

The dashboard exposes kernel health, modules, agents, tools, events, metrics and
configuration. You can inspect what the runtime is doing instead of guessing.

### Multi-user and multi-device

One VIRA server can serve several users and several endpoint devices. The server is
itself registered as a device, so local sensors use the same ingestion path as remote
clients. Device credentials are separate from user sessions, scoped, expiring and
revocable.

See [docs/dev/designs/multi-device-implementation.md](docs/dev/designs/multi-device-implementation.md) for the
current status and [docs/dev/designs/multi-device-design.md](docs/dev/designs/multi-device-design.md) for the
design.

### Device companion: VIRA Link

`client/` is **VIRA Link**, a modular Flutter client for Android, iOS, the web,
Linux, Windows and macOS (Apple Silicon). It signs in as a VIRA user, enrolls the
device, captures only the signals you enable, stores every event in a local
outbox, and sends bounded batches to the server when it is reachable. Offline
capture keeps working; the queue drains automatically on reconnect.

The macOS build is published unsigned as `vira_link.app`; right-click → **Open**
the first time or sign it locally. Intel Macs can use the web/PWA client; an Intel
desktop build is not part of the release matrix yet. See the
[platform capability matrix](docs/user/platforms.md) for the exact support story.

```bash
cd client
flutter pub get
flutter run -d chrome       # or android, ios, linux, windows, macos
```

See [client/README.md](client/README.md) for the module layout and API contract.

---

[![VIRA system architecture](docs/assets/VIRA_architecture.svg)](docs/assets/VIRA_architecture.svg)

---

## How it fits together

*The complete architecture diagram at the top of this README shows VIRA Link and
the web console at the edge, the authenticated API and device plane, the kernel
event runtime, the agent and workflow platform, local-first intelligence and
memory, tools and extensions, persistence domains, and deployment operations.*

```
intent -> conversation + memory -> agent reasoning -> permissioned tools -> result
```

The kernel and sensors provide state. Agents use that state and the tool registry.
Everything is exposed through the authenticated API and dashboard.

---

## Project layout

```text
vira/kernel/                event bus, dispatcher, state, scheduler, security
vira/sensors/               system, hardware, process, network, workspace, activity
vira/agent/                 BaseAgent, runtime loop, tool calls
vira/agent_orchestration/   registry, router, workflows
vira/llm/                   Ollama, OpenAI and Anthropic adapters
vira/memory/                conversations, scoped memory, context assembly
vira/tooling/               tool contract, catalog, policies, domain tool packs
vira/mcp/servers/           deployable domain MCP servers
vira/api/                   FastAPI app and route modules
vira/auth/  vira/devices/   users, sessions, credentials, access grants
vira/web/static/            dashboard and chat pages
client/                     VIRA Link device companion (Flutter)
config.yaml                 runtime configuration
run.py                      start VIRA
Dockerfile / compose*.yaml  production server and Ollama deployment
docs/                       documentation source (portal + manual + site config)
```

## Documentation

The documentation is built as a website and as PDF manuals from the Markdown in
`docs/`:

- **Website:** <https://vishalsng112.github.io/VIRA/>
- **User manual (PDF):** attached to each [release](https://github.com/Vishalsng112/VIRA/releases)
- **Developer manual (PDF):** attached to each [release](https://github.com/Vishalsng112/VIRA/releases)

Start with:

- [Getting started](docs/user/getting-started.md) — install and run VIRA
- [Five-minute proof](docs/user/demo.md) — see the agent, tools and database boundary work
- [Platform capability matrix](docs/user/platforms.md) — artifacts, collectors, signing and uninstall per platform
- [Choose a local model](docs/user/models.md) — tiers by RAM/GPU, cloud fallback and the tool-use warning
- [Tool-use benchmark](docs/dev/benchmarks/tool-use.md) — reproducible device, database, RAG and recovery results
- [Agent and tool platform](docs/dev/agent-platform.md) — generated artifacts, budgets, memory, run recovery and quotas
- [Agent platform evaluation](docs/dev/evaluations/agent-platform.md) — comparable tool selection, memory, safety and recovery results
- [Security overview](docs/user/security.md) — controls, evidence and limits
- [Threat model](docs/dev/security/threat-model.md) — assets, boundaries, threats and residual risk
- [Backup/restore drill](docs/dev/runbooks/backup-restore.md) — tested RPO/RTO evidence
- [Docker and deployment](docs/user/install/docker.md) — server/client, Ollama, GPU, operations
- [Product roadmap](ROADMAP.md) — maturity phases and acceptance criteria
- [Showcase](docs/user/showcase.md) — demo and deployment patterns
- [Changelog](CHANGELOG.md) — release notes in Keep-a-Changelog format
- [Release process](docs/dev/releases.md) — monthly cadence, checklist and response targets
- [Decision log](docs/dev/decision-log.md) — accepted product and architecture decisions
- [Developer manual](docs/dev/index.md) — architecture, plugin SDK and design docs
- [API reference](docs/reference/api.md) — generated from the FastAPI schema
- [Architecture diagram](docs/assets/VIRA_architecture.svg)
- [Contributing](CONTRIBUTING.md) — including how to build the docs locally
- [Good first issues](docs/dev/good-first-issues.md) — curated, current starter tasks
- [Code of Conduct](CODE_OF_CONDUCT.md) — community standards

Preview the docs locally (creates a project-local `.venv`, so the system
`mkdocs` is never used):

```bash
./scripts/docs.sh serve      # http://127.0.0.1:8001
./scripts/docs.sh build      # strict build
./scripts/docs.sh pdf        # both PDF manuals
```

---

## Configuration and security

`config.yaml` controls the provider, agents, sensors, tools and devices.
The dashboard can edit it and reload the runtime.

Before exposing VIRA beyond localhost: set a random `auth.secret_key`, enable
`auth.https_only` behind TLS, review tool permissions, and keep port 8000 behind a
reverse proxy. The default Compose file publishes port 8000 on `0.0.0.0`; set
`VIRA_BIND_ADDRESS=127.0.0.1` for local-only access.

The Bubblewrap sandbox is for development workloads, not hostile code. Use a
container or VM for a stronger boundary.

Read the full **[security and privacy overview](docs/user/security.md)** for
implemented controls, evidence commands and known limitations. The engineering
detail is in the **[threat model](docs/dev/security/threat-model.md)**, and the
latest **[backup/restore drill](docs/dev/runbooks/backup-restore.md)** records
RPO/RTO evidence. Report vulnerabilities through [SECURITY.md](SECURITY.md).

---

## Development status

VIRA is an early, actively developed system with rough edges. APIs, config keys
and UI details can still change.

Working: kernel, sensors, events, state, metrics, authenticated dashboard, chat,
memory, runs, agent lifecycle, local/MCP tools with permissions and auditing,
multi-user accounts and devices, Docker deployment on Linux/macOS/Windows, and
VIRA Link on Android, iOS, web/PWA, Linux, Windows and macOS (Apple Silicon).

Still open: signed Apple store builds, OS notification scheduling, stronger
isolation, verified (not just approved) generated artifacts, broader evaluation
datasets and deeper long-term memory research.
The [product roadmap](ROADMAP.md) defines the phases and acceptance criteria.

## How to give feedback

Feedback is most useful when it is based on the current release or `main` and
includes evidence:

- VIRA version or commit, installation method and OS;
- what you expected, what happened and the exact steps;
- relevant logs or screenshots with secrets, tokens and personal data removed;
- whether the Chatbot agent and a model were available.

Open a GitHub issue with that context. For security problems, use
[SECURITY.md](SECURITY.md) instead of a public issue.

Response targets: security reports are triaged privately within 2 business days,
bugs/install failures within 3 business days, and good first issues/features
within 5 business days. Releases target the first Tuesday of each month. These
are targets, not contractual SLAs. Community standards are in
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Contributing

Issues and pull requests are welcome. You do not need to understand the whole runtime
to improve one part of it. Start with [CONTRIBUTING.md](CONTRIBUTING.md), or pick a
[`good first issue`](https://github.com/Vishalsng112/VIRA/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

```bash
python -m pytest vira/tests
```

---

## License

MIT. See [LICENSE](LICENSE).
