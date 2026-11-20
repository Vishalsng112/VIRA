# Troubleshooting

## Run the doctor

Before changing anything, run the first-run health check from the VIRA directory:

```bash
python -m vira doctor
```

Or, if you only want a machine-readable report:

```bash
python -m vira doctor --json
```

It checks Docker and Compose, Ollama reachability, the selected model and its
context size, port conflicts, the Chatbot agent, database writability and the
master key. Every warning or failure prints a suggested fix.

If the Chatbot is slow or makes poor tool choices, read
[Choose a local model](models.md) before concluding the server is broken.

## Docker is missing on Windows

Install Docker Desktop, enable WSL2 if prompted, reboot, start Docker Desktop,
then re-run the installer.

## Docker is missing on Linux

The one-command installer installs Docker Engine automatically. If it cannot,
install Docker from your distribution's repository, then re-run the installer.

## No GPU

VIRA falls back to CPU, which is slower. To use an NVIDIA GPU, see the GPU
section of [Docker and deployment](install/docker.md).

## Apple Silicon

Use native Ollama on macOS (`--host-ollama`). Docker Desktop runs a Linux VM and
cannot use Metal GPU acceleration.

## Model pull fails

The selected model may not be available under that name. Set
`VIRA_OLLAMA_MODEL` in `.env`, then pull the same name manually:

```bash
docker compose exec ollama ollama pull <model>
```

## Port is already in use

Re-run the installer with `--port 8080`, or change `VIRA_PORT` in `.env` and
restart.

## A device cannot reach the server

- Use the server's LAN address on the device, not `localhost`.
- Set `VIRA_BIND_ADDRESS=0.0.0.0` in `.env` and restart.
- Allow port `8000` through the host firewall.
- Keep `auth.https_only: false` only for local HTTP; use HTTPS otherwise.

## Where are the logs?

```bash
docker compose logs -f vira-server
docker compose logs -f worker
```

Operational endpoints: `/health` and `/metrics` on the server.

## Still stuck?

Open an issue at <https://github.com/Vishalsng112/VIRA/issues> with the output of
`docker compose ps`, `docker compose logs vira-server` and your OS/architecture.
