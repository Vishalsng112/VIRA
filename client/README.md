# VIRA Link

VIRA Link is the Flutter device companion for a VIRA server. It enrolls a device,
captures only the signals the user enables, stores every event in a local outbox,
and syncs to the server when it is reachable. It runs as an Android APK, iOS app,
web PWA, Linux AppImage and Windows desktop executable.

## What it does

- Signs in with a normal VIRA user account.
- Enrolls this device through `POST /api/v1/devices` and stores the one-time
  device credential in the platform keystore/keychain.
- Captures device telemetry through modular collectors.
- Captures **Android foreground app usage** through `UsageStatsManager` (after the user grants Usage Access), categorises apps, and keeps a local 30-day usage ledger.
- Shows **Insights** with screen time, unlocks, top apps, focus/category breakdowns and rest suggestions.
- Captures **battery**, **screen/session**, **device health** (storage/memory/thermal) and **desktop idle** signals.
- Supports **focus sessions** with a local ledger and `device.focus.session` events.
- Captures **device health** (storage, memory, thermal, battery temperature) and **desktop idle** state.
- Builds **local rule-based smart insights** (distraction share, long sessions, unlocks, health warnings) without sending raw data.
- Captures **desktop active-window usage** on X11, Sway, Hyprland, KDE, Windows and macOS. GNOME Wayland uses the bundled optional Shell extension.
- Exports local insight data as JSON and can clear local histories per collector.
- Writes events to a durable local outbox before any network call.
- Sends bounded batches to `POST /api/v1/devices/{id}/events:batch`.
- Heartbeats the device (which also activates a newly enrolled device).
- Lists, renames and revokes devices linked to the account.
- Works offline; the queue drains automatically when the server returns.
- Polls server-to-device commands: pause/resume capture, config update, queue flush/clear, update check.

## Run

```bash
cd client
flutter pub get
flutter run -d chrome       # web
flutter run -d linux        # Linux desktop
flutter run                 # connected Android/iOS device
```

Set the server URL to the host reachable from the device, for example
`http://192.168.1.20:8000`. Keep `auth.https_only: false` only for local HTTP
development. On the web, serve the PWA over HTTPS (or `localhost`) so the
browser's secure credential storage is available.

Builds:

```bash
flutter build apk --release
flutter build web --release
flutter build linux --release
flutter build windows --release   # run on Windows
./packaging/build_appimage.sh     # Linux AppImage (needs GTK 3 + appimagetool)
```

## CI builds

Run **Actions → Build VIRA Link (all platforms) → Run workflow**. The manual
workflow builds and uploads:

- Android release APK
- iOS unsigned `Runner.app` archive
- Web PWA zip
- Linux x86_64 AppImage
- Windows x64 zip

It also runs `flutter analyze` and `flutter test` first. Set `create_release` to
publish all builds and a checksum file in one GitHub Release.

The iOS artifact is unsigned because signing certificates and provisioning
profiles are not part of the repository. Sign it in Xcode or with your own CI
secrets before distributing to devices.

For a signed Android release, add these repository secrets:

- `ANDROID_KEYSTORE_BASE64` — base64 of your `.jks` keystore
- `ANDROID_STORE_PASSWORD`
- `ANDROID_KEY_PASSWORD`
- `ANDROID_KEY_ALIAS`

Without them the workflow still builds an installable APK using the debug key.

## Architecture

```text
lib/
  app/                 shell, navigation modules, theme, AppController
  core/                config, models and id utilities
  data/
    api/               HTTP contract for the VIRA device API
    storage/           secure credentials, outbox, settings
  services/
    capture/           collector interface + platform probes
      collectors/      device status, hardware, network
    sync/              heartbeat, batch send, backoff
  features/
    onboarding/        connect + enroll
    dashboard/         status, capture modules, sync controls
    insights/          local app-usage summary and categories
    activity/          queued and delivered event log
    devices/           account devices, rename, revoke
    settings/          sync, capture, lifecycle
```

The full data taxonomy, use cases and future phases are in
[ROADMAP.md](ROADMAP.md). In short: the client is being built to collect device
health, app usage, screen/focus signals and opt-in context so VIRA agents can
later produce wellbeing, study and productivity insights.

### Adding a feature

1. Add a page under `lib/features/<feature>/`.
2. Register it in `lib/app/modules.dart`.
3. Add API calls in `lib/data/api/vira_api.dart` if the feature needs the server.
4. Add any durable state to `lib/data/storage/`.

Removing a feature is the reverse: remove its module entry and page. Capture
features are even smaller: implement `Collector` and add it to the collector list
in `lib/services/capture/capture_service.dart`.

### Design rules

- **Offline first**: capture never depends on the network. The outbox is the
  source of truth until the server acknowledges an event.
- **Server is authoritative**: the client never chooses its device id, owner or
  scopes; those come from the server-issued credential.
- **Explicit capture**: every collector can be disabled independently.
- **Idempotent delivery**: event ids are generated on the device, so retries are
  safe and the server deduplicates them.
- **No secrets in plain storage**: session and device credentials use
  `flutter_secure_storage`.

## Server contract used

| Purpose | Endpoint |
| --- | --- |
| Sign in | `POST /api/v1/auth/login` |
| Create first admin | `POST /api/v1/auth/setup` |
| Enroll device | `POST /api/v1/devices` |
| List devices | `GET /api/v1/devices` |
| Rename device | `PATCH /api/v1/devices/{id}` |
| Revoke device | `POST /api/v1/devices/{id}/revoke` |
| Heartbeat | `POST /api/v1/devices/{id}/heartbeat` |
| Send events | `POST /api/v1/devices/{id}/events:batch` |

The event allow-list is controlled by the server in `config.yaml`
(`devices.event_policy.types`).

### Android Usage Access permission

App usage, screen/session events and screen-time rollups are read only after the user grants **Usage Access**:

1. Open **Overview → App usage → Grant access**.
2. Enable VIRA Link in the Android Usage Access screen.
3. Return to the app; capture resumes automatically.

Android also requires the `QUERY_ALL_PACKAGES` permission to resolve app labels.
If you distribute through Google Play, review its declaration requirements for
that permission; the collector still works with package names if labels are not
available.

### GNOME Wayland active window

GNOME does not expose the focused window to normal applications. Install the bundled optional extension once:

```bash
./packaging/gnome-extension/install.sh
# Log out and back in, then:
gnome-extensions enable vira-link@vira.local
```

The X11/Sway/Hyprland/KDE, Windows and macOS probes work without an extension. On GNOME without the extension, Active window reports `unavailable`; all other collectors continue normally.

### Admin control panel

Administrators get an **Admin** module in the client with:

- Server health, uptime, event pipeline and sensor status
- Agent list, enable/disable and unregister
- User create/update/delete, role and status changes, one-time credentials
- Fleet devices with last-seen, queue and battery state
- Security/admin audit log

Non-admin accounts do not see the module. The server still enforces every
administrator permission.

### Server insight API

The server exposes aggregate-only insight endpoints:

- `GET /api/v1/insights/summary?device_id=…&days=7`
- `GET /api/v1/insights/context?device_id=…&days=7` for future agents
- `GET /api/v1/insights/fleet` for administrators

They aggregate the device events already stored by the ingestion pipeline; raw
payloads are not re-exported.

VIRA's ChatAgent also registers an `insights` tool, so a user can ask questions
such as “how much time did I spend on social apps this week?” and the agent can
use the authenticated user/device context to answer from the aggregate.

### Local data controls

Settings includes **Export local data** (JSON copy, no credentials) and
**Clear local insights**. Each collector with a local ledger also has a menu to
clear just that collector’s history.
