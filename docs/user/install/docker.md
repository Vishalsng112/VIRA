# Running VIRA with Docker

This is the supported cross-platform way to run **VIRA Server**. The server runs
as a Linux container on Linux, macOS or Windows. The **VIRA Link** client remains
a native app so it can reach the device sensors.

## First: Server vs client

| Piece | What it is | Where it runs |
|---|---|---|
| **VIRA Server** | API, web dashboard, chat workspace, agents, tools, memory, database, scheduler, admin | Docker container (Linux) |
| **Ollama** | Local model HTTP service | Docker container or native host service |
| **VIRA Link** | Device companion: collectors, offline ledgers, sync, command polling | Native app on each phone/desktop, or its web build |
| **Web console** | Browser UI served by VIRA Server (`/dashboard`, `/chat`) | Browser; no separate install |

The browser UI is part of the server. VIRA Link is the client that produces
device telemetry. You do **not** need VIRA Link to use the dashboard or chat.

## Recommended installation: Compose + bundled Ollama

### Requirements

- Docker Engine or Docker Desktop
- Docker Compose v2+
- About 6–10 GB free disk for models and images
- 8 GB RAM minimum; 16 GB+ recommended for larger local models

### 1. Get the code

```bash
git clone https://github.com/Vishalsng112/VIRA.git
cd VIRA
cp .env.example .env
```

Edit `.env` if needed:

```dotenv
VIRA_BIND_ADDRESS=0.0.0.0
VIRA_PORT=8000
VIRA_OLLAMA_MODEL=qwen3.5:9b
```

- `VIRA_BIND_ADDRESS=127.0.0.1` exposes the server only on this machine.
- `VIRA_BIND_ADDRESS=0.0.0.0` allows other devices on your LAN to connect.
- `VIRA_OLLAMA_MODEL` must match an Ollama model you pull. The repository
  default is `qwen3.5:9b`. If that model is not available from your Ollama
  registry, use any capable model, for example `llama3.2:3b`, in both
  `VIRA_OLLAMA_MODEL` and `ollama pull`.

### 2. Start the server and Ollama

```bash
docker compose up -d --build
# convenience wrapper: ./docker_run.sh
```

This starts:

- `vira-server` — API + web console on port `8000`
- `vira-worker` — durable jobs, retention, rollups, backups
- `vira-ollama` — Ollama on an internal Docker network (not exposed to the host)

### 3. Pull the model

```bash
docker compose --profile setup run --rm model-pull
```

Or pull a different model manually after editing `VIRA_OLLAMA_MODEL`:

```bash
docker compose exec ollama ollama pull qwen3.5:9b
```

### 4. Open VIRA

```text
http://localhost:8000
```

The first visit creates the administrator account. Then:

- use `/dashboard` for the control center
- use `/chat` for the chat workspace
- open the server URL from another device using the host's LAN address, for example
  `http://192.168.1.20:8000`

### 5. Connect VIRA Link

Install/open VIRA Link and enter:

```text
Server URL: http://<server-LAN-IP>:8000
```

Do not use `http://localhost:8000` inside a phone or another computer; that
points at the client device itself.

## Ollama connectivity modes

Ollama is just an HTTP service. VIRA Server reads its endpoint from
`VIRA_OLLAMA_URL`:

| Mode | URL | Best for |
|---|---|---|
| Bundled Ollama container | `http://ollama:11434` | Simplest, CPU-only, Linux/NVIDIA |
| Native Ollama on the host | `http://host.docker.internal:11434` | macOS Metal, existing installs, fastest host GPU |
| Remote GPU server | `https://ollama.example.internal` | Teams, shared GPU machine |

The default `compose.yaml` uses the bundled container.

### Native Ollama on macOS / Windows

Use the host-ollama Compose file:

```bash
docker compose -f compose.host-ollama.yaml up -d --build
```

It adds `host.docker.internal` automatically. Make sure the native Ollama service
accepts connections from Docker:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

On macOS with the Ollama app, set the variable for the app session and restart it:

```bash
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"
```

Only expose `11434` on trusted networks. Do not publish it to the internet.

### Existing native Ollama on Linux

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
docker compose -f compose.host-ollama.yaml up -d --build
```

Alternative for a local-only setup: `network_mode: host` on Linux, but that
reduces container isolation. Prefer `host.docker.internal` or the bundled network.

### Remote Ollama

```dotenv
VIRA_OLLAMA_URL=https://ollama.example.internal
```

Put the remote endpoint behind TLS, authentication or a VPN. VIRA Server should
not expose an unauthenticated model server to the public internet.

### NVIDIA GPU with bundled Ollama

Install the NVIDIA Container Toolkit, then:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
```

For Apple Silicon, prefer native Ollama: Docker Desktop runs Linux containers in
a VM and does not provide Metal acceleration to the Ollama container.

## Data and persistence

Named Docker volumes keep state across rebuilds:

```text
vira_vira-data       -> /app/data (database, master key, artifacts, plugins)
vira_ollama-models   -> /root/.ollama (model weights)
```

VIRA Server's important files:

```text
/app/data/vira.sqlite3          SQLite database
/app/data/.vira_master_key      encryption key for payloads/secrets
/app/data/objects/              local object storage
/app/data/checkpoints/          kernel state
/app/data/plugins/              plugin state/data
```

### Back up

```bash
mkdir -p backups
docker run --rm \
  -v vira_vira-data:/data \
  -v "$PWD/backups":/backup \
  alpine sh -c 'tar czf /backup/vira-data-$(date +%Y%m%d-%H%M%S).tgz -C /data .'
```

Also run the in-app backup job/settings if you use PostgreSQL or S3.

### Restore

