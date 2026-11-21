# VIRA Link client

VIRA Link is the Flutter device companion for a VIRA server. It enrolls a device,
captures only the signals you enable, stores every event in a local outbox and
syncs to the server when it is reachable.

It runs as an Android APK, iOS app, web PWA, Linux AppImage, Windows desktop
executable and macOS (Apple Silicon) app. See the
[platform capability matrix](platforms.md) for what each platform can collect and
which artifact is published.

## What it does

- Signs in with a normal VIRA user account.
- Enrolls the device and stores its one-time credential in the platform
  keystore or keychain.
- Captures only the signals you enable: usage, focus, battery, screen/session,
  device health and desktop idle.
- Writes events to a durable local outbox before any network call, so it works
  offline and drains automatically when the server returns.
- Shows local Insights — screen time, unlocks, top apps, focus breakdown and
  rest suggestions.
- **Agent Inbox** — proactive agent results, unread notifications, agent recipe
  cards, schedule creation/editing, pause/resume, delete, next-run times,
  run-now and run history.
- Polls server-to-device commands such as pause/resume capture, config update and
  queue flush.
- Lists, renames and revokes devices linked to your account.

## Get the app

The client is built from the [`client/`](https://github.com/Vishalsng112/VIRA/tree/main/client)
directory in this repository. Build outputs are produced by the
[client workflow](https://github.com/Vishalsng112/VIRA/actions/workflows/build-client.yml).

## Build and run from source

```bash
cd client
flutter pub get
flutter run -d chrome       # web
flutter run -d linux        # Linux desktop
flutter run -d macos        # macOS desktop (Apple Silicon)
flutter run                 # connected Android/iOS device
```

Set the server URL to an address reachable from the device, for example
`http://192.168.1.20:8000`. Keep `auth.https_only: false` only for local HTTP
development; use HTTPS when the server is reachable from other machines.

## Server URL and networking

- On the same machine, `http://localhost:8000` works for the desktop and web build.
- On a phone, use the server's LAN address, not `localhost`.
- If the server binds only to `127.0.0.1`, other devices cannot connect. Set
  `VIRA_BIND_ADDRESS=0.0.0.0` in `.env` and restart.

For developer-level details — module layout, collectors and API contract — see
the [client README](https://github.com/Vishalsng112/VIRA/blob/main/client/README.md).
