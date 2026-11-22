# VIRA User Manual

This manual is for people who want to **run and use VIRA**. No source changes are
required.

## Contents

- [Getting started](getting-started.md) — install the server and open the dashboard
- [Five-minute proof](demo.md) — chat, live tool calls and the database boundary
- [One-command install](install/one-command.md) — Linux, macOS and Windows installers
- [Docker and deployment](install/docker.md) — Compose, Ollama, GPU and operations
- [VIRA Link client](client.md) — the device companion app
- [Remote access](remote-access.md) — Cloudflare tunnel, LAN fallback and optional Tailscale
- [Platform capability matrix](platforms.md) — artifacts, collectors, signing and uninstall per platform
- [Choose a local model](models.md) — tiers by RAM/GPU, cloud fallback and the tool-use warning
- [Security overview](security.md) — controls, evidence and limits
- [Troubleshooting](troubleshooting.md) — common install and runtime problems

## What you need

- A computer, NAS or server that can run Docker (8 GB RAM minimum, 16 GB+ recommended)
- Docker Engine or Docker Desktop with Compose v2+
- About 6–10 GB free disk for images and models
- Optionally, a phone or desktop for VIRA Link

You do **not** need VIRA Link to use the dashboard or chat.
