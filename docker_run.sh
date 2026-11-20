#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Easy start: VIRA Server + bundled Ollama.
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
docker compose up -d --build

echo
echo "VIRA Server:  http://localhost:${VIRA_PORT:-8000}"
echo "Model pull:   docker compose --profile setup run --rm model-pull"
echo "Logs:         docker compose logs -f vira"
