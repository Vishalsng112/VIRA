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
- Writes events to a durable local outbox before any network call.
- Sends bounded batches to `POST /api/v1/devices/{id}/events:batch`.
- Heartbeats the device (which also activates a newly enrolled device).
- Lists, renames and revokes devices linked to the account.
- Works offline; the queue drains automatically when the server returns.

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
    activity/          queued and delivered event log
    devices/           account devices, rename, revoke
    settings/          sync, capture, lifecycle
```

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
