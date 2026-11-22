# VIRA Link Roadmap

**Goal:** make VIRA Link a mature, privacy-first device companion that collects
useful behavioural and device context locally, works offline, and gives the VIRA
server enough structured data to power useful agents later.

Legend: **Done** · **Now** · **Next** · **Later**

---

## 1. Product principles

1. **Local first.** Capture writes to the device outbox before any network call.
2. **Explicit consent.** Every sensitive signal has its own switch and OS
   permission. App usage is opt-in at the OS level through Usage Access.
3. **Minimum necessary data.** Prefer aggregates and metadata over raw content.
   Never collect keystrokes, message bodies, passwords or clipboard content by
   default.
4. **Server is authoritative.** Device identity, credentials, scopes and event
   policy come from the VIRA server.
5. **Modular collectors.** A feature should be addable or removable without
   touching sync, storage or the UI shell.
6. **Explainable insights.** Every summary must be traceable to events the user
   can inspect, export or delete.
7. **Graceful degradation.** Unsupported platforms report `unavailable`, not
   fake data.

---

## 2. What is useful to capture

### 2.1 Device and runtime context

| Signal | Why it is useful | Sensitivity | Status |
|---|---|---|---|
| Platform, OS, device type, hostname | Correct interpretation of all other data | Low | **Done** |
| App/client version, protocol | Compatibility and rollout health | Low | **Done** |
| Hardware: CPU, memory, uptime | Device health, performance warnings | Low | **Done** (Linux/Windows; macOS storage) |
| Battery level, charging, power source | Energy advice, quiet-hours logic | Low | **Done** (Android/Linux) |
| Network type, interface availability | Offline/online context, sync scheduling | Low | **Done** (basic) |
| Screen on/off, unlock count | Screen time, rest reminders | Medium | **Done** (Android) |
| Idle/focus state | Focus sessions, interruption detection | Medium | **Done** (desktop idle + focus sessions) |
| Crash/error events | Reliability and support | Low | **Done** (opt-in, redacted, local or explicit upload) |

### 2.2 Application and activity context

| Signal | Why it is useful | Sensitivity | Status |
|---|---|---|---|
| Foreground app time per package | “Most used apps”, digital wellbeing, study advice | High | **Done** (Android) |
| App category (social, education, games…) | Human-readable summaries and recommendations | Medium | **Done** |
| Current foreground app | Real-time focus/context signals | High | **Next** |
| App launches and sessions | Habit and routine detection | High | **Next** |
| Desktop active window/app | Equivalent of Android app usage on desktop | High | **Done** (X11, Sway, Hyprland, KDE, Windows, macOS; GNOME Wayland via bundled extension) |
| Media playback | Entertainment vs work balance | Medium | **Later** |
| Browser/domain usage | Online learning vs distraction | High, opt-in | **Later** |

### 2.3 Communication and social context

| Signal | Why it is useful | Sensitivity | Status |
|---|---|---|---|
| Notification volume and source app | Interruption/attention analysis | High, opt-in | **Later** |
| Call/meeting duration | Workload and meeting load | High, opt-in | **Later** |
| Message counts by app, never content | Communication balance | High, opt-in | **Later** |
| Contact interaction frequency, never content | Relationship maintenance | Very high, opt-in | **Later** |

### 2.4 Productivity, learning and planning

| Signal | Why it is useful | Sensitivity | Status |
|---|---|---|---|
| Study/focus sessions | Student coaching, streaks | Medium | **Next** |
| Tasks completed / reminders | Planning and follow-through | Medium | **Later** |
| Calendar busy/free blocks | Meeting load, focus suggestions | High, opt-in | **Later** |
| Documents recently opened | Knowledge recall and context | High, opt-in | **Later** |
| Typing/activity counts, never content | Focus and workload estimate | Medium | **Later** |

### 2.5 Health, location and environment

| Signal | Why it is useful | Sensitivity | Status |
|---|---|---|---|
| Steps, sleep, workouts | Holistic wellbeing recommendations | Very high, opt-in | **Later** |
| Location / places | Routines, commute, context-aware reminders | Very high, opt-in | **Later** |
| Ambient noise / light | Focus and sleep suggestions | High, opt-in | **Later** |
| Screen brightness and night usage | Eye comfort and sleep hygiene | Medium | **Later** |

### 2.6 Data quality and privacy metadata

