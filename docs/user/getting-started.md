# Getting started

VIRA has two pieces:

- **VIRA Server** — the API, dashboard, chat, agents, tools, memory and scheduler.
  It runs as a Linux container through Docker, on Linux, macOS or Windows.
- **VIRA Link** — the optional device companion that collects usage, focus,
  battery and health signals. It connects to VIRA Server.

## One-command install (recommended)

Linux and macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.ps1 | iex
```

The installer detects your OS, architecture, memory, free disk and GPU, installs
or checks Docker, chooses a suitable Ollama model, downloads VIRA, starts the
server and worker, pulls the model and prints the dashboard URL.

Open the printed URL — by default <http://localhost:8000> — and create your
account on first run.

Before the first chat, check the whole path:

```bash
python -m vira doctor
```

It verifies Docker, Ollama, the selected model and context, the port, the
Chatbot, the database and the master key. If the model is too small for your
hardware, see [Choose a local model](models.md).

!!! info "Review before you run"
    The installers are plain shell and PowerShell scripts in
    [`scripts/`](https://github.com/Vishalsng112/VIRA/tree/main/scripts). Read
    them first if you prefer to know exactly what runs on your machine.

## Manual install with Docker

```bash
git clone https://github.com/Vishalsng112/VIRA.git
cd VIRA
cp .env.example .env
docker compose up -d --build
```

Then pull the default model:

```bash
docker compose exec ollama ollama pull ornith-1.5:9b
```

Open <http://localhost:8000>.

For GPU, native-Ollama and development variants, see
[Docker and deployment](install/docker.md).

## Connect a device

1. Install **VIRA Link** on the phone or desktop. See [VIRA Link](client.md).
2. Sign in with the same VIRA account.
3. Approve the signals you want to share. VIRA Link captures nothing that you
   have not enabled.

The dashboard and chat work without VIRA Link.

## Next steps

- [One-command install options](install/one-command.md)
- [Docker, Ollama and GPU](install/docker.md)
- [Troubleshooting](troubleshooting.md)
