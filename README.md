<div align="center">

# VIRA

**A local-first AI server and extensible agent platform for your devices, tools and knowledge.**

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](#license)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#quick-start)
[![Server: Docker](https://img.shields.io/badge/server-Docker-blue.svg)](#quick-start)
[![Model: ornith-1.5:9b](https://img.shields.io/badge/default%20model-ornith--1.5%3A9b-green.svg)](#the-default-model)

[Quick start](#quick-start) · [Docs](#documentation) · [Contributing](#contributing)

</div>

VIRA gives you a control center, a chat workspace, persistent memory, permissioned
tools, retrieval-augmented knowledge, durable workflows, and specialist agents that
can work on real tasks. The server runs once as a Linux container on Linux, macOS or
Windows; VIRA Link can be installed on phones and desktops to collect consented
device signals. Ollama is the default provider; cloud models are optional.

VIRA is the platform underneath your own agents: it handles conversations, device
events, memory, retrieval, permissions, tool execution, workflow persistence and
observability, so you can focus on agent logic.

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

[![VIRA Server and VIRA Link client](docs/VIRA_server_client.svg)](docs/VIRA_server_client.svg)

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
account. Full install options and safety notes: **[docs/INSTALL.md](docs/INSTALL.md)**.

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
instructions: **[docs/DOCKER.md](docs/DOCKER.md)**.

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

ollama pull ornith-1.5:9b
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

VIRA ships with **`ornith-1.5:9b`** through Ollama. This is the framework's final
default model choice, and the agents and prompts are tuned around it.

```bash
ollama pull ornith-1.5:9b
```

You can still use other Ollama models, OpenAI or Anthropic. Change
`llm.default_model` and the `llm.models` list in `config.yaml`.

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

See [docs/MULTI_DEVICE_IMPLEMENTATION.md](docs/MULTI_DEVICE_IMPLEMENTATION.md) for the
current status and [VIRA_MULTI_DEVICE_DESIGN.md](VIRA_MULTI_DEVICE_DESIGN.md) for the
design.

### Device companion: VIRA Link

`client/` is **VIRA Link**, a modular Flutter client for Android, iOS, the web,
Linux and Windows. It signs in as a VIRA user, enrolls the device, captures only
the signals you enable, stores every event in a local outbox, and sends bounded
batches to the server when it is reachable. Offline capture keeps working; the
queue drains automatically on reconnect.

```bash
cd client
flutter pub get
flutter run -d chrome       # or android, linux
```

See [client/README.md](client/README.md) for the module layout and API contract.

---

[![VIRA system architecture](docs/VIRA_architecture.svg)](docs/VIRA_architecture.svg)

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
vira/tools/                 registry, built-ins, MCP server, web tools
vira/api/                   FastAPI app and route modules
vira/auth/  vira/devices/   users, sessions, credentials, access grants
vira/web/static/            dashboard and chat pages
client/                     VIRA Link device companion (Flutter)
config.yaml                 runtime configuration
run.py                      start VIRA
Dockerfile / compose*.yaml  production server and Ollama deployment
docs/DOCKER.md              server/client install and operations guide
```

## Documentation

- [docs/VIRA_DOCS.md](docs/VIRA_DOCS.md) — framework reference and config
- [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) — design and persistence
- [docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md)
- [docs/TOOL_SEARCH.md](docs/TOOL_SEARCH.md) — tool catalog, relevance ranking and prompt budgeting
- [docs/PLUGIN_SDK.md](docs/PLUGIN_SDK.md) — plugin manifest, permissions and extension API
- [docs/P4_ECOSYSTEM.md](docs/P4_ECOSYSTEM.md) — marketplace, organizations, storage, quotas and scale-out
- [docs/MULTI_DEVICE_IMPLEMENTATION.md](docs/MULTI_DEVICE_IMPLEMENTATION.md) and
  [VIRA_MULTI_DEVICE_DESIGN.md](VIRA_MULTI_DEVICE_DESIGN.md)
- [docs/INSTALL.md](docs/INSTALL.md) — one-command Linux/macOS/Windows installer
- [docs/VIRA_server_client.svg](docs/VIRA_server_client.svg) — server vs client overview
- [docs/DOCKER.md](docs/DOCKER.md) — server/client installation, Docker, Ollama, GPU and operations
- [docs/VIRA_architecture.svg](docs/VIRA_architecture.svg) — complete system architecture diagram

---

## Configuration and security

`config.yaml` controls the provider, agents, sensors, tools and devices.
The dashboard can edit it and reload the runtime.

Before exposing VIRA beyond localhost: set a random `auth.secret_key`, enable
`auth.https_only` behind TLS, review tool permissions, and keep port 8000 behind a
reverse proxy.

The Bubblewrap sandbox is for development workloads, not hostile code. Use a
container or VM for a stronger boundary.

---

## Development status

This is a real system with rough edges, not a finished product. Linux is the primary
platform. APIs and config keys can still move.

Working: kernel, sensors, events, state, metrics, authenticated dashboard, chat,
memory, runs, agent lifecycle, local/MCP tools with permissions and auditing,
and multi-user accounts and devices.

Still open: better memory retrieval, run recovery, OS-native sensing, stronger
isolation, generated agents/tools with approval gates, and Windows/macOS packaging.

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