| Signal | Why it is useful | Sensitivity | Status |
|---|---|---|---|
| Consent state per collector | Trust, audit, server policy | Low | **Done** |
| Capability status on heartbeat | Know what the device can report | Low | **Done** |
| Event retention class | Privacy-aware server modelling | Low | **Done** |
| Local export / delete | User control | Low | **Next** |

---

## 3. Use cases this unlocks

1. **Digital wellbeing coach** — daily screen time, top apps, late-night usage,
   category balance and weekly trends.
2. **Student focus coach** — compare study/education time with social and games,
   suggest focus blocks and exam-week limits.
3. **Context-aware assistant** — “you usually study at 7 pm; should I enable
   focus mode?” or “you have been on social apps for 45 minutes”.
4. **Daily and weekly reviews** — the agent summarises what happened, what
   changed and what to try next.
5. **Habit and pattern detection** — streaks, first-app-of-the-day, doom-scroll
   sessions, late-night screen time, weekend vs weekday patterns.
6. **Personal recommendations** — learning app suggestions, break reminders,
   app limits, sleep hygiene, fitness routines.
7. **Task automation triggers** — start a focus session when a study app opens,
   pause notifications during deep work, queue a review after a long session.
8. **Device fleet health** — low battery, high CPU, storage pressure, stale
   devices, unusual activity.
9. **Security and anomaly detection** — unexpected app usage bursts, revoked
   credential detection, unusual sync patterns.
10. **Privacy-preserving local insights** — summaries on-device before sending
    raw events, with redaction and aggregation.

---

## 4. Current architecture

```text
collectors -> CaptureService -> OutboxStore -> SyncService -> VIRA API
                    |                              |
                    +-> UsageLedger (local)        +-> heartbeat
                    +-> Settings (consent)
```

- `Collector` contract: id, title, description, capability, event type, interval,
  default-enabled, optional access request.
- `CollectorResult` reports `available`, `unavailable`, `permission_denied` or
  `degraded` plus a human-readable message.
- `CaptureService` schedules collectors and writes events to the outbox.
- `UsageLedger` keeps a 30-day local daily rollup for offline Insights.
- `SyncService` batches events, retries with backoff and heartbeats capability
  status.
- `Insights` is a module in the shell, not hard-coded navigation.

### Event naming

```text
device.telemetry.state          device/app identity and status
sensor.hardware.state           CPU, memory, uptime
sensor.network.state            interface availability
device.app.usage                aggregated foreground app time
device.session.state            screen time, unlocks, current session
device.focus.state              focus/distraction summary per interval
device.battery.state             battery level, charging, temperature
```

### App usage event shape

```json
{
  "event_id": "uuid",
  "type": "device.app.usage",
  "schema_version": 1,
  "occurred_at": "2026-11-20T05:30:00Z",
  "source_component": "app_usage",
  "device_sequence": 42,
  "payload": {
    "window_seconds": 300,
    "total_foreground_ms": 240000,
    "apps": [
      {
        "package": "com.instagram.android",
        "label": "Instagram",
        "category": "social",
        "foreground_ms": 180000,
        "last_used_at": "2026-11-20T05:29:00Z"
      }
    ]
  }
}
```

---

## 5. Implemented today

- [x] Device enrollment, secure credential storage and session refresh
- [x] Offline outbox with device sequence, retries and batching
- [x] Heartbeat with capability status and queue backlog
- [x] Device status collector
- [x] Network collector
- [x] Linux hardware collector (CPU, memory, uptime)
- [x] Modular collector contract and access-request flow
- [x] **Android app usage collector** via `UsageStatsManager`
- [x] **App categories** (social, communication, productivity, education,
      entertainment, browsing, games, shopping, finance, health, travel, system)
- [x] **Local 30-day usage ledger**
- [x] **Insights screen** with today/7-day ranges, top apps, category split
- [x] **Usage Access permission flow** and automatic refresh on app resume
- [x] **Desktop active-window collector** (X11, Sway, Hyprland, KDE, Windows, macOS; GNOME Wayland via bundled extension)
- [x] **Device health collector** (storage, memory, thermal, battery temperature)
- [x] **Desktop idle collector** (GNOME Wayland Mutter, X11/KDE, Windows, macOS)
- [x] **Focus sessions** with a local ledger and `device.focus.session` events
- [x] **Local smart insight engine** (rule-based recommendations and warnings)
- [x] **Server insight API** (`/api/v1/insights/summary`, `/context`, `/fleet`)
- [x] **Desktop app usage + focus events** sharing the same schema and local ledger as Android
- [x] **Battery collector** (Android via BatteryManager, Linux via sysfs)
- [x] **Screen & session collector** (Android UsageStats: screen on/off,
      unlocks, current session, interactions)
