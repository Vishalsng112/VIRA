#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m vira.ops.backup create "$@"
