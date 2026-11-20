#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Build the production VIRA Server image.
# Extra arguments are passed to docker build, e.g. --no-cache.
docker build -t vira:latest "$@" .