- [x] **Local session ledger** and screen-time rollups
- [x] **Focus summary** (`device.focus.state`) from app-category distribution
- [x] **In-app break suggestions** for long sessions and screen-heavy days
- [x] **Low-battery-aware automatic sync** (manual sync still works)
- [x] **Local data export** and per-collector/local-history clearing
- [x] Research-grade event payloads for server-side modelling
- [x] CI workflow for Android, iOS, web, Linux, Windows and macOS builds with checksums

---

## 6. Roadmap phases

### Phase 1 — App usage foundation — **Done / Now**

- [x] Android foreground app time collector
- [x] Local daily ledger and category rules
- [x] Insights page
- [x] Permission state and settings deep-link
- [x] Lifecycle resume re-check
- [ ] Validate category catalogue against real user data
- [ ] Add more granular session boundaries (launch/close events)
- [ ] Add local “today vs yesterday” and “week trend” comparisons

### Phase 2 — Screen, focus and device health — **Done**

- [x] Battery and charging collector (Android, Linux; Windows/web later)
- [x] Screen on/off and unlock counters (Android)
- [x] Focus summary from app-category distribution
- [x] Daily screen-time rollup and in-app rest reminders
- [x] Low-battery-aware automatic sync
- [x] Local JSON export and per-collector/local-history delete
- [x] Storage, memory, thermal and battery-temperature health signals
- [x] Desktop idle state (GNOME Wayland Mutter idle monitor, X11, KDE, Windows, macOS)
- [ ] Background notifications for rest reminders (in-app reminders are done; OS notification scheduling is deployment work)

### Phase 3 — Desktop active-window usage — **Done**

- [x] Linux/X11 active window collector (window class/title/pid)
- [x] Linux Wayland: Sway, Hyprland and KDE strategies
- [x] Linux GNOME Wayland: bundled optional Shell extension (active-window D-Bus bridge)
- [x] XWayland fallback through X properties
- [x] Windows foreground window collector (PowerShell/user32 bridge)
- [x] macOS frontmost application collector (osascript, lsappinfo fallback)
- [x] Desktop app category mapping (firefox, chrome, code, etc.)
- [x] Desktop Insights parity through the shared usage ledger
- [ ] Native Windows/macOS window probes without PowerShell/osascript (performance polish)
- [ ] GNOME extension auto-install/onboarding flow

### Phase 4 — Context signals — **In progress, opt-in**

- [ ] Notification volume/source app (requires Notification Access service)
- [ ] Calendar busy/free blocks (requires runtime calendar permission)
- [x] Focus/study session tracking (manual start/stop, local ledger, `device.focus.session` event)
- [ ] Media playback and meeting duration (requires media/notification session access)
- [ ] Browser/domain usage with allow-list (requires a browser extension or local history opt-in)
- [ ] Location/places with explicit consent (requires location permission flow)
- [ ] Health data with explicit consent (Health Connect / vendor platform)
- [ ] Ambient environment sensors where available (hardware dependent)

### Phase 5 — On-device intelligence — **Done (rule-based)**

- [x] Local daily/weekly summary generation
- [x] On-device pattern detection (distraction share, long sessions, unlocks, health warnings)
- [x] Aggregation before upload (interval aggregates, not raw app titles)
- [x] Local context API (`InsightEngine` + server `/api/v1/insights/context`)
- [x] Offline recommendations for focus, study and wellbeing
- [ ] User feedback loop (“useful / not useful”) stored locally
- [ ] Late-night usage detection (needs hourly buckets)

### Phase 6 — Server and agent integration — **In progress**

- [x] `/api/v1/insights/summary` endpoint for daily/weekly summaries
- [x] `/api/v1/insights/context` endpoint for agent context
- [x] Aggregate fleet health (`/api/v1/insights/fleet`)
- [x] Server-side aggregation of app/session/focus/battery/health events
- [x] `insights` tool registered for ChatAgent (uses the authenticated user/device context)
- [x] Device context threaded through ChatAgent → AgentLoop → local tools
- [ ] Server-side app catalogue and category enrichment (client categories are used today)
- [x] Insight-aware ChatAgent (answers usage/focus/wellbeing questions via the `insights` tool)
- [ ] Dedicated specialist student/focus agent
- [ ] Dedicated specialist digital wellbeing agent
- [ ] Dedicated specialist habit/routine agent
- [ ] Recommendation explanations with event references
- [ ] Retention, export and deletion workflows across client/server

