#!/usr/bin/env bash
# Build the Linux AppImage for VIRA Link.
# Requires: Flutter Linux desktop toolchain (GTK 3), appimagetool on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."

flutter build linux --release
BUNDLE="build/linux/x64/release/bundle"
APPDIR="build/appimage/VIRA_Link.AppDir"
OUT="build/VIRA-Link-x86_64.AppImage"

if [[ ! -d "$BUNDLE" ]]; then
  echo "Linux bundle not found at $BUNDLE" >&2
  exit 1
fi
TOOL="${APPIMAGETOOL:-}"
if [[ -z "$TOOL" ]]; then
  if ! command -v appimagetool >/dev/null 2>&1; then
    echo "appimagetool is not installed (set APPIMAGETOOL to a downloaded copy)" >&2
    exit 1
  fi
  TOOL="appimagetool"
fi
FLAGS="${APPIMAGETOOL_FLAGS:-}"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$BUNDLE"/. "$APPDIR/usr/bin/"
cp web/icons/Icon-512.png "$APPDIR/vira-link.png"

cat > "$APPDIR/vira-link.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=VIRA Link
Comment=Device companion for your private VIRA server
Exec=vira_link
Icon=vira-link
Categories=Utility;Network;
Terminal=false
DESKTOP

cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/vira_link" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

ARCH=x86_64 "$TOOL" $FLAGS "$APPDIR" "$OUT"
echo "Built $OUT"