```bash
docker compose down
docker run --rm \
  -v vira_vira-data:/data \
  -v "$PWD/backups":/backup \
  alpine sh -c 'cd /data && tar xzf /backup/vira-data-YYYYMMDD-HHMMSS.tgz'
docker compose up -d
```

The master key must be in the same backup. Without it, encrypted payloads cannot
be recovered.

### Reset everything (destructive)

```bash
docker compose down -v
```

This deletes the VIRA database, master key, objects and Ollama models.

## Upgrade

```bash
git pull
docker compose up -d --build
```

Database migrations run automatically on server startup. Back up first. Check:

```bash
docker compose ps
docker compose logs --tail=100 vira
```

## Configuration

The server reads `config.yaml` from the repository, mounted at
`/app/config.yaml`. You can edit it on the host, or through the dashboard
configuration page, then restart:

```bash
docker compose restart vira worker
```

If dashboard saves fail on Linux, the container user cannot write the host file.
Set `VIRA_UID` and `VIRA_GID` in `.env` to your host UID/GID and rebuild:

```bash
VIRA_UID=$(id -u) VIRA_GID=$(id -g) docker compose up -d --build
```

Environment overrides:

| Variable | Meaning |
|---|---|
| `VIRA_OLLAMA_URL` | Ollama endpoint used by chat and embeddings |
| `VIRA_OLLAMA_MODEL` | Model name override |
| `VIRA_BIND_ADDRESS` | Host bind address for port 8000 |
| `VIRA_PORT` | Host port |
| `VIRA_DATABASE_URL` | PostgreSQL URL instead of SQLite |
| `VIRA_MASTER_KEY` / `VIRA_MASTER_KEY_FILE` | encryption key override |

Before exposing the server beyond localhost:

- change `auth.secret_key`
- enable `auth.https_only` behind TLS
- use a reverse proxy (Caddy, Traefik, nginx)
- keep Ollama private
- review device consent, tool permissions and quotas
- back up the master key separately

## Container hardening and host sensing

The default Compose services already apply:

- non-root user (`VIRA_UID` / `VIRA_GID`);
- `no-new-privileges: true`;
- all Linux capabilities dropped;
- a read-only root filesystem;
- a small `noexec` `/tmp` tmpfs;
- process limits;
- no Docker socket mount and no `privileged` mode.

Runtime state lives on the `vira-data` volume. If you add a feature that writes
outside that volume, mount an explicit path instead of disabling the read-only
root filesystem.

Docker limits host sensing. The server container sees its own CPU, memory,
process, filesystem and network view, not the full host. App usage, focus,
battery and health signals come from **VIRA Link** on phones and desktops. See
the [security overview](../security.md#what-host-sensing-looks-like-inside-docker)
for the exact boundaries.

Verify the flags Compose will apply:

```bash
docker compose config | grep -E 'privileged|cap_drop|read_only|no-new-privileges|docker.sock'
```

## Developer workflow

### Run the working tree in the container

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
docker compose -f compose.yaml -f compose.dev.yaml logs -f vira
```

### Run tests in the container

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm vira python -m pytest -q
```

### Build only

```bash
docker build -t vira:latest .
# or
./docker_build.sh
```

### Open a shell

```bash
docker compose run --rm vira bash
```

### Rebuild after code changes

```bash
docker compose up -d --build vira worker
```

### Plugin development

Mount a plugin directory into the container and add it to `plugins.directories`
in `config.yaml`. The container already includes `examples/plugins`.

## Troubleshooting

### The server restarts immediately

```bash
docker compose logs --tail=120 vira
```

Common causes: config parse error, unreadable master key, database permission,
or a missing Python dependency after a code update (rebuild the image).

### `curl http://localhost:8000/livez` works but `/health` returns 401

`/livez` is the unauthenticated liveness probe. `/health` is an administrator
health endpoint and requires a session. This is intentional.

### Ollama connection refused

Check the endpoint from inside the VIRA container:

```bash
docker compose exec vira python -c "import urllib.request,os; print(urllib.request.urlopen(os.environ['VIRA_OLLAMA_URL']+'/api/tags').status)"
```

Check the bundled service:

```bash
docker compose exec ollama ollama list
```

If using native Ollama, make sure it is listening on `0.0.0.0:11434` and the
host-ollama compose file is in use.

### Model not found

```bash
docker compose exec ollama ollama pull qwen3.5:9b
```

Then set `VIRA_OLLAMA_MODEL` to the same name and restart `vira worker`.

### Port 8000 is already in use

```dotenv
VIRA_PORT=8080
```

Then `docker compose up -d`.

### VIRA Link cannot connect

Use the server machine's LAN IP, not `localhost`, and ensure the host firewall
allows port `8000`. If using Docker Desktop on macOS/Windows, the server container
is reachable through the published host port.

### Apple Silicon feels slow

Docker runs a Linux VM. Use native Ollama on the host with
`compose.host-ollama.yaml` so Ollama can use Metal.

## Operator cheat sheet

```bash
# start
docker compose up -d --build

# pull model
docker compose --profile setup run --rm model-pull

# status / logs
docker compose ps
docker compose logs -f vira worker ollama

# restart after config edit
docker compose restart vira worker

# stop
docker compose down

# stop and delete all data/models
docker compose down -v

# native Ollama on macOS/Linux
docker compose -f compose.host-ollama.yaml up -d --build

# NVIDIA GPU
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build

# development
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

## Related docs

- [Architecture](../../assets/VIRA_architecture.svg)
- [Deployment roadmap](../../dev/roadmap/server.md)
- [Plugin SDK](../../dev/plugin-sdk.md)
- [P4 ecosystem](../../dev/designs/p4-ecosystem.md)
- [Client README](https://github.com/Vishalsng112/VIRA/blob/main/client/README.md)