### Phase 7 — Product hardening — **Partial**

- [ ] Background execution and reliable scheduling (requires platform workers)
- [ ] Battery-optimisation guidance per OEM
- [ ] Encrypted local outbox/ledger (needs key migration)
- [ ] QR/one-tap device pairing
- [ ] Multi-user account switching on one device (sign out/unlink exists)
- [ ] Notification permission and quiet-hours support (in-app reminders and an honest permission state exist; OS scheduling is deferred)
- [x] Admin control panel in VIRA Link: server health, agents, users, fleet, audit
- [x] Signed Android releases via optional CI secrets (iOS/macOS signing still needs Apple credentials)
- [ ] iOS/macOS signing, notarization, store metadata and submission automation
- [x] Crash reporting with opt-in and redaction
- [ ] Accessibility and localization pass
- [x] Manual end-to-end verification against a live VIRA server

---

## 6b. Deployment / external work

These items cannot be finished inside this repository alone:

- Store-signed APK/AAB/IPA (signing keys, Play/App Store accounts).
- Health Connect, Google Play Services location and vendor health APIs.
- GNOME extension activation on Wayland (requires a user session restart).
- OS notification scheduling and background workers on each platform.

The code surfaces these limitations in the UI instead of silently pretending the
signal is available.

## 7. Privacy and consent requirements

- Every collector must be independently disableable.
- Sensitive collectors default to **off** unless the OS permission itself is the
  explicit consent (current Android app usage flow).
- The UI must show what is captured, when it last ran and why it is unavailable.
- Users must be able to clear local history and delete server data.
- Never collect message bodies, passwords, keystrokes or clipboard content by
  default.
- Prefer `device.*` for durable aggregates and `sensor.*`/`telemetry` for
  high-volume raw signals.
- Include retention class and capability status in the event/heartbeat contract.

---

## 8. Platform capability matrix

| Capability | Android | iOS | Linux | Windows | macOS | Web |
|---|---|---|---|---|---|---|
| Device/app status | Yes | Yes | Yes | Yes | Yes | Yes |
| Network | Yes | Yes | Yes | Yes | Yes | Limited |
| Hardware metrics | Limited | No | Yes | Partial | Partial (storage) | No |
| App usage | Yes (Usage Access) | No (sandbox) | Yes (active window) | Yes (foreground window) | Yes (frontmost app) | No |
| Screen on/off | Yes | No | Partial | Partial | No | Limited |
| Battery | Yes | No | Yes | Partial | No | API-dependent |
| Focus / idle | Yes | No | Yes | Yes | Yes | No |
| Notifications | In-app only | In-app only | In-app only | In-app only | In-app only | In-app only |
| Crash diagnostics | Opt-in | Opt-in | Opt-in | Opt-in | Opt-in | Opt-in |
| Calendar | Opt-in later | Opt-in later | Opt-in later | Opt-in later | Opt-in later | No |
| Location | Opt-in later | Opt-in later | Opt-in later | Opt-in later | Opt-in later | Opt-in later |

Platform limitations are product constraints, not bugs. The client must report
them honestly through `permission_denied` and `unavailable` states.

Every available row above is represented by a toggle on **Overview**. Android
Focus/idle is implemented through UsageStats; Linux screen on/off remains
partial and is represented by the desktop Focus & idle signal. Notifications
and crash diagnostics have app-feature toggles. Calendar and location remain
future opt-ins.

---

## 9. Success metrics

- ≥ 95% of captured events eventually acknowledged by the server
- Queue survives app restart and offline periods without data loss
- App usage capture adds < 2% battery overhead per hour
- Insights load from local storage in < 300 ms
- Every collector has a clear consent state and capability report
- User can export and delete all local data in one flow
- No sensitive content is read without an explicit opt-in

---

## 10. How to add a collector

1. Create `lib/services/capture/collectors/<name>_collector.dart`.
2. Implement `Collector` with a unique id, capability, event type and interval.
3. Return `CollectorResult.available/...` and set `canRequestAccess` if an OS
   permission is needed.
4. Add it to `CaptureService._collectors`.
5. Add category/summary logic to the relevant ledger or page if needed.
6. Write a unit test with a fake platform probe/source.
7. Document the new event in this roadmap and in `client/README.md`.

Removing a collector is the reverse: remove it from `CaptureService`, delete the
file, and remove its capability from the UI.
