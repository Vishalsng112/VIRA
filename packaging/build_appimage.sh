#!/usr/bin/env bash
set -euo pipefail

PYAPPIMAGE_URL="https://github.com/niess/python-appimage/releases/download/python3.11/python3.11.17-cp311-cp311-manylinux2014_x86_64.AppImage"

cd "$(dirname "$0")/.."
ROOT="$PWD"
rm -rf build/appimage && mkdir -p build/appimage && cd build/appimage

wget -O python.AppImage "$PYAPPIMAGE_URL"
chmod +x python.AppImage
./python.AppImage --appimage-extract >/dev/null
mv squashfs-root AppDir
rm -f AppDir/*.desktop AppDir/*.png AppDir/*.svg AppDir/.DirIcon

AppDir/opt/python3.11/bin/python3.11 -m pip install --no-cache-dir -r "$ROOT/requirements.txt"

mkdir -p AppDir/opt/vira
cp -r "$ROOT/run.py" "$ROOT/config.yaml" "$ROOT/vira" "$ROOT/helpers" AppDir/opt/vira/
find AppDir -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "${VERSION:-dev}+build${BUILD_NUMBER:-0}" > AppDir/opt/vira/VERSION

install -m755 "$ROOT/packaging/AppRun" AppDir/AppRun
cp "$ROOT/packaging/vira.desktop" AppDir/vira.desktop
cp "$ROOT/packaging/vira.png" AppDir/vira.png

wget -O appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool
ARCH=x86_64 ./appimagetool --appimage-extract-and-run AppDir VIRA-x86_64.AppImage
echo "DONE: build/appimage/VIRA-x86_64.AppImage"
