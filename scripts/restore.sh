#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -ne 1 ]]; then
  echo "usage: scripts/restore.sh <backup.sqlite3>" >&2
  exit 2
fi
echo "Stop the VIRA API and worker before restoring."
python -m vira.ops.backup restore "$1"
