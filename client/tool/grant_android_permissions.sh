#!/usr/bin/env bash
# Grant the Android permissions that an ordinary app cannot grant itself.
#
# This is a developer convenience for USB/emulator builds. Normal users should
# install VIRA Link from the Play Store, where Android does not apply the
# sideloading restriction.
#
# Usage:
#   ./tool/grant_android_permissions.sh [package-name]
#
# Defaults to com.vira.link.

set -euo pipefail

PACKAGE="${1:-com.vira.link}"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb is not installed or not on PATH." >&2
  exit 1
fi

adb wait-for-device

echo "Allowing restricted settings for $PACKAGE..."
adb shell cmd appops set "$PACKAGE" ACCESS_RESTRICTED_SETTINGS allow || true

echo "Granting Usage Access (app usage + screen time)..."
adb shell cmd appops set "$PACKAGE" GET_USAGE_STATS allow

echo "Granting notification permission..."
adb shell pm grant "$PACKAGE" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

echo
echo "Current permission state:"
adb shell cmd appops get "$PACKAGE" ACCESS_RESTRICTED_SETTINGS || true
adb shell cmd appops get "$PACKAGE" GET_USAGE_STATS || true
adb shell dumpsys package "$PACKAGE" | grep -A1 "POST_NOTIFICATIONS" | tail -1 || true

echo
echo "Done. Reopen VIRA Link if it was already running."
