# One-command VIRA Server install

These installers are the fastest path for a new user. They detect the operating
system, architecture, memory, free disk and GPU, install/check Docker, choose a
sensible Ollama model, download VIRA, start the server and worker, and pull the
model.

## Linux and macOS

```bash
curl -fsSL https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.sh | bash
```

What it does:

1. Detects Linux distribution or macOS, CPU architecture, RAM and free disk.
2. Detects NVIDIA/AMD/Apple GPU where possible.
3. Installs Docker Engine automatically on Linux if needed.
4. Uses Docker Desktop on macOS if present; otherwise explains the requirement.
5. Chooses a model based on available RAM.
6. Downloads VIRA to `~/vira` (or updates an existing checkout).
7. Starts VIRA Server, the worker and Ollama.
8. Pulls the model and prints the dashboard URL.

Default Ollama mode:

- **Linux:** bundled Ollama container
- **macOS:** native Ollama on the host, so it can use Metal

## Windows

```powershell
irm https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.ps1 | iex
```

What it does:

1. Detects Windows, CPU architecture, RAM, free disk and NVIDIA GPU.
2. Checks Docker Desktop; tries to install it with `winget` if missing.
3. Chooses a model based on available RAM.
4. Downloads VIRA to `%USERPROFILE%\VIRA`.
5. Starts VIRA Server, the worker and bundled Ollama.
6. Pulls the model and prints the dashboard URL.

Docker Desktop may require WSL2 and a reboot on first install. If the installer
stops, start Docker Desktop, reboot if needed, and run the command again.

## Review before running

The one-liner downloads and executes a script. If you prefer to inspect it:

```bash
curl -fsSL https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.sh -o vira-install.sh
less vira-install.sh
bash vira-install.sh --dry-run
bash vira-install.sh
```

Windows:

```powershell
irm https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.ps1 -OutFile vira-install.ps1
notepad vira-install.ps1
powershell -ExecutionPolicy Bypass -File .\vira-install.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\vira-install.ps1
```

## Options

### Linux/macOS

```bash
# custom location and port
curl -fsSL .../scripts/install.sh | bash -s -- --dir ~/apps/vira --port 8080

# choose a model
curl -fsSL .../scripts/install.sh | bash -s -- --model llama3.1:8b

# use native Ollama instead of the container
curl -fsSL .../scripts/install.sh | bash -s -- --host-ollama

# use a remote Ollama server
curl -fsSL .../scripts/install.sh | bash -s -- \
  --ollama-url https://ollama.example.internal

# NVIDIA GPU with bundled Ollama
curl -fsSL .../scripts/install.sh | bash -s -- --gpu

# plan only
curl -fsSL .../scripts/install.sh | bash -s -- --dry-run
```

### Windows

When using `irm | iex`, configure with environment variables before running:

```powershell
$env:VIRA_DIR = "$env:USERPROFILE\apps\VIRA"
$env:VIRA_PORT = "8080"
$env:VIRA_OLLAMA_MODEL = "llama3.1:8b"
irm https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.ps1 | iex
```

Or download and run with parameters:

```powershell
.\vira-install.ps1 -Dir "$env:USERPROFILE\apps\VIRA" -Port 8080 -Model llama3.1:8b
.\vira-install.ps1 -DryRun
.\vira-install.ps1 -OllamaMode host -Gpu
```

Useful parameters: `-Dir`, `-Port`, `-BindAddress`, `-Model`, `-OllamaMode`,
`-OllamaUrl`, `-Gpu`, `-NoModel`, `-NoDockerInstall`, `-DryRun`.

## After install

Open:

```text
http://localhost:8000
```

Create the administrator account on first visit. Then use:

- `/dashboard` — control center
- `/chat` — chat workspace
- `http://<server-LAN-IP>:8000` — server URL for VIRA Link on other devices

**VIRA Server** is the Dockerized runtime. **VIRA Link** is the native device
companion that collects usage, focus, battery and health data. You do not need
VIRA Link to use the dashboard or chat.

## Change the model later

```bash
cd ~/vira
# edit VIRA_OLLAMA_MODEL in .env, then
docker compose up -d
docker compose exec ollama ollama pull llama3.1:8b
```

## Stop / restart / logs

```bash
cd ~/vira
docker compose ps
docker compose logs -f vira worker
docker compose restart vira worker
docker compose down
```

## Uninstall

Stop the containers:

```bash
cd ~/vira
docker compose down
```

Remove everything, including the database, master key and models:

```bash
docker compose down -v
rm -rf ~/vira
```

Windows:

```powershell
cd $env:USERPROFILE\VIRA
docker compose down -v
Remove-Item $env:USERPROFILE\VIRA -Recurse -Force
```

## If the installer cannot continue

- **Docker missing on macOS:** install Docker Desktop, OrbStack or Colima, start
  it, then re-run the installer.
- **Docker missing on Windows:** install Docker Desktop, enable WSL2 if prompted,
  reboot, start Docker Desktop, then re-run.
- **No GPU:** the installer uses CPU; models will be slower.
- **Apple Silicon:** use native Ollama (`--host-ollama` on macOS). Docker Desktop
  runs a Linux VM and cannot use Metal GPU acceleration.
- **Model pull fails:** the selected model may not be available under that name.
  Edit `VIRA_OLLAMA_MODEL` in `.env`, then pull the same name manually.
- **Port in use:** re-run with `--port 8080` or change `VIRA_PORT` in `.env`.

For deeper deployment, backup, security and developer instructions see
[docs/DOCKER.md](DOCKER.md) and the [architecture diagram](VIRA_architecture.svg).
