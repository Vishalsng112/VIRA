# Platform capability matrix

VIRA has two pieces with different platform stories:

- **VIRA Server** runs anywhere Docker runs: Linux, macOS and Windows.
- **VIRA Link** is the native device companion. Its collectors depend on what the
  operating system exposes; it reports `permission_denied`, `degraded` or
  `unavailable` instead of inventing data.

The [client roadmap](../dev/roadmap/client.md) tracks deeper collector work.

## Server

| Platform | Supported | How |
|---|---|---|
| Linux | Yes | Docker Compose, one-command installer |
| macOS | Yes | Docker Desktop or Colima + native Ollama for Metal |
| Windows | Yes | Docker Desktop + PowerShell installer |
| NAS / homelab | Yes | Docker Compose on the NAS |

Host sensing inside the server container is limited by Docker. App usage, focus,
battery and health signals come from VIRA Link on the endpoint, not from the
server container. See
[what host sensing looks like inside Docker](security.md#what-host-sensing-looks-like-inside-docker).

## VIRA Link artifacts

| Platform | Artifact | Signing | Notes |
|---|---|---|---|
| Android | `*-android.apk` | Debug-signed unless signing secrets are configured | Usage Access is required for app usage |
| iOS | `*-ios-unsigned.zip` | Unsigned | Sign in Xcode with your Apple credentials |
| Web / PWA | `*-web.zip` | HTTPS | Best on macOS and any modern browser |
| Linux x86_64 | `*-linux-x86_64.AppImage` | — | `chmod +x`, then run |
| Windows x64 | `*-windows-x64.zip` | — | Unzip and run `vira_link.exe` |
| macOS | `*-macos-arm64.zip` | Unsigned | Apple Silicon; right-click → Open the first time |

Release artifacts are produced by
[`build-client.yml`](https://github.com/Vishalsng112/VIRA/blob/main/.github/workflows/build-client.yml)
and published with `checksums.txt`. Verify downloads:

```bash
sha256sum -c checksums.txt        # Linux
shasum -a 256 -c checksums.txt    # macOS
```

## Collector support

| Capability | Android | iOS | Linux | Windows | macOS | Web |
|---|---|---|---|---|---|---|
| Device/app status | Yes | Yes | Yes | Yes | Yes | Yes |
| Network state | Yes | Yes | Yes | Yes | Yes | Limited |
| Hardware / health | Limited | No | Yes | Partial | Partial | No |
| App usage | Yes (Usage Access) | No | Yes (active window) | Yes (foreground window) | Yes (frontmost app) | No |
| Screen / session | Yes | No | Partial | Partial | No | Limited |
| Battery | Yes | No | Yes | Partial | No | API-dependent |
| Focus / idle | Yes | No | Yes | Yes | Yes | No |
| Active window | — | — | X11, Sway, Hyprland, KDE; GNOME via extension | Yes | Yes | No |
| Notifications | Yes (while running) | In-app only | In-app only | In-app only | In-app only | In-app only |
| Crash diagnostics | Opt-in | Opt-in | Opt-in | Opt-in | Opt-in | Opt-in |

## macOS support decision

VIRA Link now has a **native macOS target** built by the release workflow on
`macos-latest` (Apple Silicon). It supports signing in, enrollment, sync, chat,
insights, desktop active-window capture and the same permission diagnostics as the
other desktop builds.

Known limits:

- The published macOS build is **unsigned and arm64**. Right-click → **Open** the
  first time, or sign/notarize it with your Apple Developer credentials.
- **Intel Macs** should use the web/PWA client. An Intel desktop artifact is not
  part of the release matrix yet.
- macOS app-sandbox entitlements are limited to network client/server and the
  app's keychain group. VIRA Link does not request screen recording or
  accessibility permissions; those signals are unavailable and report honestly.
- The server itself still runs on macOS through Docker; native Ollama on the host
  is recommended for Metal acceleration.

## Permissions and notifications

- After the first successful connection, VIRA Link shows a one-time **Set up
  your device** screen with two optional permissions.
- **Notifications** use Android's standard runtime prompt, requested in-app.
  Native notifications are used for agent results while VIRA Link is running.
  Delivery while the app is closed needs a configured push relay.
- **Activity insights** (app usage and screen time) are **off by default**.
  Enabling them opens Android's Usage Access page. Android does not allow an app
  to grant this special access itself.
- Platform-specific collectors now default to off when the platform cannot
  provide them. Android leaves active-window, hardware and idle collectors off;
  Linux leaves active-window and battery collectors off.
- Linux active-window capture is unavailable under GNOME Wayland because the
  compositor does not expose foreground windows. It remains available on
  supported X11/Wayland compositors and can be enabled manually.
- If VIRA Link was installed outside the Play Store and the Usage Access switch
  is greyed out, Android is applying its sideloading restriction. Open
  **App info → ⋮ → Allow restricted settings** once, then retry. Play Store
  installs do not show this block.
- **Settings → Permissions and notifications** repeats the list, explains every
  unavailable signal, and lets you open the same system pages again.
- Every collector remains independently disableable. Turning one off stops new
  events; queued events still sync.

Developers installing with USB/ADB can grant the special access after each fresh
install:

```bash
cd client
./tool/grant_android_permissions.sh
```

## Diagnostics

Crash and error diagnostics are **off by default**. When enabled:

- reports stay on the device unless you press **Send diagnostic report**;
- only app version, platform/device type/OS version, sync state, collector
  statuses and redacted error text are included;
- credentials, server URL, device ID, username, chat content and event payloads
  are excluded;
- the client redacts token-shaped strings and URLs before storing or sending;
- the server applies a second redaction pass and stores the report in the
  administrator audit view (`/api/v1/admin/diagnostics`).

## Uninstall

| Platform | Clean removal |
|---|---|
| Android | Uninstall the app from the launcher or system settings |
| iOS | Remove the app; delete the Keychain item if you used a shared keychain |
| Web | Clear site data for the VIRA server origin |
| Linux | Delete the AppImage; remove `~/.local/share/com.vira.link` if present |
| Windows | Delete the unzipped folder and `%APPDATA%\com.vira.link` |
| macOS | Move `vira_link.app` to the Trash; delete the app container if prompted |

Revoke the device first in **VIRA Link → Settings → Device lifecycle → Sign out and
unlink**, or from the server dashboard, so the credential cannot be reused.
