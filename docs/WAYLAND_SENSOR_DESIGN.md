# Wayland sensor design

VIRA's behavioral context is built from coarse, local signals rather than
capturing the user's screen. This is intentional: Wayland clients cannot
enumerate or inspect other applications through the core protocol. Screen
capture is mediated by `xdg-desktop-portal` and PipeWire, requires an explicit
user selection/consent flow, and is not a suitable background sensor.

## Signals and collection modes

| Sensor | Mode | Default | Useful context | Privacy decision |
|---|---|---:|---|---|
| `FileSystemSensor` | event-driven | opt-in | files created, edited, moved, deleted in an approved workspace | paths are scoped; never watch `$HOME` by default |
| `WaylandIdleSensor` | polling, change-only events | 5 s | present/idle transitions and session identity | no global keyboard or pointer capture |
| `UserActivitySensor` | polling | 2 s | clipboard-change frequency and content length | `wl-paste` only; content is suppressed by default |
| `ProcessSensor` | polling | 15 s | process count and coarse resource pressure | only top resource consumers, no command lines |
| `NetworkSensor` | polling | 10 s | network intensity and online-work periods | byte/packet counters only, no destinations |
| `HardwareSensor` | polling | 30 s | CPU, memory, battery, thermal and display conditions | low-rate aggregate telemetry |

Project context should come from an explicitly configured `FileSystemSensor`,
not from a home-directory scan. Global focus and screenshot sensors are not
implemented because Wayland does not provide those capabilities to ordinary
background clients.

## Signals deliberately not collected

- Screenshots, OCR, and video capture.
- Global keyboard and pointer events.
- Global active-window enumeration or application titles.
- X11 APIs (`xclip`, `xsel`, Xlib, or XTest).
- Clipboard contents unless a future, explicit user-consent setting enables
  bounded content capture.

If a user needs screen context, it should be a foreground, user-initiated
portal session using `org.freedesktop.portal.ScreenCast`, not a silent sensor.
The portal's source selection and consent must remain visible to the user.

## Configuration guidance

The default values in [`config.yaml`](../config.yaml) balance behavioral
resolution with event volume:

- Event-driven filesystem changes are the primary fine-grained work signal.
- Idle and clipboard polling are fast enough to segment sessions without
  producing a one-event-per-second stream.
- Process and network samples are slower because they describe trends.
- Hardware samples are slowest because they are environmental context, not
  direct user intent.

Keep payloads aggregate and apply retention at the device event policy. Any
new sensor should document its signal, collection mode, data minimization, and
Wayland support before being enabled by default.

## References

- [Wayland protocol overview](https://wayland.app/protocols/)
- [Wayland idle-notify protocol](https://wayland.app/protocols/ext-idle-notify-v1)
- [Desktop portal ScreenCast interface](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)
- [PipeWire](https://pipewire.org/)
