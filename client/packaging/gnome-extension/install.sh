#!/usr/bin/env bash
# Install the optional VIRA Link active-window bridge for GNOME Wayland.
set -euo pipefail

UUID="vira-link@vira.local"
SRC="$(cd "$(dirname "$0")" && pwd)/$UUID"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"

if [[ ! -f "$SRC/metadata.json" ]]; then
  echo "Extension source not found at $SRC" >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$SRC"/. "$DEST"/

echo "Installed $UUID to $DEST"
if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions enable "$UUID" 2>/dev/null || true
fi

echo
echo "If VIRA Link still reports Active window as unavailable:"
echo "  1. Log out and back in (GNOME Wayland only loads new extensions after a session restart)."
echo "  2. Run: gnome-extensions enable $UUID"
echo "  3. Restart VIRA Link."
