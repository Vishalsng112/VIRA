# VIRA Family Client — System Design

> **Status:** Draft v0.1 · **Audience:** Flutter and VIRA-server developers · **Scope:** the cross-platform client app (Android, iOS/iPadOS, Linux, web) for the *Private Family Assistant* use case, and the server additions it requires.
>
> Companion to [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) (server) and [`MULTI_DEVICE_IMPLEMENTATION.md`](./MULTI_DEVICE_IMPLEMENTATION.md). This document is written so a developer can start coding from it: every requirement has an ID, every API has a payload, every table has DDL, and the client internals are specified down to class level.

---

## Table of Contents

1. [Purpose, scope and conventions](#1-purpose-scope-and-conventions)
2. [Functional requirements](#2-functional-requirements)
3. [Non-functional requirements](#3-non-functional-requirements)
4. [High-level design (HLD)](#4-high-level-design-hld)
5. [Entities and domain model](#5-entities-and-domain-model)
6. [Database schema](#6-database-schema)
7. [API design](#7-api-design)
8. [Low-level design (LLD)](#8-low-level-design-lld)
9. [Security and privacy design](#9-security-and-privacy-design)
10. [Testing strategy](#10-testing-strategy)
11. [Delivery plan](#11-delivery-plan)
12. [Risks and open questions](#12-risks-and-open-questions)
13. [Requirement traceability](#13-requirement-traceability)

---

## 1. Purpose, scope and conventions

### 1.1 Purpose

The VIRA server (a family PC, mini-server or Raspberry Pi) is a private, local-first AI runtime. The **Family Client** is the app each family member installs on their phone, tablet or laptop. It lets a household:

- keep **notes, checklists and shared lists** that sync between members,
- get **reminders and notifications**,
- **chat with VIRA**, grounded in the household's own notes,
- do all of this **offline-first** and **at zero running cost to the user** (the family owns the server; no paid cloud is required).

### 1.2 Goals and non-goals

| Goals | Non-goals (v1) |
|---|---|
| Fully usable offline; sync is background work | Real-time co-editing of one note (no CRDT) |
| One codebase for Android, iOS, iPadOS, Linux, web | Public cloud-hosted VIRA ("VIRA Cloud") |
| Free connectivity paths (LAN, free VPN/tunnel) | End-to-end encryption between members (see §9.6, planned) |
| Minimal data capture; everything opt-in and visible | Screen, keystroke or contact harvesting |
| Hindi + English from day one; i18n-ready | Calendar/e-mail integrations (v2) |
| Small, understandable server additions | Replacing the existing VIRA web dashboard |

### 1.3 Personas

| Persona | Needs | Typical device |
|---|---|---|
| **Household admin** (e.g. parent who runs the server) | Add/remove members, set roles, see server status | Laptop + phone |
| **Adult member** | Notes, lists, reminders, chat | Android/iOS phone |
| **Child member** | Limited sharing, safe chat, reminders assigned to them | Low-end Android phone/tablet |
| **Guest** | View one shared notebook/list | Browser (web client) |

### 1.4 Conventions used in this document

- **Requirement priority:** `Must` / `Should` / `Could`. **Release:** `v1` (MVP) or `v2`.
- **API status tags:** `[EXISTING]` already in the VIRA server, `[EXTEND]` exists but needs change, `[NEW]` must be built.
- **Identifiers:** all new entities use client-generatable **UUIDv7** strings (time-ordered), so records can be created offline. Users keep their existing `public_id`.
- **Timestamps:** UTC, ISO-8601 with `Z` in JSON; stored as `TEXT` ISO-8601 on the server and as epoch **milliseconds** (`INTEGER`) in the client DB.
- **Base path:** `/api/v1`. Errors use the existing envelope `{ "detail": "...", "error": { "code", "message", "correlation_id" } }`.
- Code samples are Dart 3 / Flutter 3.x and Python 3.11 / FastAPI, matching the existing code base. Package names are **suggestions; verify current versions** before pinning.

### 1.5 What the current server already gives us

| Capability | Existing endpoint / module | Use in client |
|---|---|---|
| Device enrollment, hashed credentials shown once | `POST /api/v1/devices` | Pairing |
| Device heartbeat | `POST /api/v1/devices/{id}/heartbeat` | Presence, version reporting |
| Per-user filtered SSE | `GET /api/v1/stream` | Realtime "something changed" hints |
| Streaming chat (NDJSON) | `POST /chat/stream` | VIRA chat UI |
| Conversations / messages with `Idempotency-Key` | `/api/v1/conversations/{id}/messages` | Chat history |
| Scoped memories | `/memories` | Grounding for chat |
| Typed principals, audit log, user admin | `auth/*`, `/api/v1/admin/*` | Roles, audit |
| Correlation IDs, cursor pagination | `api/deps.py` | All new APIs |

### 1.6 What is missing (drives the server work in §7.10)

1. No **household / family** concept (access is per *device*, not per content).
2. No **notes, checklists, reminders** entities and no **sync** protocol.
3. Mobile **auth is cookie-based**; device credentials only carry scopes `events:write` and `heartbeat`.
4. No **attachment** upload/download API.
5. No **push notification** path.
6. The event allow-list rejects `user.*` / `agent.*` events by design, so note content must **not** travel as events.

---

## 2. Functional requirements

### 2.1 Onboarding, pairing and session

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-01 | The app opens a setup screen on first launch with two choices: "Join my family's VIRA" (scan QR / enter code) and "Set up a new server" (instructions + link). | Must | v1 |
| CFR-02 | A user can pair by scanning a QR code or typing a short pairing code plus a server address. | Must | v1 |
| CFR-03 | Pairing registers the phone as a **device** owned by the user and stores its credential only in OS secure storage. | Must | v1 |
| CFR-04 | The QR payload contains one or more server endpoints, the server TLS certificate fingerprint, a one-time code and a protocol version; the app validates all of them before connecting. | Must | v1 |
| CFR-05 | The app keeps the user signed in using short-lived access tokens plus a rotating refresh token; the user never retypes a password on the phone. | Must | v1 |
| CFR-06 | A user can view the devices they have paired, rename them and revoke any of them (including the current one). | Should | v1 |
| CFR-07 | If the server revokes the device or user, the app locks, offers "export my local notes", then wipes server-derived data on confirmation. | Must | v1 |
| CFR-08 | App-lock (biometric/PIN) can be enabled per device. | Should | v1 |

### 2.2 Households and members

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-10 | A user belongs to one or more households; the UI shows one *active* household at a time with a switcher. | Must | v1 |
| CFR-11 | Roles are `admin`, `adult`, `child`, `guest`. The role matrix in §9.3 is enforced by the server and mirrored in the UI (hidden/disabled actions). | Must | v1 |
| CFR-12 | An admin can generate a pairing code for a new member with a chosen role and expiry (default 15 min, single use). | Must | v1 |
| CFR-13 | An admin can change a member's role or remove the member. Removal purges that member's local copy on their next sync. | Must | v1 |
| CFR-14 | Members see who else is in the household and who last edited a shared item. | Should | v1 |
| CFR-15 | A member can leave a household. | Should | v1 |

### 2.3 Notes and notebooks

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-20 | Create, edit, pin, archive, delete and restore (30-day trash) notes while offline. | Must | v1 |
| CFR-21 | Notes live in **notebooks**. Each notebook has visibility `private`, `household` or `custom` (shared with named members, each `view` or `edit`). | Must | v1 |
| CFR-22 | Note body is lightweight Markdown (headings, bold/italic, lists, links). Max 100 KB. | Must | v1 |
| CFR-23 | Tags, colour and pin; list sorted by pinned then last-edited. | Should | v1 |
| CFR-24 | Full-text search across all locally available notes, offline. | Must | v1 |
| CFR-25 | Show "last edited by X on device Y" and a version indicator for shared notes. | Should | v1 |
| CFR-26 | When a conflicting edit is detected the app keeps both: the server version stays, the local version becomes a visible *conflict copy* the user can merge or delete. | Must | v1 |
| CFR-27 | Export a notebook as Markdown/ZIP. | Could | v2 |

### 2.4 Checklists and shared lists

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-30 | A note can be of kind `checklist`. Items are independent rows (add, edit, reorder, check, delete). | Must | v1 |
| CFR-31 | Two members editing different items of the same list never conflict. | Must | v1 |
| CFR-32 | Items can be assigned to a member. "Assigned to me" is a filtered view. | Should | v1 |
| CFR-33 | Checked items move to a collapsible "Done" section; "clear done" is one tap. | Should | v1 |
| CFR-34 | Pre-built templates: Groceries, Packing, Chores. | Could | v1 |

### 2.5 Reminders

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-40 | Create reminders with title, due date/time, time zone and optional repeat rule (daily/weekly/monthly/custom RRULE). | Must | v1 |
| CFR-41 | A reminder is assigned to one member or to "everyone". Each assignee completes it independently. | Must | v1 |
| CFR-42 | Reminders fire as **local notifications scheduled on the device**, so they work offline and with no server. | Must | v1 |
| CFR-43 | Snooze (10 min / 1 h / tomorrow) and "mark done" actions directly from the notification. | Must | v1 |
| CFR-44 | A reminder can link to a note or list item. | Should | v1 |
| CFR-45 | Reminders are rescheduled after device reboot, time-zone change and app update. | Must | v1 |

### 2.6 Attachments

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-50 | Attach photos, PDFs and voice notes to a note. Default max 25 MB (server-configurable, never above the tunnel limit advertised by the server). | Must | v2 |
| CFR-51 | Uploads are resumable, run in the background and are retried; downloads are lazy and cached with an LRU limit. | Must | v2 |
| CFR-52 | Thumbnails are generated on the device before upload. | Should | v2 |
| CFR-53 | Scan a paper document to PDF with on-device edge detection. | Could | v2 |

### 2.7 Sync and offline

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-60 | All reads come from the local database; all writes go to the local database first and into a durable **outbox**. | Must | v1 |
| CFR-61 | Sync is triggered by: app foreground, local change (debounced), server hint (SSE or push), connectivity regained, and a periodic background job. | Must | v1 |
| CFR-62 | Every pushed operation carries a client-generated `op_id`; retries are idempotent. | Must | v1 |
| CFR-63 | Pull is cursor-based and resumable; the client can recover from an expired/compacted cursor by re-bootstrapping. | Must | v1 |
| CFR-64 | The UI always shows sync state per item (synced / pending / conflict / failed) and globally (online, offline, syncing). | Must | v1 |
| CFR-65 | Losing access to a notebook removes its content from the device on the next sync (`forget` change). | Must | v1 |

### 2.8 Notifications

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-70 | Categories: `reminder_due` (local), `assigned_to_you`, `list_updated`, `note_shared`, `member_joined`, `vira_suggestion`, `system`. Each category can be toggled per household. | Must | v1 |
| CFR-71 | Server-originated alerts use a **content-free wake-up push**; the app then syncs and builds the visible notification locally. | Must | v1 |
| CFR-72 | Quiet hours per user; reminders marked *urgent* may bypass them. | Should | v1 |
| CFR-73 | Notification taps deep-link to the exact note, list item or chat. | Must | v1 |
| CFR-74 | Android users without Google services can use UnifiedPush/ntfy as an alternative provider. | Could | v2 |

### 2.9 Chat with VIRA

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-80 | Chat UI streams the agent's progress (status, tool use) and final answer from `/chat/stream`. | Must | v1 |
| CFR-81 | Chat can be **grounded** in the active household's notes the user is allowed to see (server-side retrieval; the client sends `household_id` only). | Must | v1 |
| CFR-82 | Chat history is browsable offline (read-only); sending requires connectivity. Drafts are kept. | Must | v1 |
| CFR-83 | VIRA may *propose* a reminder, note or list item; the user must approve before it is created. | Should | v2 |
| CFR-84 | Voice dictation into the chat and note editor (on-device speech recognition where available). | Should | v1 |
| CFR-85 | Child accounts use a restricted chat profile enforced by the server. | Should | v2 |

### 2.10 Share sheet, settings, privacy and data control

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-90 | The app registers as a share target: text, links and images shared from other apps become a new note in a chosen notebook. | Must | v1 |
| CFR-91 | A "Privacy" screen lists exactly what the app stores and sends, with per-signal toggles (see the data table in §2.10). | Must | v1 |
| CFR-92 | Optional signals (location, calendar) are **off** by default and require an explicit, revocable opt-in. | Must | v1 |
| CFR-93 | The user can export all their data and delete their account's data from the server (admin approval for last-admin). | Should | v1 |
| CFR-94 | Diagnostics logs are local only, redacted, and shared only when the user taps "Send logs". | Should | v1 |

**Data the client may capture**

| Category | Examples | Default | Leaves device? |
|---|---|---|---|
| Authored content | Notes, checklist items, reminders | On | Yes, to the family server |
| Chat | Prompts and answers | On | Yes, to the family server (and to the LLM provider the server is configured with) |
| Attachments | Photos, PDFs, voice notes | Only when added | Yes, to the family server |
| Device state | Client version, OS version, queue size, capability status | On | Yes (heartbeat) |
| Optional signals | Location ("home"), calendar read | **Off** | Only if enabled |
| Analytics / ad IDs / contacts / screenshots / keystrokes | — | **Never collected** | — |

### 2.11 Connectivity

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-95 | The app stores an ordered list of server endpoints (LAN, VPN, tunnel) and always uses the best reachable one. | Must | v1 |
| CFR-96 | LAN discovery via mDNS (`_vira._tcp`) when the stored LAN address changes. | Should | v1 |
| CFR-97 | The app works behind proxies that break SSE by falling back to long-polling. | Must | v1 |
| CFR-98 | A diagnostics screen shows each endpoint, latency, last error and TLS fingerprint status. | Should | v1 |

### 2.12 Localization and accessibility

| ID | Requirement | Priority | Rel. |
|---|---|---|---|
| CFR-99 | UI strings are externalised (ARB). v1 ships English and Hindi; adding a language requires no code change. | Must | v1 |
| CFR-100 | Supports system font scaling up to 200%, screen readers (TalkBack/VoiceOver), minimum 48 dp touch targets and WCAG AA contrast, light and dark themes. | Must | v1 |

---

## 3. Non-functional requirements

| ID | Category | Requirement / target |
|---|---|---|
| CNFR-01 | Offline | 100% of read and write features in §2.3–2.5 work with no network. |
| CNFR-02 | Startup | Cold start to first interactive frame ≤ 2.0 s on a 3 GB RAM / mid-range Android device; ≤ 1.0 s warm. |
| CNFR-03 | Responsiveness | Local queries ≤ 50 ms p95 for 10 000 notes; scrolling at 60 fps (no jank > 16 ms in lists of 1 000 items). |
| CNFR-04 | Sync latency | Change visible on another online member's device ≤ 3 s on LAN, ≤ 10 s over VPN/tunnel, when SSE or push is available. |
| CNFR-05 | Sync efficiency | Idle app generates no network traffic other than the SSE/long-poll connection and heartbeat (≤ 1 per 5 min). Pull of 100 changes ≤ 100 KB. |
| CNFR-06 | Battery | No foreground service. Background work only via OS-scheduled jobs (≥ 15 min period) and push wake-ups. |
| CNFR-07 | Size | Android APK/AAB download ≤ 40 MB (arm64 split); iOS ≤ 60 MB. |
| CNFR-08 | Platforms | Android 8.0+ (API 26), iOS/iPadOS 15+, Linux (x64, GTK/Wayland and X11), evergreen browsers (Chromium, Firefox, Safari 16+). |
| CNFR-09 | Reliability | No acknowledged local write is ever lost: durable outbox survives crash, kill and reboot. Sync is at-least-once with idempotent apply (effectively exactly-once). |
| CNFR-10 | Consistency | Eventual consistency; all replicas converge after quiescence. Per-entity versions are monotonic. |
| CNFR-11 | Security | TLS or WireGuard on every non-LAN hop; certificate pinning on LAN HTTPS; secrets only in Keychain/Keystore; local DB encrypted (SQLCipher) on mobile/desktop. |
| CNFR-12 | Privacy | Data minimisation per §2.10; no third-party SDKs that collect analytics; push payloads contain no user content. |
| CNFR-13 | Observability | Every API call carries `X-Correlation-ID`; client keeps a 2 MB redacted ring-buffer log; sync status is inspectable in the diagnostics screen. |
| CNFR-14 | Compatibility | Client sends `X-Vira-Client: flutter/<semver> proto/<int>`. Server supports the current and previous protocol version; older clients get a clear "update required" screen. |
| CNFR-15 | Limits | Note body ≤ 100 KB; ≤ 200 ops per push; ≤ 500 changes per pull page; household ≤ 12 members; attachment ≤ 25 MB default. |
| CNFR-16 | Accessibility | WCAG 2.1 AA; all interactive elements labelled for screen readers. |
| CNFR-17 | Testability | ≥ 80% line coverage on `domain/` and `data/sync/`; deterministic clock and ID generator injectable everywhere. |
| CNFR-18 | Maintainability | Feature-first layered architecture (§8.1); no feature imports another feature's `presentation/` code; lints enforced in CI. |
| CNFR-19 | Cost | Zero mandatory recurring cost for the family. Any shared service (push gateway) must run within free tiers at the target scale of a few thousand households. |
| CNFR-20 | Upgradability | Local DB migrations are forward-only, tested from every released schema version; a failed migration never deletes user data (backup copy first). |

---
## 4. High-level design (HLD)

### 4.1 System context

```mermaid
flowchart LR
    subgraph Family["Family devices (Flutter app)"]
        A1["Phone (Android/iOS)"]
        A2["Tablet / iPad"]
        A3["Laptop (Linux)"]
        A4["Browser (web)"]
    end

    subgraph Home["Home network"]
        S["VIRA server<br/>(FastAPI + kernel + agents)"]
        DB[("SQLite WAL<br/>data/vira.sqlite3")]
        FS[("Attachment store<br/>data/attachments/")]
        LLM["LLM (Ollama / optional cloud)"]
        S --- DB
        S --- FS
        S --- LLM
    end

    subgraph Free["Free connectivity (user's choice)"]
        TS["Tailscale (WireGuard mesh)"]
        CF["Cloudflare named tunnel"]
    end

    PG["Push gateway (stateless, content-free)"]
    FCM["FCM / APNs"]

    A1 -- "LAN (mDNS + pinned TLS)" --> S
    A1 -. "VPN / tunnel" .-> TS
    A1 -. "tunnel" .-> CF
    TS --> S
    CF --> S
    S -- "wake-up (opaque handle)" --> PG
    PG --> FCM
    FCM -- "silent push" --> A1
```

**Key ideas**

1. The client is a **replica**, not a thin UI. The server is the **authority** (it assigns versions, enforces permissions, decides conflicts).
2. The only component that a project maintainer operates is the **push gateway** (stateless, free-tier). Everything else is owned by the family.
3. Content never goes through the push gateway or through FCM/APNs.

### 4.2 Logical architecture of the client

```mermaid
flowchart TB
    subgraph UI["Presentation (Flutter widgets, Riverpod notifiers)"]
        F1[Onboarding / Pairing]
        F2[Notes & Notebooks]
        F3[Lists]
        F4[Reminders]
        F5[Household]
        F6[Chat]
        F7[Settings / Privacy / Diagnostics]
    end

    subgraph Domain["Domain (pure Dart)"]
        E[Entities]
        UC[Use cases]
        RI[Repository interfaces]
    end

    subgraph Data["Data"]
        REPO[Repository implementations]
        LDB[("Local DB (drift + SQLCipher)")]
        OUT[Outbox]
        SYNC[Sync engine]
        API["API client (dio)"]
        TR[Transport manager]
        SEC[Secure storage]
    end

    subgraph Platform["Platform services"]
        NOTI[Notification service]
        PUSH[Push receiver]
        BG[Background scheduler]
        SHARE[Share receiver]
        VOICE[Speech-to-text]
        SCAN[QR scanner]
        MDNS[mDNS discovery]
    end

    UI --> UC --> RI
    REPO -. implements .-> RI
    REPO --> LDB
    REPO --> OUT
    SYNC --> OUT
    SYNC --> LDB
    SYNC --> API
    API --> TR
    API --> SEC
    PUSH --> SYNC
    BG --> SYNC
    SHARE --> UC
    NOTI --> LDB
    TR --> MDNS
    F1 --> SCAN
    F6 --> VOICE
```

Dependency rule: **UI → Domain ← Data**. `domain/` imports nothing from Flutter, drift or dio.

### 4.3 Technology choices

| Concern | Choice | Why / alternatives |
|---|---|---|
| UI framework | Flutter 3.x, Dart 3, Material 3 | One codebase for all target platforms |
| State management | `flutter_riverpod` (+ `riverpod_generator`) | Testable, compile-time safe DI; alt: Bloc |
| Navigation | `go_router` | Deep links from notifications, web URLs |
| Local DB | `drift` over SQLite; `sqlcipher_flutter_libs` on mobile/desktop; drift WASM/IndexedDB on web | Typed queries, migrations, FTS5, streams |
| HTTP | `dio` + custom interceptors | Interceptors, cancellation, adapters for pinning |
| Models | `freezed` + `json_serializable` | Immutable, union types |
| Secure storage | `flutter_secure_storage` (Keychain/Keystore/libsecret) | Web: see §9.5 |
| Local notifications | `flutter_local_notifications` + `timezone` | Scheduled reminders |
| Push | `firebase_messaging` (FCM, iOS via APNs) behind a `PushProvider` interface; UnifiedPush later | Free; content-free payloads |
| Background | `workmanager` (Android WorkManager / iOS BGTaskScheduler) | OS-scheduled, battery-friendly |
| QR | `mobile_scanner` | Pairing |
| LAN discovery | `multicast_dns` / `nsd` | `_vira._tcp` |
| Share target | `receive_sharing_intent` (or platform channel) | Share-sheet notes |
| Speech | `speech_to_text` | On-device where available |
| Recurrence | `rrule` package | RFC 5545 parsing |
| IDs | `uuid` (v7) | Offline creation |
| Localization | `flutter_localizations`, `intl`, ARB | EN + HI |
| Logging | `logger` wrapper with redaction | Ring buffer |

### 4.4 Platform capability matrix

| Capability | Android | iOS/iPadOS | Linux | Web |
|---|---|---|---|---|
| Local encrypted DB | Yes | Yes | Yes | Not encrypted at rest (IndexedDB) |
| Secure credential storage | Keystore | Keychain | libsecret | Session cookie only (§9.5) |
| mDNS LAN discovery | Yes | Yes (needs local-network permission) | Yes | **No** (user enters URL) |
| LAN over HTTPS (pinned self-signed cert) | Yes | Yes (Local Network permission) | Yes | **No** (browsers cannot pin; needs a public certificate) |
| Scheduled local notifications | Yes (exact alarm permission) | Yes (**64 pending cap**) | Basic | No (use web push, v2) |
| Push | FCM / UnifiedPush | APNs via FCM | None | Web Push (v2) |
| Background sync | WorkManager | BGTaskScheduler (best-effort) | App running | None |
| Share target | Yes | Share extension | No | Web Share Target (v2) |
| QR scan | Yes | Yes | Webcam/Enter code | Webcam/Enter code |

**Consequence:** the web client is a *secondary* client (admin and guest use). It requires an HTTPS endpoint (Tailscale `ts.net` HTTPS or a named tunnel) and does not do background reminders.

### 4.5 Key runtime flows

**Write path (local-first)**

```mermaid
sequenceDiagram
    participant U as User
    participant UI as UI / Notifier
    participant R as Repository
    participant DB as Local DB
    participant O as Outbox
    participant S as SyncEngine
    participant API as Server

    U->>UI: Edit note
    UI->>R: updateNote(id, patch)
    R->>DB: BEGIN TX, update note (sync_state=pending)
    R->>O: insert op(op_id, upsert, base_version)
    R->>DB: COMMIT
    R-->>UI: Stream emits updated note (instant)
    R->>S: requestSync(reason=localChange)
    S->>API: POST /sync/push {ops}
    API-->>S: results (applied / conflict / duplicate)
    S->>DB: mark synced, store new version
```

**Remote change path**

```mermaid
sequenceDiagram
    participant Other as Other member
    participant API as Server
    participant PG as Push gateway
    participant App as This app
    participant S as SyncEngine

    Other->>API: POST /sync/push
    API->>API: append sync_changes (seq N)
    API-->>App: SSE sync.changed {latest_seq}
    API-->>PG: wake-up (if app not connected)
    PG-->>App: silent push
    App->>S: requestSync(reason=hint)
    S->>API: GET /sync/changes?cursor=N-1
    API-->>S: changes[]
    S->>S: apply in one transaction, schedule reminders, raise notifications
```

### 4.6 Connectivity architecture

The client keeps an **ordered endpoint list** (from the pairing QR, editable in settings):

```json
[
  {"kind": "lan",       "url": "https://192.168.1.20:8443", "priority": 10},
  {"kind": "tailscale", "url": "https://vira-home.tail1234.ts.net", "priority": 20},
  {"kind": "tunnel",    "url": "https://vira.example.com", "priority": 30}
]
```

`TransportManager` probes `GET /health` on each (parallel, 1.5 s timeout), picks the lowest-priority-number reachable endpoint, keeps it until it fails or the network changes, and re-probes on connectivity change. All HTTP clients obtain their base URL from the manager; no feature code knows about endpoints.

| Path | Cost to family | When to use | Notes |
|---|---|---|---|
| LAN | Free | At home | mDNS + pinned self-signed cert |
| Tailscale | Free personal plan (non-commercial; check current user limit) | Away from home | Each member installs the Tailscale app; HTTPS via `tailscale serve` |
| Cloudflare **named** tunnel | Free service; needs a domain on Cloudflare DNS | Away from home, no extra app | Quick tunnels (`trycloudflare.com`) lack SSE and have rotating URLs, so use them for demos only |
| Long-poll fallback | Free | Any proxy that breaks SSE | `GET /api/v1/sync/wait` |

The honest limit: truly zero-config remote access needs a relay someone pays for. v1 deliberately avoids that; a hosted relay can later be added as another `kind` without client changes.

### 4.7 Notification architecture

```mermaid
flowchart LR
    subgraph Local["On device (free, offline)"]
        R1[Reminder rows] --> SCH[Reminder scheduler] --> LN[Local notifications]
    end
    subgraph Remote["Server-originated"]
        EV[Server event e.g. item assigned] --> NS[Notification service]
        NS --> PGW[Push gateway]
        PGW --> FCMX[FCM / APNs]
        FCMX --> WAKE[Silent wake-up in app]
        WAKE --> SYNCX[Sync] --> BUILD[Build visible notification locally]
    end
```

- **Reminders never depend on push.** They are scheduled locally from synced reminder rows.
- **Wake-up payload** is `{ "t": "sync" }` plus a collapse key. No titles, names or content.
- The push gateway stores only `push_handle → (provider, token)`; it never sees user IDs or household data (API in §7.8).

### 4.8 Deployment view

| Unit | Runs on | Owner | Notes |
|---|---|---|---|
| Flutter app | Each family device | Family | Distributed via stores, F-Droid/APK, AppImage, web build served by the VIRA server |
| VIRA server + new modules | Family PC / Pi | Family | AppImage/Docker already exist |
| Tunnel/VPN agent | Family server | Family | Optional |
| Push gateway | Free-tier serverless (e.g. an edge-function platform) | Project maintainers | Stateless + tiny KV store |

### 4.9 Architectural decisions (ADR summary)

| # | Decision | Rationale | Consequence |
|---|---|---|---|
| ADR-1 | Local-first replica with outbox + cursor sync | Offline, instant UI, tolerates a home server that is off | Need conflict policy and versioning |
| ADR-2 | Sync is the **only** write path for notes/lists/reminders (attachment *creation* is the one REST exception, §7.6) | One code path to test; idempotent | Web client uses the same path |
| ADR-3 | Server assigns entity `version` and change `seq` | No client-clock trust | Clients must send `base_version` |
| ADR-4 | Checklist items are separate rows | Avoids conflicts inside lists | More rows, more ops |
| ADR-5 | Note body conflicts keep both versions (conflict copy) | Never lose text; no CRDT complexity | Occasional manual merge |
| ADR-6 | Reminders scheduled **locally** | Offline, free, reliable | iOS 64-notification cap handled with a rolling window |
| ADR-7 | Content-free push via a shared gateway | Each family cannot own a Firebase project | One small shared service to run |
| ADR-8 | Device credential → short-lived **access token** | Existing credentials have too-narrow scopes; limits blast radius | New token endpoints |
| ADR-9 | Transport abstraction with ordered endpoints | Free paths differ per family | Probing logic and diagnostics UI |
| ADR-10 | Riverpod + repository interfaces in `domain/` | Testability | Slightly more boilerplate |

---
## 5. Entities and domain model

### 5.1 Entity relationship diagram (domain level)

```mermaid
erDiagram
    USER ||--o{ HOUSEHOLD_MEMBER : "is"
    HOUSEHOLD ||--o{ HOUSEHOLD_MEMBER : has
    HOUSEHOLD ||--o{ NOTEBOOK : contains
    NOTEBOOK ||--o{ NOTEBOOK_SHARE : "shared via"
    USER ||--o{ NOTEBOOK_SHARE : receives
    NOTEBOOK ||--o{ NOTE : contains
    NOTE ||--o{ CHECKLIST_ITEM : "has (kind=checklist)"
    NOTE ||--o{ ATTACHMENT : has
    HOUSEHOLD ||--o{ REMINDER : has
    REMINDER ||--o{ REMINDER_COMPLETION : "completed per user"
    USER ||--o{ DEVICE : owns
    DEVICE ||--o{ PUSH_REGISTRATION : has
    DEVICE ||--o{ CLIENT_TOKEN : "authenticates with"
    HOUSEHOLD ||--o{ PAIRING_CODE : issues
    HOUSEHOLD ||--o{ SYNC_CHANGE : logs
    USER ||--o{ CONVERSATION : owns
    CONVERSATION ||--o{ MESSAGE : contains
```

`USER`, `DEVICE`, `CONVERSATION` and `MESSAGE` already exist in the server schema. All other entities are **[NEW]**.

### 5.2 Entity catalogue

| Entity | Synced to client? | Owner of truth | Key rules |
|---|---|---|---|
| `Household` | Yes (read-only) | Server | Name ≤ 60 chars; ≥ 1 `admin` at all times |
| `HouseholdMember` | Yes (read-only) | Server | Unique `(household_id, user_id)`; role ∈ `admin, adult, child, guest` |
| `Notebook` | Yes | Server | `visibility` ∈ `private, household, custom`; owner can always edit |
| `NotebookShare` | Yes | Server | Only for `custom` visibility; permission ∈ `view, edit` |
| `Note` | Yes | Server | `kind` ∈ `note, checklist`; body ≤ 100 KB; soft-delete (trash 30 d) |
| `ChecklistItem` | Yes | Server | Belongs to a `checklist` note; `position` is a fractional-index string |
| `Reminder` | Yes | Server | `due_at` UTC + IANA `timezone`; optional `rrule`; assignee may be null (= everyone) |
| `ReminderCompletion` | Yes | Server | One row per `(reminder_id, user_id, occurrence_at)` |
| `Attachment` | Metadata yes, bytes on demand | Server | `sha256` verified; size ≤ server limit |
| `Device` | Own devices only | Server | Existing entity; gains `client_kind` and push registration |
| `PairingCode` | No | Server | Single-use, hashed, expires (default 15 min) |
| `ClientToken` | No | Server | Access (15 min) and refresh (30 d, rotating) tokens, hashed |
| `PushRegistration` | No | Server | Provider + opaque handle; never contains content |
| `SyncChange` | Via pull API | Server | Append-only change log; basis of cursors |
| `OutboxOp` | Client only | Client | Durable queue of pending writes |
| `Conversation` / `Message` | Cached read-only | Server | Existing entities |

### 5.3 Common fields on synced entities

| Field | Type | Meaning |
|---|---|---|
| `id` | UUIDv7 string | Created by the client; unique globally |
| `household_id` | UUIDv7 | Scoping and permission anchor |
| `version` | integer ≥ 1 | Assigned by the server; increments on every accepted change |
| `created_at`, `updated_at` | UTC time | `updated_at` is server time |
| `deleted_at` | UTC time or null | Soft delete (tombstone) |
| `updated_by_user_id`, `updated_by_device_id` | ids | Provenance for UI ("last edited by…") |

### 5.4 Enumerations

| Enum | Values |
|---|---|
| `Role` | `admin`, `adult`, `child`, `guest` |
| `NotebookVisibility` | `private`, `household`, `custom` |
| `SharePermission` | `view`, `edit` |
| `NoteKind` | `note`, `checklist` |
| `ReminderStatus` | `active`, `done`, `cancelled` |
| `EntityType` | `household`, `member`, `notebook`, `notebook_share`, `note`, `checklist_item`, `reminder`, `reminder_completion`, `attachment` |
| `ChangeOp` | `upsert`, `delete`, `forget` |
| `SyncState` (client) | `synced`, `pending`, `conflict`, `failed` |
| `PushProvider` | `fcm`, `unifiedpush`, `ntfy` (APNs is reached through FCM) |
| `EndpointKind` | `lan`, `tailscale`, `tunnel`, `custom` |

### 5.5 State machines

**Device pairing**

```mermaid
stateDiagram-v2
    [*] --> Unpaired
    Unpaired --> Scanning: tap Join
    Scanning --> Validating: QR/code read
    Validating --> Redeeming: endpoint + fingerprint OK
    Validating --> Unpaired: invalid / expired
    Redeeming --> Bootstrapping: credential + tokens stored
    Redeeming --> Unpaired: code used / rejected
    Bootstrapping --> Ready: first sync complete
    Ready --> Locked: device revoked / user disabled
    Locked --> Unpaired: wipe confirmed
```

**Outbox operation**

```mermaid
stateDiagram-v2
    [*] --> Queued
    Queued --> InFlight: batch selected
    InFlight --> Done: applied / duplicate
    InFlight --> Queued: network error (backoff)
    InFlight --> Conflict: base_version mismatch
    InFlight --> Failed: rejected (validation / permission)
    Conflict --> Done: conflict copy created
    Failed --> [*]: user dismisses or edits
    Done --> [*]
```

**Note lifecycle:** `active → archived ↔ active`, `active → trashed (deleted_at set) → purged after 30 d` (server job) or `→ active` (restore).

---

## 6. Database schema

### 6.1 Server schema [NEW] (SQLite, WAL; add as a versioned migration in `auth/migrations.py`)

```sql
-- ===== Households ==========================================================
CREATE TABLE households (
  id                 TEXT PRIMARY KEY,                 -- UUIDv7
  name               TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  created_by_user_id INTEGER NOT NULL REFERENCES users(id),
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  deleted_at         TEXT
);

CREATE TABLE household_members (
  household_id TEXT NOT NULL REFERENCES households(id),
  user_id      INTEGER NOT NULL REFERENCES users(id),
  role         TEXT NOT NULL CHECK (role IN ('admin','adult','child','guest')),
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed')),
  display_name TEXT,
  joined_at    TEXT NOT NULL,
  removed_at   TEXT,
  version      INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (household_id, user_id)
);
CREATE INDEX idx_members_user ON household_members(user_id, status);

CREATE TABLE pairing_codes (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL REFERENCES households(id),
  created_by    INTEGER NOT NULL REFERENCES users(id),
  role          TEXT NOT NULL CHECK (role IN ('admin','adult','child','guest')),
  code_hash     TEXT NOT NULL UNIQUE,                  -- SHA-256 of the code; raw code shown once
  expires_at    TEXT NOT NULL,
  used_at       TEXT,
  used_by_user_id INTEGER REFERENCES users(id),
  used_device_id  TEXT,
  created_at    TEXT NOT NULL
);

-- ===== Tokens for mobile/desktop clients ===================================
CREATE TABLE client_tokens (
  id            TEXT PRIMARY KEY,
  device_id     TEXT NOT NULL,                         -- devices.id
  user_id       INTEGER NOT NULL REFERENCES users(id),
  kind          TEXT NOT NULL CHECK (kind IN ('access','refresh')),
  token_hash    TEXT NOT NULL UNIQUE,
  scopes        TEXT NOT NULL,                         -- space-separated
  expires_at    TEXT NOT NULL,
  revoked_at    TEXT,
  rotated_from  TEXT,                                  -- refresh-token reuse detection
  created_at    TEXT NOT NULL
);
CREATE INDEX idx_tokens_device ON client_tokens(device_id, kind, revoked_at);

-- ===== Content =============================================================
CREATE TABLE notebooks (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL REFERENCES households(id),
  owner_user_id INTEGER NOT NULL REFERENCES users(id),
  title         TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 100),
  color         TEXT,
  visibility    TEXT NOT NULL DEFAULT 'household'
                CHECK (visibility IN ('private','household','custom')),
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT,
  updated_by_user_id   INTEGER,
  updated_by_device_id TEXT
);
CREATE INDEX idx_notebooks_household ON notebooks(household_id, deleted_at);

CREATE TABLE notebook_shares (
  notebook_id TEXT NOT NULL REFERENCES notebooks(id),
  user_id     INTEGER NOT NULL REFERENCES users(id),
  permission  TEXT NOT NULL CHECK (permission IN ('view','edit')),
  version     INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL,
  deleted_at  TEXT,
  PRIMARY KEY (notebook_id, user_id)
);

CREATE TABLE notes (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL REFERENCES households(id),
  notebook_id   TEXT NOT NULL REFERENCES notebooks(id),
  author_user_id INTEGER NOT NULL REFERENCES users(id),
  kind          TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note','checklist')),
  title         TEXT NOT NULL DEFAULT '' CHECK (length(title) <= 200),
  body_md       TEXT NOT NULL DEFAULT '' CHECK (length(body_md) <= 102400),
  pinned        INTEGER NOT NULL DEFAULT 0,
  archived      INTEGER NOT NULL DEFAULT 0,
  color         TEXT,
  tags_json     TEXT NOT NULL DEFAULT '[]',
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT,
  updated_by_user_id   INTEGER,
  updated_by_device_id TEXT
);
CREATE INDEX idx_notes_notebook ON notes(notebook_id, deleted_at, pinned DESC, updated_at DESC);

CREATE TABLE checklist_items (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL,
  note_id       TEXT NOT NULL REFERENCES notes(id),
  text          TEXT NOT NULL CHECK (length(text) <= 500),
  done          INTEGER NOT NULL DEFAULT 0,
  done_by_user_id INTEGER,
  done_at       TEXT,
  position      TEXT NOT NULL,                         -- fractional index, e.g. 'a0', 'a0V'
  assignee_user_id INTEGER,
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT,
  updated_by_user_id   INTEGER,
  updated_by_device_id TEXT
);
CREATE INDEX idx_items_note ON checklist_items(note_id, deleted_at, position);

CREATE TABLE reminders (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL REFERENCES households(id),
  created_by_user_id INTEGER NOT NULL REFERENCES users(id),
  assignee_user_id   INTEGER,                          -- NULL = everyone
  title         TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  body          TEXT NOT NULL DEFAULT '',
  due_at        TEXT NOT NULL,                         -- UTC of first occurrence
  timezone      TEXT NOT NULL,                         -- IANA, e.g. 'Asia/Kolkata'
  rrule         TEXT,                                  -- RFC 5545, e.g. 'FREQ=WEEKLY;BYDAY=MO'
  urgent        INTEGER NOT NULL DEFAULT 0,
  note_id       TEXT,
  item_id       TEXT,
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','cancelled')),
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT,
  updated_by_user_id   INTEGER,
  updated_by_device_id TEXT
);
CREATE INDEX idx_reminders_household ON reminders(household_id, status, due_at);

CREATE TABLE reminder_completions (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL,
  reminder_id   TEXT NOT NULL REFERENCES reminders(id),
  user_id       INTEGER NOT NULL REFERENCES users(id),
  occurrence_at TEXT NOT NULL,                         -- which occurrence was completed
  completed_at  TEXT NOT NULL,
  version       INTEGER NOT NULL DEFAULT 1,
  deleted_at    TEXT,
  UNIQUE (reminder_id, user_id, occurrence_at)
);

CREATE TABLE attachments (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL,
  note_id       TEXT NOT NULL REFERENCES notes(id),
  owner_user_id INTEGER NOT NULL REFERENCES users(id),
  filename      TEXT NOT NULL,
  mime          TEXT NOT NULL,
  size_bytes    INTEGER NOT NULL,
  sha256        TEXT NOT NULL,
  storage_path  TEXT,                                  -- relative to data/attachments/
  thumb_path    TEXT,
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','failed')),
  uploaded_bytes INTEGER NOT NULL DEFAULT 0,
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT
);

-- ===== Sync ================================================================
CREATE TABLE sync_changes (
  seq            INTEGER PRIMARY KEY AUTOINCREMENT,    -- the cursor
  household_id   TEXT NOT NULL,
  entity_type    TEXT NOT NULL,
  entity_id      TEXT NOT NULL,
  notebook_id    TEXT,                                 -- for per-user visibility filtering
  op             TEXT NOT NULL CHECK (op IN ('upsert','delete','forget')),
  version        INTEGER NOT NULL,
  target_user_id INTEGER,                               -- set only for 'forget' (deliver to one user)
  actor_user_id  INTEGER,
  actor_device_id TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_changes_household_seq ON sync_changes(household_id, seq);
CREATE INDEX idx_changes_entity ON sync_changes(entity_type, entity_id, seq);

CREATE TABLE sync_op_receipts (                         -- idempotency for POST /sync/push
  device_id  TEXT NOT NULL,
  op_id      TEXT NOT NULL,
  status     TEXT NOT NULL,                              -- applied | conflict | rejected
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (device_id, op_id)
);

-- ===== Push / notifications ================================================
CREATE TABLE push_registrations (
  id          TEXT PRIMARY KEY,
  device_id   TEXT NOT NULL,
  user_id     INTEGER NOT NULL REFERENCES users(id),
  provider    TEXT NOT NULL CHECK (provider IN ('fcm','unifiedpush','ntfy')),
  push_handle TEXT NOT NULL,                             -- opaque handle issued by push gateway (or UP endpoint)
  locale      TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  revoked_at  TEXT,
  UNIQUE (device_id, provider)
);

CREATE TABLE notification_prefs (
  user_id      INTEGER NOT NULL REFERENCES users(id),
  household_id TEXT NOT NULL,
  category     TEXT NOT NULL,
  enabled      INTEGER NOT NULL DEFAULT 1,
  quiet_start  TEXT,                                     -- 'HH:MM' local
  quiet_end    TEXT,
  PRIMARY KEY (user_id, household_id, category)
);
```

**Per-user visibility rule for pull (server-side)**

A change row is delivered to user *U* if **any** of:

1. `entity_type IN ('household','member')` and *U* is an active member;
2. its `notebook_id` is visible to *U*: notebook `visibility='household'` and *U* is an active member, **or** *U* owns it, **or** a non-deleted `notebook_shares` row exists for *U*;
3. `op='forget'` and `target_user_id = U`;
4. `entity_type='reminder'` / `'reminder_completion'` and (`assignee_user_id IS NULL` or `= U` or *U* created it).

Guests only receive notebooks explicitly shared with them. Children never receive `private` notebooks of others (this is already covered by rule 2).

### 6.2 Client local schema (drift / SQLite)

Timestamps are epoch **milliseconds**. Every synced table has `sync_state` and `base_version` columns used by the outbox logic.

```sql
CREATE TABLE households (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, my_role TEXT NOT NULL,
  version INTEGER NOT NULL, updated_at INTEGER NOT NULL
);

CREATE TABLE members (
  household_id TEXT NOT NULL, user_id TEXT NOT NULL,       -- user public_id
  display_name TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL,
  version INTEGER NOT NULL,
  PRIMARY KEY (household_id, user_id)
);

CREATE TABLE notebooks (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  title TEXT NOT NULL, color TEXT, visibility TEXT NOT NULL,
  my_permission TEXT NOT NULL,                              -- 'edit' | 'view' (computed on apply)
  version INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  deleted_at INTEGER, sync_state TEXT NOT NULL DEFAULT 'synced'
);

CREATE TABLE notebook_shares (
  notebook_id TEXT NOT NULL, user_id TEXT NOT NULL, permission TEXT NOT NULL,
  version INTEGER NOT NULL, deleted_at INTEGER,
  PRIMARY KEY (notebook_id, user_id)
);

CREATE TABLE notes (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, notebook_id TEXT NOT NULL,
  author_user_id TEXT NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL, body_md TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
  color TEXT, tags_json TEXT NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL DEFAULT 0,                       -- 0 = never synced
  base_version INTEGER NOT NULL DEFAULT 0,                  -- version the local edit started from
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted_at INTEGER,
  updated_by_user_id TEXT, updated_by_device_id TEXT,
  conflict_of TEXT,                                         -- id of original when this is a conflict copy
  sync_state TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX idx_notes_list ON notes(notebook_id, deleted_at, archived, pinned DESC, updated_at DESC);

CREATE VIRTUAL TABLE notes_fts USING fts5(title, body_md, content='notes', content_rowid='rowid');
-- triggers keep notes_fts in sync with notes (insert/update/delete), excluding deleted rows

CREATE TABLE checklist_items (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, note_id TEXT NOT NULL,
  text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, done_by_user_id TEXT, done_at INTEGER,
  position TEXT NOT NULL, assignee_user_id TEXT,
  version INTEGER NOT NULL DEFAULT 0, base_version INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL, deleted_at INTEGER,
  sync_state TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX idx_items_note ON checklist_items(note_id, deleted_at, position);

CREATE TABLE reminders (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, created_by_user_id TEXT NOT NULL,
  assignee_user_id TEXT, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  due_at INTEGER NOT NULL, timezone TEXT NOT NULL, rrule TEXT, urgent INTEGER NOT NULL DEFAULT 0,
  note_id TEXT, item_id TEXT, status TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0, base_version INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL, deleted_at INTEGER, sync_state TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX idx_reminders_due ON reminders(household_id, status, due_at);

CREATE TABLE reminder_completions (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, reminder_id TEXT NOT NULL,
  user_id TEXT NOT NULL, occurrence_at INTEGER NOT NULL, completed_at INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 0, deleted_at INTEGER, sync_state TEXT NOT NULL DEFAULT 'synced',
  UNIQUE (reminder_id, user_id, occurrence_at)
);

CREATE TABLE scheduled_notifications (                      -- what the OS currently has scheduled
  id INTEGER PRIMARY KEY,                                   -- OS notification id
  reminder_id TEXT NOT NULL, occurrence_at INTEGER NOT NULL, fire_at INTEGER NOT NULL
);

CREATE TABLE attachments (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, note_id TEXT NOT NULL,
  filename TEXT NOT NULL, mime TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
  local_path TEXT, thumb_path TEXT,
  transfer_state TEXT NOT NULL DEFAULT 'remote_only',       -- remote_only|downloading|cached|upload_pending|uploading|failed
  transferred_bytes INTEGER NOT NULL DEFAULT 0, last_access_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0, deleted_at INTEGER
);

CREATE TABLE outbox (
  op_id TEXT PRIMARY KEY,                                   -- UUIDv7, also the idempotency key
  seq INTEGER NOT NULL,                                     -- local ordering (autoincrement via separate counter)
  household_id TEXT NOT NULL,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  op TEXT NOT NULL,                                         -- upsert | delete
  base_version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',                    -- queued|in_flight|failed
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, created_at INTEGER NOT NULL
);
CREATE INDEX idx_outbox_ready ON outbox(status, next_attempt_at, seq);

CREATE TABLE sync_state (                                   -- key/value
  key TEXT PRIMARY KEY, value TEXT NOT NULL                 -- 'cursor:<household_id>', 'last_full_sync', ...
);

CREATE TABLE conversations (
  id TEXT PRIMARY KEY, title TEXT, household_id TEXT, updated_at INTEGER NOT NULL
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, sequence_no INTEGER NOT NULL, created_at INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'sent'                        -- draft|sending|sent|failed
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, sequence_no);

CREATE TABLE endpoints (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, url TEXT NOT NULL, priority INTEGER NOT NULL,
  last_ok_at INTEGER, last_latency_ms INTEGER, last_error TEXT
);

CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

**Secrets are never in this DB.** Access/refresh tokens, the device credential and the SQLCipher key live in OS secure storage (§9.5).

### 6.3 Migration policy

- Server: add as the next numbered migration; migrations are idempotent and recorded in `schema_migrations` (existing mechanism).
- Client: drift `schemaVersion` with `MigrationStrategy.stepByStep`; before any migration, copy the DB file to `vira.db.bak-<version>`; keep the last backup until the next successful launch (CNFR-20).
- A change to an API payload is **additive** within a protocol version; breaking changes bump `proto` (CNFR-14).

---
## 7. API design

### 7.1 Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1` |
| Format | JSON (`application/json; charset=utf-8`), except chat stream (`application/x-ndjson`) and attachment bytes |
| Auth | `Authorization: Bearer <access_token>` for the Flutter clients on mobile/desktop. Flutter **web** uses the existing session cookie (`vira_session`) from `POST /api/v1/auth/login`. |
| Client header | `X-Vira-Client: flutter/1.0.0 proto/1` on every request |
| Correlation | Client sends `X-Correlation-ID` (UUID); server echoes it (existing behaviour) |
| Idempotency | Mutating non-sync endpoints accept `Idempotency-Key`; sync ops use `op_id` |
| Pagination | Cursor style: `?limit=50&cursor=<opaque>` → `{ "items": [...], "next_cursor": "..." \| null }` (existing convention) |
| Time | UTC ISO-8601 (`2026-11-04T10:15:30Z`) |
| Errors | `{ "detail": "...", "error": { "code": "sync.cursor_expired", "message": "...", "correlation_id": "..." } }` |
| Compression | `Accept-Encoding: gzip` supported on all JSON responses |
| Limits | See CNFR-15 and `GET /client-config` |

### 7.2 Authentication and pairing

#### 7.2.1 QR payload (what the admin's screen shows)

Encoded as `vira://pair?d=<base64url(JSON)>`:

```json
{
  "v": 1,
  "server_id": "srv_01JC3R8...",
  "name": "Sharma Family",
  "household_id": "0192f6b2-7c1e-7a55-9d3a-5f1c0d6e8a11",
  "code": "7QK4M9XB",
  "endpoints": [
    { "kind": "lan",       "url": "https://192.168.1.20:8443",          "priority": 10 },
    { "kind": "tailscale", "url": "https://vira-home.tail1234.ts.net", "priority": 20 }
  ],
  "cert_sha256": "4F:9A:...:C1"
}
```

The app must refuse the payload if `v` is unknown, `code` is empty, or no endpoint is reachable and matches `cert_sha256` (for self-signed LAN certs) or a valid public certificate (for tunnel/Tailscale HTTPS).

#### 7.2.2 `POST /api/v1/auth/pairing-codes` **[NEW]** — create a pairing code

Requires an authenticated **household admin** (to add a member) or the user themself (to add another device).

Request
```jsonc
{
  "purpose": "join_household",          // "join_household" | "add_device"
  "household_id": "0192f6b2-...",
  "role": "adult",                     // ignored for add_device
  "expires_in_seconds": 900
}
```
Response `201`
```json
{
  "pairing_id": "0192f6c0-...",
  "code": "7QK4M9XB",
  "expires_at": "2026-11-04T10:30:00Z",
  "qr_payload": "vira://pair?d=eyJ2IjoxLC4uLn0"
}
```
The raw code is shown once; only its SHA-256 is stored (`pairing_codes.code_hash`).

#### 7.2.3 `POST /api/v1/auth/pairing/redeem` **[NEW]** — unauthenticated, rate-limited

Request
```jsonc
{
  "code": "7QK4M9XB",
  "user": { "display_name": "Anita" },            // required for join_household, ignored for add_device
  "device": {
    "display_name": "Anita's Pixel 8",
    "platform": "android",                        // android | ios | linux | web
    "device_type": "phone",                       // phone | tablet | laptop | browser
    "os_version": "15",
    "client_version": "1.0.0",
    "capabilities": ["notes", "reminders", "push.fcm"]
  }
}
```
Response `201`
```json
{
  "server": { "id": "srv_01JC3R8...", "name": "Sharma Family", "protocol": 1, "time": "2026-11-04T10:16:02Z" },
  "user": { "public_id": "usr_8f2a...", "display_name": "Anita", "platform_role": "member" },
  "household": { "id": "0192f6b2-...", "name": "Sharma Family", "role": "adult" },
  "device": { "id": "dev_5c21...", "display_name": "Anita's Pixel 8" },
  "device_credential": { "credential_id": "cred_77...", "token": "vdc_live_...", "expires_at": "2027-11-04T10:16:02Z" },
  "tokens": {
    "token_type": "Bearer",
    "access_token": "vat_...", "expires_in": 900,
    "refresh_token": "vrt_...", "refresh_expires_in": 2592000
  }
}
```
Errors: `pairing.invalid_code` (404), `pairing.expired` (410), `pairing.used` (409), `rate_limited` (429).

Server behaviour: in one transaction mark the code used, create the user (if `join_household`: passwordless, `status=active`), add `household_members`, register the device via the existing `DeviceService.register`, and issue tokens.

#### 7.2.4 `POST /api/v1/auth/token` **[NEW]** — refresh / re-authenticate

```json
{ "grant_type": "refresh_token", "refresh_token": "vrt_..." }
```
or, if the refresh token was lost or expired:
```json
{ "grant_type": "device_credential", "device_id": "dev_5c21...", "credential": "vdc_live_..." }
```
Response `200`: same `tokens` object as above. Refresh tokens **rotate**: the old one is revoked and linked via `rotated_from`. Presenting an already-rotated refresh token is treated as theft: the whole token family for that device is revoked and the response is `401 auth.token_reuse`.

Scopes granted: `sync:read sync:write chat attachments devices:self households:read`, plus `households:admin` when the user is a household admin.

#### 7.2.5 Existing auth endpoints

| Endpoint | Status | Client use |
|---|---|---|
| `GET /api/v1/auth/me` | **[EXTEND]** | Also return `memberships[]` and current `device` |
| `POST /api/v1/auth/login`, `/logout` | [EXISTING] | Flutter web and admin dashboard (cookie) |
| `POST /api/v1/devices/{id}/revoke`, `retire`, `PATCH /devices/{id}` | [EXISTING] | Device list screen |
| `GET /api/v1/devices` | [EXISTING] | "My devices" screen |
| `POST /api/v1/devices/{id}/heartbeat` | **[EXTEND]** | Accept Bearer access token bound to that device (today: device credential only) |

### 7.3 `GET /api/v1/client-config` **[NEW]**

```json
{
  "protocol": { "current": 1, "min_supported": 1 },
  "server": { "id": "srv_01JC3R8...", "name": "Sharma Family", "version": "0.9.0", "time": "2026-11-04T10:16:05Z" },
  "limits": {
    "max_note_bytes": 102400,
    "max_attachment_bytes": 26214400,
    "max_ops_per_push": 200,
    "max_changes_per_page": 500,
    "max_members": 12
  },
  "features": { "attachments": false, "push": true, "chat_grounding": true, "suggestions": false },
  "push": { "gateway_url": "https://push.example.org", "providers": ["fcm"] }
}
```
The client calls this after login and on each cold start (cached); it uses `server.time` to compute a clock offset (§8.9).

### 7.4 Households **[NEW]**

| Method & path | Purpose | Who |
|---|---|---|
| `GET /households` | List my households | any member |
| `POST /households` `{ "name": "..." }` | Create; caller becomes `admin` | any non-guest user |
| `GET /households/{id}` | Details + `my_role` | member |
| `PATCH /households/{id}` `{ "name": "..." }` | Rename | admin |
| `GET /households/{id}/members` | List members (also delivered through sync as `member` entities) | member |
| `PATCH /households/{id}/members/{user_public_id}` `{ "role": "child" }` | Change role | admin |
| `DELETE /households/{id}/members/{user_public_id}` | Remove member (server emits `forget` changes for that user) | admin |
| `DELETE /households/{id}/members/me` | Leave | member (not last admin) |

Example `GET /households`:
```json
{ "items": [ { "id": "0192f6b2-...", "name": "Sharma Family", "my_role": "adult", "member_count": 4 } ], "next_cursor": null }
```

### 7.5 Sync API **[NEW]** (the only write path for notes, lists, reminders)

#### 7.5.1 `GET /api/v1/sync/changes`

Query: `household_id` (required), `cursor` (integer, default `0`), `limit` (≤ 500).

`cursor=0` is a **bootstrap**: the server returns the user's visible state as synthetic `upsert` changes in dependency order (households → members → notebooks → shares → notes → items → reminders → completions → attachments) with `"snapshot": true` and a `snapshot_seq` the client then uses as its cursor.

Response `200`
```json
{
  "household_id": "0192f6b2-...",
  "snapshot": false,
  "changes": [
    {
      "seq": 1042,
      "entity_type": "note",
      "entity_id": "0192f6d1-...",
      "op": "upsert",
      "version": 4,
      "actor": { "user_id": "usr_8f2a...", "device_id": "dev_5c21..." },
      "changed_at": "2026-11-04T10:15:30Z",
      "data": {
        "id": "0192f6d1-...", "household_id": "0192f6b2-...", "notebook_id": "0192f6c4-...",
        "kind": "note", "title": "Electricity bill", "body_md": "Due **12 Nov**. Paid via UPI.",
        "pinned": true, "archived": false, "color": null, "tags": ["bills"],
        "author_user_id": "usr_8f2a...",
        "created_at": "2026-11-01T08:00:00Z", "updated_at": "2026-11-04T10:15:30Z", "deleted_at": null
      }
    },
    {
      "seq": 1043, "entity_type": "checklist_item", "entity_id": "0192f6d9-...", "op": "delete", "version": 3,
      "actor": { "user_id": "usr_1b7e...", "device_id": "dev_a901..." }, "changed_at": "2026-11-04T10:15:31Z",
      "data": { "id": "0192f6d9-...", "note_id": "0192f6d2-...", "deleted_at": "2026-11-04T10:15:31Z" }
    },
    {
      "seq": 1044, "entity_type": "notebook", "entity_id": "0192f6c9-...", "op": "forget", "version": 0,
      "actor": null, "changed_at": "2026-11-04T10:16:00Z", "data": null
    }
  ],
  "next_cursor": 1044,
  "has_more": false,
  "server_time": "2026-11-04T10:16:05Z"
}
```

Rules:
- `op=upsert` → insert or replace the local row if `version` is greater than the local `version`.
- `op=delete` → set `deleted_at` (tombstone); client hides the row.
- `op=forget` → **physically remove** the entity and all its children from the local DB (access lost). Never shown as a deletion in the UI.
- Changes are ordered by `seq`; the client must apply a page in **one transaction** and persist `next_cursor` in the same transaction.
- `410 Gone` with `error.code = "sync.cursor_expired"` means the cursor is older than the compaction floor; the client discards local synced data for that household (keeping un-pushed outbox ops) and bootstraps with `cursor=0`.

#### 7.5.2 `POST /api/v1/sync/push`

Request
```json
{
  "device_id": "dev_5c21...",
  "household_id": "0192f6b2-...",
  "ops": [
    {
      "op_id": "0192f700-0a1b-7c3d-8e9f-001122334455",
      "entity_type": "note",
      "entity_id": "0192f6d1-...",
      "op": "upsert",
      "base_version": 4,
      "fields": ["body_md"],
      "data": { "id": "0192f6d1-...", "notebook_id": "0192f6c4-...", "kind": "note",
                "title": "Electricity bill", "body_md": "Due **12 Nov**. Paid via UPI & cash." }
    },
    {
      "op_id": "0192f700-0a1c-7a11-8e9f-001122334456",
      "entity_type": "checklist_item",
      "entity_id": "0192f6da-...",
      "op": "upsert",
      "base_version": 0,
      "data": { "id": "0192f6da-...", "note_id": "0192f6d2-...", "text": "Milk 2L", "done": false,
                "position": "a0V", "assignee_user_id": null }
    }
  ]
}
```
- `base_version`: the entity version the edit started from (`0` for a new entity).
- `fields`: optional list of changed fields, used for field-level merge (see 7.5.4).
- Max 200 ops / 1 MB per request; ops are applied **in order** and each in its own savepoint, so one rejected op never blocks the others.

Response `200`
```json
{
  "results": [
    { "op_id": "0192f700-0a1b-...", "status": "applied",   "version": 5 },
    { "op_id": "0192f700-0a1c-...", "status": "duplicate", "version": 1 },
    { "op_id": "0192f700-0a1d-...", "status": "conflict", "reason": "version_mismatch",
      "server": { "version": 7, "data": { "...": "current server entity" } } },
    { "op_id": "0192f700-0a1e-...", "status": "rejected",
      "error": { "code": "household.permission_denied", "message": "Notebook is view-only for you." } }
  ],
  "latest_seq": 1051
}
```
`status` values: `applied`, `duplicate` (same `op_id` already processed → return stored result), `conflict`, `rejected`.

#### 7.5.3 Idempotency and ordering guarantees

- Server stores `(device_id, op_id) → result` in `sync_op_receipts` in the **same transaction** as the entity change and the `sync_changes` row.
- The client keeps an op in the outbox until it receives a terminal status. Retrying after a timeout is therefore always safe.
- Ordering inside one client is preserved by `outbox.seq`; across clients the server's `seq` defines the order.

#### 7.5.4 Conflict policy per entity

| Entity | Stale `base_version` handling |
|---|---|
| `note` — `title`, `body_md` | **Conflict.** Server keeps its version; returns `conflict` + current server data. Client creates a *conflict copy* (§8.6). |
| `note` — only `pinned`, `archived`, `color`, `tags` in `fields` | **Merged**, last-writer-wins by arrival time; `applied`. |
| `checklist_item` | Last-writer-wins per item (`applied`); toggling `done` and editing `text` by different people merge field-wise using `fields`. |
| `reminder` | Last-writer-wins; assignee changes always win over completion. |
| `reminder_completion` | Unique on `(reminder, user, occurrence)`; re-sending is `duplicate`. |
| `notebook`, `notebook_share` | Owner/admin LWW; non-owners get `rejected`. |
| Edit vs **deleted** entity | Delete wins: `conflict` with `reason: "deleted"`; client keeps its text as a conflict copy when it was a note. |

#### 7.5.5 `GET /api/v1/sync/wait` — long-poll fallback

`GET /api/v1/sync/wait?household_id=...&cursor=1044&timeout=25`

Returns `200 { "latest_seq": 1051, "changed": true }` as soon as `latest_seq > cursor`, or `{ "changed": false }` after `timeout` seconds (max 30). Used when SSE is unavailable (CFR-97).

### 7.6 Attachments **[NEW]** (v2)

Attachment *metadata* is created over REST (the server must allocate storage); deletion and later metadata changes still go through sync.

| Step | Request | Response |
|---|---|---|
| 1. Create | `POST /attachments` `{ "id": "<uuidv7>", "note_id": "...", "filename": "bill.jpg", "mime": "image/jpeg", "size_bytes": 482113, "sha256": "ab12..." }` | `201 { "id": "...", "status": "pending", "upload": { "url": "/api/v1/attachments/{id}/content", "chunk_size": 1048576 } }` |
| 2. Resume check | `HEAD /attachments/{id}/content` | `200` + header `Upload-Offset: 0` |
| 3. Upload chunk | `PATCH /attachments/{id}/content` headers `Upload-Offset: N`, `Content-Type: application/offset+octet-stream`, body = bytes | `204` + `Upload-Offset: N+len` |
| 4. Completion | Automatic when `Upload-Offset == size_bytes`; server verifies SHA-256, sets `status=ready`, emits a sync change | — |
| Download | `GET /attachments/{id}/content` (supports `Range`) | bytes |
| Thumbnail | `GET /attachments/{id}/thumbnail` | `image/jpeg` ≤ 20 KB |

Errors: `limits.attachment_too_large` (413), `attachment.hash_mismatch` (422).

### 7.7 Chat and realtime

#### 7.7.1 Chat **[EXISTING]** with small extensions

| Endpoint | Notes |
|---|---|
| `POST /chat/stream` **[EXTEND]** | Accept Bearer tokens and an `Idempotency-Key`; accept `metadata.household_id` and `metadata.grounding` (bool) |
| `GET /api/v1/conversations`, `GET /conversations/{id}/messages` | [EXISTING] cursor-paginated history |
| `POST /api/v1/conversations/{id}/messages` | [EXISTING] non-streaming send with `Idempotency-Key` |

Request
```json
{
  "message": "What did we decide about the electricity bill?",
  "conversation_id": "conv_...",
  "device_id": "dev_5c21...",
  "metadata": { "household_id": "0192f6b2-...", "grounding": true, "locale": "hi-IN" }
}
```
Response: `application/x-ndjson`, one JSON object per line:
```json
{"type":"status","text":"Searching your notes…"}
{"type":"tool_start","tool":"notes_search","args":{"q":"electricity bill"}}
{"type":"tool_end","tool":"notes_search","ok":true}
{"type":"thought","text":"Found 2 relevant notes."}
{"type":"done","conversation_id":"conv_...","message_id":"msg_...","reply":"You decided to pay by UPI before 12 Nov.","sources":[{"note_id":"0192f6d1-...","title":"Electricity bill"}]}
```
Error line: `{"type":"error","status":503,"detail":"Model is not available"}`.

**Grounding is server-side**: the server's notes-search tool only returns notes the *caller* may read (same visibility rule as §6.1). The client never uploads its notes to the chat endpoint.

#### 7.7.2 Realtime (SSE) **[EXISTING]**, new event types

`GET /api/v1/stream` (per-user filtered). The client subscribes with the Bearer token and reconnects with exponential backoff (1 s → 30 s, jitter).

| Event `type` | `data` | Client reaction |
|---|---|---|
| `sync.changed` | `{ "household_id": "...", "latest_seq": 1051 }` | `SyncEngine.requestSync(hint)` |
| `device.revoked` | `{ "device_id": "..." }` | Lock app (CFR-07) |
| `session.revoked` | `{}` | Re-authenticate with device credential or lock |
| `kernel.*`, `sensor.*`, `agent.*` | — | **Ignored** by the family client |

### 7.8 Push registration and the push gateway

#### 7.8.1 Client → VIRA server **[NEW]**

`PUT /api/v1/devices/{device_id}/push-registration`
```json
{ "provider": "fcm", "push_handle": "ph_9d1c...", "locale": "hi-IN" }
```
`DELETE /api/v1/devices/{device_id}/push-registration?provider=fcm` — unregister.

#### 7.8.2 Push gateway (separate tiny service) **[NEW]**

The gateway exists only because each family cannot own a Firebase project. It maps opaque handles to provider tokens and forwards **content-free** wake-ups.

| Endpoint | Caller | Body → Response |
|---|---|---|
| `POST /v1/servers` | VIRA server (once) | `{ "server_name": "optional", "version": "0.9.0" }` → `{ "server_id": "srv_...", "server_secret": "..." }` |
| `POST /v1/handles` | Flutter app | `{ "server_id": "srv_...", "provider": "fcm", "token": "<fcm token>", "platform": "android" }` → `{ "push_handle": "ph_9d1c..." }` |
| `POST /v1/push` | VIRA server | Headers `X-Server-Id`, `X-Timestamp`, `X-Signature: HMAC-SHA256(server_secret, timestamp + "." + body)`; body `{ "handles": ["ph_9d1c..."], "collapse_key": "sync", "priority": "high" }` → `{ "accepted": 1, "invalid_handles": [] }` |
| `DELETE /v1/handles/{push_handle}` | Flutter app | `204` |

Rules: payload delivered to the device is always `{ "t": "sync" }` (plus the collapse key); the gateway rejects any other field. A handle is valid only for the `server_id` it was created with. The server removes handles listed in `invalid_handles`. Rate limits: 30 pushes/min per handle, 600/min per server.

### 7.9 Error codes

| HTTP | `error.code` | Meaning / client action |
|---|---|---|
| 400 | `validation_error` | Show field errors; do not retry |
| 401 | `auth.invalid_token` / `auth.token_expired` | Refresh once, then re-auth |
| 401 | `auth.token_reuse` | Lock + force re-pair |
| 403 | `household.permission_denied` | Show message; mark op `failed` |
| 403 | `auth.device_revoked` / `auth.user_disabled` | Lock app (CFR-07) |
| 404 | `pairing.invalid_code`, `not_found` | Show message |
| 409 | `pairing.used`, `sync.version_conflict` | Conflict flow |
| 410 | `pairing.expired`, `sync.cursor_expired` | Re-pair / re-bootstrap |
| 413 | `limits.note_too_large`, `limits.attachment_too_large` | Block in UI |
| 426 | `protocol.upgrade_required` | "Update the app" screen |
| 429 | `rate_limited` | Honour `Retry-After` |
| 5xx | `server_error` | Backoff and retry |

### 7.10 Server work packages (summary)

| WP | Deliverable | Touches |
|---|---|---|
| WP-S1 | `family` migration (§6.1), households + roles + permission checks | `auth/migrations.py`, new `vira/family/` |
| WP-S2 | Token auth: pairing, refresh, scopes, `Authorization: Bearer` dependency, platform role `member` | `auth/`, `api/deps.py`, new `api/routes_pairing.py` |
| WP-S3 | Sync service (`apply_op`, change log, visibility filter, compaction, `/sync/*`) | new `vira/family/sync.py`, `api/routes_sync.py` |
| WP-S4 | SSE `sync.changed`, `device.revoked`; long-poll `/sync/wait` | `api/streams.py` |
| WP-S5 | Notes-search tool for chat grounding with per-user visibility | `vira/tools/`, `agent/Agents/chat_agent.py` |
| WP-S6 | Push registration + gateway client; notification policy | new `vira/family/push.py` |
| WP-S7 | Attachments (v2) | new `vira/family/attachments.py` |
| WP-S8 | `GET /client-config`, `PUT push-registration`, `/auth/me` extension | `api/app.py` |
| WP-S9 | Push gateway service | new repo / directory |

New `config.yaml` block:
```yaml
family:
  token_ttl_seconds: 900
  refresh_ttl_days: 30
  pairing_ttl_seconds: 900
  limits: { max_note_bytes: 102400, max_attachment_bytes: 26214400, max_members: 12, max_ops_per_push: 200 }
  sync: { compaction_days: 30, trash_days: 30 }
  push: { enabled: true, gateway_url: "https://push.example.org" }
  tls: { lan_cert_path: ./data/tls/lan.pem, lan_key_path: ./data/tls/lan.key }
```

---
## 8. Low-level design (LLD)

### 8.1 Project structure and layering rules

Feature-first, layered. One Dart package (`vira_family`); split into packages later only if build times demand it.

```
vira_family/
├─ lib/
│  ├─ main.dart                      # bootstrap: ProviderScope, error zone, DB + secure-store init
│  ├─ app/
│  │  ├─ app.dart                    # MaterialApp.router, theme, l10n delegates
│  │  ├─ router.dart                 # go_router config, auth/pairing redirect guards, deep links
│  │  ├─ theme/                      # ColorScheme, text styles, dark theme
│  │  └─ l10n/                       # app_en.arb, app_hi.arb
│  ├─ core/
│  │  ├─ clock.dart                  # abstract Clock + SystemClock + ServerClock (offset)
│  │  ├─ ids.dart                    # Uuid7 generator (injectable)
│  │  ├─ result.dart                 # Result<T, AppFailure>
│  │  ├─ failures.dart               # sealed AppFailure hierarchy
│  │  ├─ logging/                    # redacting logger, ring buffer, export
│  │  └─ platform/                   # capability flags (isWeb, supportsMdns, supportsBgTasks)
│  ├─ domain/
│  │  ├─ entities/                   # Household, Member, Notebook, Note, ChecklistItem, Reminder, ...
│  │  ├─ repositories/               # abstract interfaces (NotesRepository, ...)
│  │  └─ usecases/                   # CreateNote, ToggleItem, CompleteReminder, ...
│  ├─ data/
│  │  ├─ local/
│  │  │  ├─ app_database.dart        # drift @DriftDatabase, migrations
│  │  │  ├─ tables/                  # one file per table (§6.2)
│  │  │  └─ daos/                    # NotesDao, OutboxDao, SyncStateDao, ...
│  │  ├─ remote/
│  │  │  ├─ transport_manager.dart   # endpoint selection, probing, pinning
│  │  │  ├─ api_client.dart          # dio instance, interceptors
│  │  │  ├─ dto/                     # freezed JSON DTOs matching §7
│  │  │  └─ services/                # AuthApi, SyncApi, HouseholdApi, ChatApi, PushApi
│  │  ├─ sync/
│  │  │  ├─ sync_engine.dart
│  │  │  ├─ outbox.dart
│  │  │  ├─ change_applier.dart      # per-entity apply of pulled changes
│  │  │  └─ conflict_resolver.dart
│  │  ├─ secure/secure_store.dart    # tokens, credential, db key
│  │  └─ repositories/               # *_repository_impl.dart
│  ├─ platform_services/
│  │  ├─ notifications/              # notification_service.dart, reminder_scheduler.dart, policy.dart
│  │  ├─ push/                       # push_provider.dart (interface), fcm_provider.dart
│  │  ├─ background/                 # workmanager callbacks
│  │  ├─ share/share_receiver.dart
│  │  ├─ discovery/mdns_discovery.dart
│  │  └─ speech/speech_service.dart
│  └─ features/
│     ├─ onboarding/  ├─ pairing/  ├─ notes/  ├─ lists/  ├─ reminders/
│     ├─ household/   ├─ chat/     ├─ search/ ├─ settings/ (privacy, devices, connection, notifications)
│     └─ <feature>/{presentation (screens, widgets), application (notifiers/controllers)}
├─ test/                             # unit + widget tests mirroring lib/
├─ integration_test/
├─ android/ ios/ linux/ web/
└─ pubspec.yaml, analysis_options.yaml, l10n.yaml
```

**Rules (enforced with `import_lint`/custom lint in CI)**

1. `domain/` imports only `dart:core` and pure-Dart packages (`freezed_annotation`, `rrule`, `meta`).
2. `features/*/presentation` talks only to `features/*/application` and `domain/`.
3. `features/A` never imports `features/B/presentation`. Shared widgets go to `app/widgets/`.
4. Only `data/` and `platform_services/` may import `dio`, `drift`, `firebase_*`, `flutter_local_notifications`.
5. Every side-effecting dependency (clock, ids, http, db, notifications) is injected through a Riverpod provider so tests can override it.

### 8.2 Bootstrap and dependency graph

```dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final secure = SecureStore();                       // flutter_secure_storage
  final dbKey = await secure.getOrCreateDbKey();      // 32 random bytes, base64
  final db = await AppDatabase.open(key: dbKey);      // migrations run here (backup first)
  await NotificationService.init();                   // channels + tz database
  runZonedGuarded(
    () => runApp(ProviderScope(
      overrides: [appDatabaseProvider.overrideWithValue(db), secureStoreProvider.overrideWithValue(secure)],
      child: const ViraApp(),
    )),
    (e, st) => Log.fatal('uncaught', e, st),
  );
}
```

Core providers (Riverpod):

| Provider | Type | Depends on |
|---|---|---|
| `clockProvider` | `Clock` | — |
| `idsProvider` | `Ids` | — |
| `appDatabaseProvider` | `AppDatabase` | (override in main) |
| `secureStoreProvider` | `SecureStore` | (override in main) |
| `endpointsProvider` | `StreamProvider<List<Endpoint>>` | db |
| `transportManagerProvider` | `TransportManager` | endpoints, connectivity |
| `sessionProvider` | `AsyncNotifier<Session?>` | secure store, auth API |
| `apiClientProvider` | `ApiClient` (dio) | transport, session |
| `syncEngineProvider` | `SyncEngine` | db, api, clock, notification policy |
| `activeHouseholdProvider` | `Notifier<String?>` | db, settings |
| `*RepositoryProvider` | repositories | db, outbox, sync engine, ids, clock |
| `*ListProvider(family)` | `StreamProvider` | repository (drift `watch()` queries) |

### 8.3 Domain layer

**Entities (immutable, `freezed`)** — example:

```dart
@freezed
class Note with _$Note {
  const factory Note({
    required String id,
    required String householdId,
    required String notebookId,
    required String authorUserId,
    required NoteKind kind,                 // note | checklist
    required String title,
    required String bodyMd,
    required bool pinned,
    required bool archived,
    String? color,
    @Default([]) List<String> tags,
    required int version,                   // 0 = never synced
    required int baseVersion,
    required DateTime createdAt,
    required DateTime updatedAt,
    DateTime? deletedAt,
    String? conflictOf,
    required SyncState syncState,           // synced | pending | conflict | failed
  }) = _Note;
}
```

**Repository interfaces** (all reads are `Stream`s, all writes return `Future<Result<T>>` and are local-first):

```dart
abstract interface class NotesRepository {
  Stream<List<Note>> watchNotes({required String notebookId, bool includeArchived = false});
  Stream<Note?> watchNote(String id);
  Stream<List<Note>> search(String query, {String? householdId});
  Future<Result<Note>> create({required String notebookId, required NoteKind kind, String title = '', String bodyMd = ''});
  Future<Result<void>> update(String id, NotePatch patch);   // title/body/pinned/archived/color/tags
  Future<Result<void>> moveToTrash(String id);
  Future<Result<void>> restore(String id);
}

abstract interface class ChecklistRepository {
  Stream<List<ChecklistItem>> watchItems(String noteId);
  Future<Result<ChecklistItem>> add(String noteId, String text, {String? afterItemId});
  Future<Result<void>> setDone(String itemId, bool done);
  Future<Result<void>> edit(String itemId, {String? text, String? assigneeUserId});
  Future<Result<void>> reorder(String itemId, {String? beforeId, String? afterId});
  Future<Result<void>> remove(String itemId);
  Future<Result<void>> clearDone(String noteId);
}

abstract interface class RemindersRepository { /* watchUpcoming, create, update, complete(reminderId, occurrenceAt), cancel */ }
abstract interface class HouseholdRepository { /* watchHouseholds, watchMembers, createPairingCode, changeRole, removeMember, leave */ }
abstract interface class NotebooksRepository { /* watchNotebooks, create, rename, setVisibility, share(userId, permission), unshare */ }
abstract interface class AuthRepository { /* redeemPairing, refresh, signOutAndWipe, watchDevices, revokeDevice */ }
abstract interface class ChatRepository { Stream<ChatEvent> send(...); Stream<List<ChatMessage>> watchMessages(String convId); }
```

**Use cases** are thin (one public `call()`): `CreateNote`, `UpdateNote`, `TrashNote`, `AddChecklistItem`, `ToggleChecklistItem`, `CreateReminder`, `CompleteReminder`, `SnoozeReminder`, `ReceiveSharedContent`, `PairDevice`, `GeneratePairingCode`, `ExportAllData`. They add validation (limits from `client-config`) and permission checks (`my_permission`, `my_role`) before calling repositories.

### 8.4 Data layer — local-first write

Every mutation = **one drift transaction** that updates the entity row *and* enqueues/coalesces an outbox op.

```dart
Future<Result<void>> update(String id, NotePatch patch) => db.transaction(() async {
  final row = await notesDao.byId(id) ?? (throw NotFound());
  _assertCanEdit(row);                                         // my_permission == edit
  final base = row.syncState == SyncState.synced ? row.version : row.baseVersion;
  final updated = row.applyPatch(patch, updatedAt: clock.nowMs());
  await notesDao.upsert(updated.copyWith(baseVersion: base, syncState: SyncState.pending));
  await outbox.enqueueOrCoalesce(
    entityType: EntityType.note, entityId: id, op: OutboxOpKind.upsert,
    baseVersion: base, fields: patch.changedFields, payload: updated.toPushPayload(),
  );
  return const Result.ok(null);
}).whenComplete(() => syncEngine.requestSync(SyncReason.localChange));
```

**Outbox coalescing** (`OutboxDao.enqueueOrCoalesce`): if a `queued` (not `in_flight`) op already exists for the same `(entity_type, entity_id)`, replace its `payload_json`, union its `fields`, **keep its original `base_version` and `op_id`**. A `delete` supersedes earlier upserts for the same entity; an upsert for an entity that has a queued *create* (`base_version = 0`) stays a create.

**Checklist ordering:** `position` is a fractional-index string (e.g. `a0`, `a0V`, `a1`). `reorder(item, before, after)` computes `between(before.position, after.position)`; no other rows change, so concurrent reorders touch only the moved item.

**Search:** `notes_fts` (FTS5) with `bm25` ranking; query is tokenised and each token gets a prefix `*`. Hindi (Devanagari) works with the `unicode61` tokenizer; no stemming in v1.

### 8.5 Transport, API client, auth

```dart
class Endpoint { final String id; final EndpointKind kind; final Uri url; final int priority; }

class TransportManager {
  /// Emits the currently chosen endpoint (null = fully offline).
  Stream<Endpoint?> get active;
  Future<Endpoint?> resolve({bool forceProbe = false});     // probe all, pick best
  void reportFailure(Endpoint e, Object error);              // triggers re-probe with backoff
  Future<void> setEndpoints(List<Endpoint> list);
}
```

Algorithm `resolve()`:
1. Load endpoints ordered by `priority`.
2. Probe all in parallel with `GET {url}/health` (timeout 1.5 s; LAN endpoints probed only if the device is on Wi-Fi/Ethernet).
3. Accept a response only if TLS validates: public CA chain for `tailscale`/`tunnel`; **SHA-256 fingerprint equals pinned `cert_sha256`** for `lan`.
4. Choose the reachable endpoint with the lowest `priority`. Cache until: request failure (network error/timeout ×2), connectivity change event, or 5 minutes since last probe while foreground.
5. On mDNS result (`_vira._tcp`, TXT `server_id=…`), update the `lan` endpoint URL if `server_id` matches.

**Dio setup**

```dart
final dio = Dio(BaseOptions(connectTimeout: const Duration(seconds: 8), receiveTimeout: const Duration(seconds: 30), sendTimeout: const Duration(seconds: 30)))
  ..httpClientAdapter = PinningAdapter(transport)            // IOHttpClientAdapter with badCertificateCallback → fingerprint check
  ..interceptors.addAll([
      BaseUrlInterceptor(transport),                          // sets baseUrl from active endpoint, fails fast if offline
      HeadersInterceptor(clientVersion, protocol, ids),       // X-Vira-Client, X-Correlation-ID
      AuthInterceptor(session),                               // Bearer + single-flight refresh on 401
      RetryInterceptor(maxAttempts: 3, baseDelay: const Duration(milliseconds: 500), idempotentOnly: true),
      ErrorMapperInterceptor(),                               // DioException → AppFailure (§8.12)
  ]);
```

`AuthInterceptor`:
- Adds `Authorization: Bearer <access>` (refresh proactively when < 60 s left).
- On `401 auth.token_expired|invalid_token`: acquire a **mutex**, call `POST /auth/token` (refresh grant) **once**, retry the original request; concurrent requests await the same refresh.
- If refresh fails with `invalid_grant`, try the `device_credential` grant; if that fails with `auth.device_revoked` → emit `SessionEvent.revoked` (app locks).
- `auth.token_reuse` → emit `SessionEvent.compromised` (lock + force re-pair).

Web uses the cookie adapter (`withCredentials: true`) and skips the Bearer logic.

### 8.6 Sync engine

**Public API**

```dart
enum SyncReason { appForeground, localChange, serverHint, connectivity, periodic, manual, bootstrap }
sealed class SyncStatus { Idle, Syncing(progress), Offline, Backoff(retryAt), AuthRequired, UpgradeRequired }

class SyncEngine {
  Stream<SyncStatus> get status;
  void requestSync(SyncReason reason, {String? householdId});   // debounced, single-flight
  Future<void> bootstrap(String householdId);                    // cursor = 0
}
```

**Triggers:** foreground (immediately), local change (debounce 300 ms), SSE `sync.changed` (debounce 200 ms; ignore if `latest_seq <= cursor`), connectivity regained, push wake-up, WorkManager periodic (15 min), pull-to-refresh.

**Algorithm (single-flight; if a run is active, set `rerun=true`)**

```dart
Future<void> _run() async {
  do {
    rerun = false;
    final ep = await transport.resolve();
    if (ep == null) return _setStatus(Offline());
    for (final h in await households.activeIds()) {
      await _pushAll(h);        // 1. flush outbox first so our edits are authoritative before we pull
      await _pullAll(h);        // 2. then pull until has_more == false
    }
  } while (rerun);
  _setStatus(Idle());
}

Future<void> _pushAll(String h) async {
  while (true) {
    final batch = await outbox.claim(householdId: h, limit: 200, now: clock.nowMs()); // queued → in_flight (txn)
    if (batch.isEmpty) return;
    try {
      final res = await syncApi.push(deviceId: session.deviceId, householdId: h, ops: batch);
      await db.transaction(() async {
        for (final r in res.results) { await _applyResult(batch.byId(r.opId), r); }
      });
    } on NetworkFailure { await outbox.release(batch, backoff: true); rethrow; }
    on AuthFailure { await outbox.release(batch); rethrow; }
  }
}

Future<void> _pullAll(String h) async {
  var cursor = await syncState.cursor(h);                       // 0 → bootstrap
  while (true) {
    final page = await syncApi.changes(householdId: h, cursor: cursor, limit: 500);
    await db.transaction(() async {
      await changeApplier.apply(page.changes);                  // idempotent
      await syncState.setCursor(h, page.nextCursor);            // same transaction
    });
    notificationPolicy.onChanges(h, page.changes);              // after commit
    cursor = page.nextCursor;
    if (!page.hasMore) break;
  }
  await reminderScheduler.reconcile();                          // after every successful pull
}
```

`410 sync.cursor_expired` → `await db.purgeSyncedData(h, keepOutbox: true)` then `bootstrap(h)`.

**`_applyResult`** (inside the transaction)

| Result | Local effect |
|---|---|
| `applied` / `duplicate` | Delete the outbox row. If no other queued op exists for the entity: set `version = result.version`, `base_version = result.version`, `sync_state = synced`. Otherwise only update `version`, keep `pending`. |
| `conflict` (`version_mismatch`) | `ConflictResolver.resolve(op, serverEntity)` (below). Delete the outbox row. |
| `conflict` (`deleted`) | Entity stays deleted locally; for notes create a conflict copy from the local text. Delete the outbox row. |
| `rejected` | Outbox row → `failed` with `last_error`; entity `sync_state = failed`. UI shows a retry/discard banner (permission errors offer "discard my change"). |

**Applying pulled changes (`ChangeApplier`)**

For each change, by `entity_type`:
- `upsert`: if the row does not exist → insert. If it exists and `change.version <= row.version` → skip (idempotent). Otherwise:
  - **No pending outbox op** for the entity → replace the row, `sync_state = synced`.
  - **Pending op, entity is note (title/body)** → keep the local content, set `row.version = change.version` but **leave `base_version` unchanged** and leave the outbox op untouched; the next push will conflict and produce a conflict copy (by design, ADR-5).
  - **Pending op, any other entity** → take server values for fields *not* in the op's `fields`; rebase the outbox op's `base_version` to `change.version`; keep `pending`.
- `delete`: set `deleted_at`; if a pending local edit exists on a note, keep it as a conflict copy.
- `forget`: delete the entity and all children, remove related outbox ops, cancel related scheduled notifications.
- Compute `my_permission` for notebooks on apply (owner → `edit`; shares → per share; household visibility → role-based, §9.3).

**ConflictResolver for notes**

```dart
Future<void> resolveNoteConflict(OutboxOp op, ServerNote server) async {
  final local = await notes.byId(op.entityId);
  final copyId = ids.next();
  await notes.insert(local.copyWith(
    id: copyId, version: 0, baseVersion: 0, conflictOf: op.entityId,
    title: '${local.title} (${l10n.conflictSuffix(deviceName, clock.now())})',
    syncState: SyncState.pending));
  await outbox.enqueue(create: copyId);                       // copy syncs like any note
  await notes.replaceFromServer(server);                       // original = server's version
  await badges.flag(op.entityId, ConflictBadge.hasCopy(copyId));
}
```
The UI shows a banner on the original: "Someone else edited this at the same time. Your version was saved as *…(conflict)*." with **Compare**, **Keep mine** (replace original with copy's text via a new normal edit) and **Dismiss**.

**Backoff:** per-op `next_attempt_at = now + min(5 min, 2^attempts s) ± 20% jitter`; global `Backoff` status after 3 consecutive failed runs; resets on connectivity change or manual refresh.

**Concurrency rules:** one sync run at a time (async mutex); DB writes from sync and UI interleave safely through SQLite WAL; UI reads are `watch()` streams that update after each commit.

### 8.7 Reminder scheduler

Reminders are scheduled **on the device**; the server is only a sync channel.

```dart
class ReminderScheduler {
  Future<void> reconcile();     // compute desired set, diff against scheduled_notifications, apply
}
```

`reconcile()`:
1. Select active reminders where `assignee IS NULL OR assignee = me`.
2. Expand occurrences in the reminder's **own time zone** (`timezone` package + `rrule`): for non-repeating reminders just `due_at`; for repeating ones the next occurrences ≥ now.
3. Drop occurrences that have a `reminder_completions` row for `(reminder, me, occurrence_at)`.
4. Sort by fire time; take the first **N = 48** (iOS allows 64 pending local notifications; keep headroom for snoozes) within the next 60 days.
5. Diff against `scheduled_notifications`: cancel those no longer desired, schedule new ones. Notification id = 31-bit stable hash of `reminder_id + occurrence_at`.
6. Payload: `{"type":"reminder","reminder_id":"…","occurrence_at":1731234000000}`.

Triggers for `reconcile()`: after every successful pull, local reminder write, app start/foreground, daily background job (also tops up the rolling window), and system time-zone/clock change detected on foreground. On Android the plugin's boot receiver re-registers alarms after reboot; `reconcile()` verifies on next launch.

Notification actions (Android action buttons / iOS categories):

| Action | Handler (may run in a background isolate) |
|---|---|
| **Done** | Open the DB with its own connection, insert `reminder_completions` row + outbox op, cancel notification, enqueue a one-off WorkManager sync |
| **Snooze 10 min / 1 h / Tomorrow** | Schedule a one-shot **local-only** notification (not synced) with the same payload |
| Tap | Deep link `vira://reminder/{id}` |

Permissions: Android 13+ `POST_NOTIFICATIONS`; exact alarms via `SCHEDULE_EXACT_ALARM`/`USE_EXACT_ALARM` — if denied, fall back to inexact alarms and show a one-time hint in settings.

### 8.8 Notification service and policy

Channels (Android) / categories (iOS):

| Channel id | Name | Importance | Used for |
|---|---|---|---|
| `reminders` | Reminders | High (sound, heads-up) | `reminder_due` |
| `household` | Family activity | Default | `assigned_to_you`, `note_shared`, `list_updated`, `member_joined` |
| `vira` | VIRA | Low | `vira_suggestion`, chat completion |
| `system` | System | Low | Sync problems, update required |

`NotificationPolicy.onChanges(household, changes)` runs **after** a pull commit and builds *local* notifications:

| Category | Rule |
|---|---|
| `assigned_to_you` | Change is a `reminder` or `checklist_item` upsert, `actor != me`, `assignee == me` and previous assignee ≠ me |
| `note_shared` | A `notebook_share` upsert for me, or a new `household`-visible notebook, `actor != me` |
| `list_updated` | `checklist_item` changes in a list by others; coalesced to ≤ 1 per list per 5 min; only if category enabled |
| `member_joined` | New `member` row (admins only) |

Common filters: category enabled for that household; not within quiet hours (unless urgent reminder); app not in foreground showing that entity; dedupe using `last_notified_seq:<household>` in `app_settings`.

**Push wake-up path:** `PushProvider.onMessage` (data message `{"t":"sync"}`) → in a background isolate: `SyncEngine.requestSync(serverHint)` → policy raises notifications. iOS silent pushes are best-effort; correctness never depends on them (the periodic job and foreground sync still converge).

**Deep links** (go_router): `vira://note/{id}`, `vira://list/{id}`, `vira://reminder/{id}`, `vira://chat/{conversationId}`; the same paths work as web URLs (`/note/{id}`).

### 8.9 Time and IDs

- `Ids.next()` → UUIDv7 (millisecond timestamp prefix, so rows sort by creation time and indexes stay compact).
- `ServerClock`: on each `client-config`/sync response compute `offset = server_time − device_now`; `nowForDisplay()` uses device time; **never** write server-trusted timestamps from the client except `updated_at` for local ordering (server overwrites with its own).
- Reminders store `due_at` in UTC **and** an IANA `timezone`; the UI renders in the *reminder's* zone with a "(your time: …)" hint if it differs from the device zone.

### 8.10 Pairing flow

```mermaid
sequenceDiagram
    participant Admin as Admin app / dashboard
    participant Srv as VIRA server
    participant App as New member's app
    Admin->>Srv: POST /auth/pairing-codes {household, role}
    Srv-->>Admin: code + qr_payload
    Admin-->>App: shows QR (or code)
    App->>App: parse + validate QR (version, endpoints)
    App->>Srv: GET /health (pinned cert_sha256)
    App->>Srv: POST /auth/pairing/redeem {code, user, device}
    Srv->>Srv: txn: use code, create user, add member, register device, issue tokens
    Srv-->>App: user, household, device_credential, tokens
    App->>App: store secrets in SecureStore; save endpoints
    App->>Srv: GET /client-config
    App->>Srv: GET /sync/changes?cursor=0 (bootstrap, paged)
    App->>Srv: PUT /devices/{id}/push-registration (after notification permission)
    App-->>App: navigate to Home
```

`PairingController` states: `idle → scanning → validating → redeeming → bootstrapping(progress) → done | error(AppFailure)`. Errors map to friendly screens (expired code → "Ask the admin for a new code").

### 8.11 Presentation: navigation and screens

Shell with bottom navigation (rail on tablets/desktop): **Notes · Lists · Reminders · VIRA · More**.

| Route | Screen | State / controller | Key behaviours |
|---|---|---|---|
| `/onboarding` | Welcome + choose join/setup | — | CFR-01 |
| `/pair/scan`, `/pair/manual` | QR scanner / code + address | `PairingController` | CFR-02..04 |
| `/notes` | Notebook list + recent notes | `notesListProvider` | Sync-state chips, search entry |
| `/notebook/:id` | Notes in notebook | `notebookNotesProvider(id)` | Pin, archive, multi-select |
| `/note/:id` | Editor | `NoteEditorController` | Autosave (debounce 500 ms), Markdown toolbar, conflict banner, "last edited by" |
| `/lists`, `/list/:id` | Checklist | `ChecklistController` | Optimistic toggle, drag reorder, "Done" section, assignee chip |
| `/reminders` | Upcoming / Done / Mine | `remindersProvider` | Snooze/complete inline |
| `/reminder/:id` | Create/edit | `ReminderFormController` | Time zone, repeat picker, assignee |
| `/chat`, `/chat/:id` | VIRA chat | `ChatController` | Streaming bubbles, tool-activity chips, sources, voice input |
| `/household` | Members, roles, invite | `HouseholdController` | Admin actions gated by `my_role` |
| `/search` | Global search | `searchProvider` | FTS results grouped by type |
| `/settings/*` | Privacy, Devices, Connection, Notifications, Language, App lock, About/Logs | respective providers | CFR-06, 91, 98 |
| `/share` | Receive shared content | `ShareController` | Choose notebook → create note |

Global UI elements: **sync indicator** in the app bar (✓ synced, ⟳ syncing, ☁︎✕ offline, ! needs attention) bound to `SyncEngine.status`; per-item **sync chip** from `sync_state`; non-blocking banners for `UpgradeRequired`, `AuthRequired`, and `Locked`.

### 8.12 Error model

```dart
sealed class AppFailure { String get code; }
class NetworkFailure extends AppFailure {}          // offline, timeout, TLS/pin mismatch
class AuthFailure extends AppFailure { final AuthFailureKind kind; }   // expired, revoked, reuse, disabled
class PermissionFailure extends AppFailure {}       // 403 household.permission_denied
class ValidationFailure extends AppFailure { final Map<String,String> fields; }
class ConflictFailure extends AppFailure {}
class LimitFailure extends AppFailure { final String limit; }
class UpgradeRequired extends AppFailure {}
class ServerFailure extends AppFailure {}
class UnknownFailure extends AppFailure {}
```
`ErrorMapperInterceptor` converts `{error:{code}}` to these types. UI never shows raw exceptions; each failure has a localized message and a recommended action (retry / sign in / update / contact admin).

### 8.13 Chat client

```dart
sealed class ChatEvent { Status(String text), ToolStart(String tool, Map args), ToolEnd(String tool, bool ok),
                         Thought(String text), Done(String conversationId, String messageId, String reply, List<Source> sources),
                         Error(int status, String detail) }

Stream<ChatEvent> send(String text, {String? conversationId, required String householdId}) async* {
  final res = await dio.post<ResponseBody>('/chat/stream',
      data: {...}, options: Options(responseType: ResponseType.stream, headers: {'Idempotency-Key': ids.next()}),
      cancelToken: token);
  final lines = utf8.decoder.bind(res.data!.stream).transform(const LineSplitter());
  await for (final line in lines) { if (line.isEmpty) continue; yield ChatEvent.fromJson(jsonDecode(line)); }
}
```
- A user message is stored locally with `state=sending` immediately; on `Done` it becomes `sent` and the assistant message is inserted.
- If the connection drops mid-stream, the server still finishes and stores the run (existing behaviour). The client polls `GET /conversations/{id}/messages` (backoff 1→8 s, max 60 s) until the assistant reply appears.
- Offline: input disabled with an explanation; drafts persist in `messages` with `state=draft`.

### 8.14 Platform configuration checklist

| Platform | Required configuration |
|---|---|
| Android | `INTERNET`, `POST_NOTIFICATIONS`, `SCHEDULE_EXACT_ALARM`/`USE_EXACT_ALARM`, `RECEIVE_BOOT_COMPLETED`, `CAMERA` (QR), `RECORD_AUDIO` (dictation); intent-filters for `vira://` and `ACTION_SEND` (text/*, image/*); FCM `google-services.json`; R8 keep rules for SQLCipher |
| iOS/iPadOS | `NSCameraUsageDescription`, `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`, `NSLocalNetworkUsageDescription` + `NSBonjourServices` = `_vira._tcp`; Push + Background Modes (remote-notification, fetch); Share Extension target; Associated Domains if universal links are used |
| Linux | `libsecret`, `libsqlcipher`; `.desktop` file with `x-scheme-handler/vira`; notifications via `libnotify` |
| Web | HTTPS endpoint only; cookie auth; IndexedDB via drift WASM; no background sync/reminders in v1 |

LAN uses **HTTPS with a self-signed certificate that the app pins** (fingerprint from the QR), so no cleartext-HTTP exceptions are needed. `dart:io`'s `HttpClient` performs its own TLS validation, so iOS App Transport Security does not apply to it; do not switch to `cupertino_http` without revisiting this.

### 8.15 Diagnostics and logging

- `Log` wrapper with levels; redaction rules: never log note text, titles, tokens, or message content; IDs are truncated to 8 chars.
- 2 MB ring buffer on disk (rotated), exportable via **Settings → Send logs** (share sheet, user-initiated).
- Connection screen shows for each endpoint: URL, reachability, latency, TLS/pin status, last error; sync screen shows cursor per household, outbox size, last successful sync, last error.
- Feature flags come only from `client-config.features`; there is no third-party remote-config SDK.

### 8.16 Server-side low-level design (new modules)

**Module layout**

```
vira/family/
  __init__.py
  models.py          # dataclasses / pydantic models for entities and sync payloads
  store.py           # SQL (repositories) for households, notebooks, notes, items, reminders
  permissions.py     # role & visibility checks (§9.3)
  sync.py            # SyncService
  tokens.py          # TokenService (pairing, access/refresh, rotation, reuse detection)
  push.py            # PushService (gateway client, notification fan-out rules)
  attachments.py     # v2
vira/api/routes_pairing.py   routes_households.py   routes_sync.py   routes_push.py
```

**`SyncService.push` (core of the system)**

```python
def push(self, actor: UserPrincipal, device_id: str, household_id: str, ops: list[Op]) -> PushResult:
    self._require_member(actor, household_id)
    results, touched = [], False
    with self.db.immediate() as conn:                          # BEGIN IMMEDIATE (single writer, WAL)
        for op in ops[:MAX_OPS]:
            with conn.savepoint():
                receipt = self.receipts.get(conn, device_id, op.op_id)
                if receipt:                                    # idempotent replay
                    results.append(receipt.as_duplicate()); continue
                try:
                    h = self.handlers[op.entity_type]
                    h.authorize(actor, household_id, op, conn)           # raises Rejected(code)
                    outcome = h.apply(conn, actor, device_id, op)        # Applied | Conflict
                except Rejected as r:
                    outcome = Rejected_(r.code, r.message)
                if isinstance(outcome, Applied):
                    self.changes.append(conn, household_id, op.entity_type, op.entity_id,
                                        notebook_id=outcome.notebook_id, op=outcome.kind,
                                        version=outcome.version, actor=actor, device_id=device_id)
                    touched = True
                self.receipts.put(conn, device_id, op.op_id, outcome)
                results.append(outcome.as_result(op.op_id))
        latest = self.changes.latest_seq(conn, household_id)
    if touched:
        self.stream.publish_sync_changed(household_id, latest)   # after commit
        self.push_service.maybe_wake(household_id, exclude_actor=actor.user_id)
    return PushResult(results, latest)
```

`Handler.apply` pattern for `note`:

```python
def apply(self, conn, actor, device_id, op):
    cur = self.store.get_note(conn, op.entity_id)
    if cur is None:
        if op.op == "delete": return Applied.noop()
        validate_note(op.data)                                   # size, kind, notebook visibility
        n = self.store.insert_note(conn, op.data, author=actor, version=1)
        return Applied(version=1, notebook_id=n.notebook_id, kind="upsert")
    if cur.deleted_at and op.op == "upsert":
        return Conflict("deleted", server=cur)
    if op.base_version != cur.version:
        if not set(op.fields or []) <= {"pinned", "archived", "color", "tags"}:
            return Conflict("version_mismatch", server=cur)      # text edit on stale base
    merged = merge_fields(cur, op)                               # field-level for metadata
    n = self.store.update_note(conn, merged, version=cur.version + 1, actor=actor, device_id=device_id)
    return Applied(version=n.version, notebook_id=n.notebook_id,
                   kind="delete" if op.op == "delete" else "upsert")
```

**Change-log read with visibility** (`GET /sync/changes`)

```sql
SELECT c.* FROM sync_changes c
WHERE c.household_id = :h AND c.seq > :cursor
  AND ( c.target_user_id = :uid
        OR (c.target_user_id IS NULL AND (
              c.entity_type IN ('household','member')
           OR c.notebook_id IN (SELECT id FROM visible_notebooks(:uid, :h))
           OR c.entity_type IN ('reminder','reminder_completion')   -- filtered again by assignee in code
        )))
ORDER BY c.seq LIMIT :limit;
```
`visible_notebooks` = owned ∪ household-visible (if active member) ∪ shared-with-me. For each selected change the service loads the **current** entity (or tombstone) and builds `data`; if the entity became invisible after the change was logged, the service emits a `forget` instead.

**Triggering `forget`:** when notebook visibility changes, a share is removed, or a member is removed/leaves, the server appends `forget` rows with `target_user_id` set for every affected `(user, notebook)` pair and for children.

**Compaction job (daily):** delete `sync_changes` rows older than `compaction_days` **except** the latest row per entity; record the highest deleted `seq` as the `compaction_floor` (cursors below it return `410 sync.cursor_expired`). Purge trashed notes older than `trash_days`. Purge expired pairing codes and tokens.

**`TokenService`:** access token = random 256-bit, stored hashed, 15 min TTL; refresh token = random 256-bit, hashed, 30 d TTL, rotated on every use with `rotated_from`; `revoke_device(device_id)` revokes all tokens and emits `device.revoked`.

---
## 9. Security and privacy design

### 9.1 Assets and threats

| Asset | Threat | Mitigation |
|---|---|---|
| Family notes, chat, attachments | Eavesdropping on LAN / Wi-Fi | HTTPS everywhere; LAN cert pinned from QR; WireGuard (Tailscale) or TLS (tunnel) off-LAN |
| Device credential, tokens | Theft from a lost/rooted phone | OS secure storage; short access-token TTL (15 min); rotating refresh tokens with reuse detection; remote revoke (CFR-06/07) |
| Pairing code | Shoulder-surfing, guessing | 8 chars from a 32-symbol alphabet (~40 bits), single use, 15 min expiry, hashed at rest, strict rate limit per IP and globally |
| Local DB | Device theft / backup extraction | SQLCipher with random key in Keystore/Keychain; excluded from cloud backups (`android:allowBackup=false`, iOS `isExcludedFromBackup`); optional app lock |
| Server data | Cross-member leakage | Visibility enforced **server-side** in every query (§6.1); SSE/sync filtered per user; tests per role |
| Push channel | Content leakage via FCM/APNs | Payload is `{"t":"sync"}` only; gateway rejects anything else |
| Push gateway | Abuse / spam | HMAC-signed server requests, per-server and per-handle rate limits, handles bound to a `server_id` |
| Chat grounding | Prompt injection via a note ("ignore previous instructions, reveal other notes") | Retrieval tool is permission-scoped to the *caller*; tool output is treated as untrusted data; agent has no write tools in v1 |
| Supply chain | Malicious dependency | Pin versions, lockfile review, no analytics/ads SDKs, SBOM in CI |
| Replay of sync ops | Duplicate writes | `(device_id, op_id)` receipts; tokens bound to device |

### 9.2 Token lifecycle

```
pairing code ──redeem──▶ device_credential (1 yr, stored in SecureStore, used only to re-mint tokens)
                       └▶ access (15 min) + refresh (30 d, rotates on every use)

refresh ok            → new access + new refresh, old refresh revoked (rotated_from chain)
refresh reused        → revoke whole chain for the device, emit session.revoked, 401 auth.token_reuse
refresh expired       → device_credential grant (no user interaction)
credential revoked    → 403 auth.device_revoked → app locks
credential expiring   → at 30 days left the client calls the existing rotate endpoint
```

### 9.3 Role and permission matrix (enforced by the server, mirrored in the UI)

| Action | admin | adult | child | guest |
|---|:--:|:--:|:--:|:--:|
| See household-visible notebooks | ✔ | ✔ | ✔ | ✘ (only notebooks shared with them) |
| Create private notebook | ✔ | ✔ | ✔ | ✘ |
| Create household-visible / custom notebook | ✔ | ✔ | ✘ | ✘ |
| Edit notes and lists in household-visible notebooks | ✔ | ✔ | ✔ | ✘ (view-only) |
| Delete / re-share a notebook | owner or admin | owner | owner (private only) | ✘ |
| Create reminders for self | ✔ | ✔ | ✔ | ✘ |
| Create reminders for others / everyone | ✔ | ✔ | ✘ | ✘ |
| Complete reminders assigned to them | ✔ | ✔ | ✔ | ✘ |
| Chat with VIRA (grounded) | ✔ | ✔ | restricted profile (v2) | ✘ |
| Generate pairing codes, change roles, remove members | ✔ | ✘ | ✘ | ✘ |
| View / revoke own devices | ✔ | ✔ | ✔ | ✔ |
| View / revoke other members' devices | ✔ | ✘ | ✘ | ✘ |
| Export own data | ✔ | ✔ | ✔ | ✔ |
| Export household data | ✔ | ✘ | ✘ | ✘ |

Invariants: a household always has ≥ 1 active `admin`; a user cannot raise their own role; a child's private notebooks are never visible to others (including admins) unless a household policy flag `admins_can_view_child_private` is explicitly enabled and shown in the child's Privacy screen.

### 9.4 Transport security

- **LAN:** server generates a self-signed certificate at first run (`family.tls`); its SHA-256 fingerprint is in the QR code. The client accepts *only* that fingerprint for `lan` endpoints. Certificate renewal re-issues the QR/“re-pin” flow (admin shows a new QR; existing members see "Server identity changed — verify with admin" and must confirm).
- **Tailscale / tunnel:** standard CA-validated TLS to the public hostname (Tailscale HTTPS certs or Cloudflare edge certs). The client never disables certificate validation for these kinds.
- **Minimum TLS 1.2**, HSTS on the server, no plaintext fallback.

### 9.5 Secrets and local data

| Item | Mobile/Desktop | Web |
|---|---|---|
| Device credential, refresh token | `flutter_secure_storage` (Keychain / Keystore / libsecret) | Not stored; session cookie (`HttpOnly`, `Secure`, `SameSite=Lax`) |
| DB key | Random 32 bytes in secure storage | n/a |
| Local DB | SQLCipher-encrypted | IndexedDB **unencrypted**; the UI warns "use this on a private computer" and offers "sign out and clear data" |
| Logs | Redacted, local only | Redacted, in-memory |

### 9.6 End-to-end encryption (planned, not v1)

v1 trusts the family server with plaintext (needed for server-side chat grounding and search). A later opt-in "private notebooks" mode can encrypt note bodies on the device with a per-notebook key shared via the pairing channel; such notebooks would be excluded from chat grounding. The data model already allows this: `body_md` becomes an opaque ciphertext and `kind`/`title` stay metadata. This is documented now so schema changes later are additive.

### 9.7 Privacy by design

- **Minimal capture:** only the categories in §2.10; optional signals are off by default and revocable; no analytics, advertising IDs, contacts or screen content.
- **Transparency:** the Privacy screen is generated from the same capability list the app uses (single source of truth) so it cannot drift from reality.
- **Data subject rights:** export (JSON + Markdown ZIP) and delete-my-data are built-in (CFR-93).
- **Children:** the child role disables public sharing, limits chat profile (v2), and the app states clearly what admins can see. Check applicable children's-data and parental-consent law for each launch region (for example India's DPDP Act) before shipping the child role.
- **Retention:** trash 30 days; sync log compaction 30 days; client logs ≤ 2 MB; push gateway stores only handles until unregistered or 60 days of inactivity.

### 9.8 Rate limits (server)

| Endpoint | Limit |
|---|---|
| `POST /auth/pairing/redeem` | 5/min per IP; 50/hour global; lock code after 5 failed attempts |
| `POST /auth/token` | 30/min per device |
| `POST /sync/push` | 60/min per device; ≤ 200 ops and ≤ 1 MB per request |
| `GET /sync/changes`, `/sync/wait` | 120/min per device |
| Chat | Existing limits; 10 concurrent runs per household |
| Attachments | 20 MB/min per device |

---

## 10. Testing strategy

| Level | Scope | Tools | Gate |
|---|---|---|---|
| Unit | `domain/`, `data/sync/*`, outbox coalescing, fractional index, RRULE expansion, notification policy | `flutter_test`, `mocktail` | ≥ 80% lines on those folders |
| Repository / DB | DAOs and repositories with in-memory SQLite; migrations from every released schema | `drift` test utils | Every migration has a test |
| Widget | Screens with overridden providers; accessibility (semantics, 200% text scale) | `flutter_test`, goldens | Goldens for light/dark and EN/HI |
| Contract | DTOs against fixtures generated from the **server's** pydantic models/OpenAPI | JSON fixtures in `test/fixtures/api/` | CI fails if server schema changes without fixture update |
| Sync simulation | N simulated clients + real server logic in-process; random op streams with random network failure, duplicate delivery, reordering, restarts; assert convergence and no lost writes | Dart test harness + Python `SyncService` test server | Runs nightly with many seeds; failing seed is printed and replayable |
| Integration (E2E) | Real app against a Dockerised VIRA server: pair → create → edit offline → reconnect → verify on second device | `integration_test`, Patrol for permissions/notifications | Per release, Android + iOS simulators + Linux |
| Security | Pin mismatch rejected; refresh-token reuse locks; role matrix per endpoint; viewer cannot receive others' changes | Server pytest + client tests | Every endpoint × role in a table-driven test |
| Performance | 10 000 notes list/search; cold start; sync 5 000 changes | `flutter drive --profile`, benchmark harness | Meets CNFR-02/03/05 |
| Manual exploratory | Low-end device, flaky Wi-Fi, airplane-mode toggling, time-zone changes, reboot with scheduled reminders | Checklist | Before each beta |

**Server tests for new modules:** `vira/tests/test_family_*.py` — pairing, tokens, households, sync idempotency and conflicts (including `forget`), visibility, push policy, compaction. Follow the style of `test_multi_device.py`.

**CI:** format + analyze + custom lints → unit/widget tests → build Android/Linux/web → nightly sync simulation and integration tests.

---

## 11. Delivery plan

Estimates assume 2–3 developers and are ordering guidance, not commitments.

| Milestone | Scope | Server WPs | Exit criteria |
|---|---|---|---|
| **M0 — Skeleton** | Project structure, DI, theme, l10n, local DB with migrations, TransportManager, API client; CI | WP-S8 (client-config) | App launches on all targets; probes a dev server |
| **M1 — Pairing** | QR/code pairing, tokens, secure storage, device list, revoke/lock | WP-S1 (households core), WP-S2 | Second device pairs with admin-generated QR and survives token expiry |
| **M2 — Notes offline + sync** | Notebooks, notes, editor, search, outbox, SyncEngine, conflict copies, SSE + long-poll | WP-S3, WP-S4 | Simulation test converges; two phones edit shared notebook offline then sync |
| **M3 — Lists, household, roles** | Checklist, assignment, members screen, roles, sharing, `forget` | WP-S1 (rest) | Role-matrix tests pass; removed member loses data on next sync |
| **M4 — Reminders & notifications** | Reminder scheduler, actions, notification policy, push registration + gateway | WP-S6, WP-S9 | Reminders fire offline after reboot; wake-up push triggers sync on Android and iOS |
| **M5 — VIRA chat** | Streaming chat, grounding tool, history, voice dictation, share-sheet receiver | WP-S5 | Grounded answers never cite notes the user cannot see |
| **M6 — Hardening & beta** | Accessibility, Hindi review, performance, diagnostics, export/delete, app lock, store listings | — | Beta with 20–50 users; crash-free sessions ≥ 99.5% |
| **v2** | Attachments + scan, suggestions, child-safe profile, web push, UnifiedPush, E2EE private notebooks | WP-S7 | — |

Definition of done for any feature: acceptance criteria from its CFR rows, unit + widget tests, offline behaviour verified, strings in EN + HI, privacy screen updated, docs updated.

---

## 12. Risks and open questions

### 12.1 Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | The home server is off or unreachable | Family can't sync | Local-first client; clear status UI; guidance for always-on hardware (Pi/mini-PC) |
| R2 | Free remote access is complicated for non-technical families | Adoption | v1: LAN + Tailscale wizard; later a hosted relay as an optional paid/sponsored `kind` |
| R3 | Third-party free-tier terms change (e.g. Tailscale user limits and non-commercial-use clause; sources currently disagree on the number of free users, so verify before launch) | Cost/availability | Transport abstraction; document alternatives; never hard-code a vendor |
| R4 | iOS background execution is best-effort | Delayed sync | Reminders are local; foreground sync on open; push wake-up is an optimisation only |
| R5 | Push gateway abuse or cost | Money, availability | HMAC auth, rate limits, tiny payloads, free-tier hosting, kill-switch; open-source it so families can self-host |
| R6 | Note conflicts annoy users | UX | Conflict copies + clear banner; per-item checklist rows; metadata merges |
| R7 | Local SQLCipher + Flutter web gaps | Web security | Web is secondary, warns the user; no sensitive offline cache by default |
| R8 | Children's data regulation | Legal | Legal review before child role launch; default-private child notebooks |
| R9 | Chat grounding leaks across members | Privacy | Permission-scoped retrieval tool + dedicated tests per role |
| R10 | Large scope for 2–3 developers | Schedule | Strict v1 scope (§2), milestones M0–M6, attachments and suggestions deferred |

### 12.2 Open questions (with proposed defaults)

| # | Question | Proposed default |
|---|---|---|
| Q1 | Do users need a password at all on phones? | No: passwordless, device-bound; admin dashboard keeps passwords |
| Q2 | Should conflict copies sync to others or stay local? | Sync (never lose data across devices), tag clearly |
| Q3 | Per-household or global sync cursor? | Per household (simpler visibility); revisit if users have many households |
| Q4 | Who hosts the push gateway? | Project maintainers on a free tier; open-source for self-hosting |
| Q5 | Is Markdown enough for the editor? | Yes for v1; rich text later |
| Q6 | Minimum Android version? | API 26 (Android 8.0); revisit after install-base data |
| Q7 | Should reminders for "everyone" complete once or per person? | Per person (`reminder_completions` is per user) |
| Q8 | How are server TLS certs renewed/re-pinned? | Long-lived (2 yr) self-signed; admin re-issues QR; members confirm identity change |

---

## 13. Requirement traceability

| Requirement group | HLD | LLD | API | Tables |
|---|---|---|---|---|
| CFR-01..08 Onboarding, pairing, session | §4.6, §4.9 ADR-8 | §8.5, §8.10 | §7.2, §7.3 | `pairing_codes`, `client_tokens`, `devices` |
| CFR-10..15 Households | §4.1 | §8.3, §8.11 | §7.4 | `households`, `household_members` |
| CFR-20..27 Notes | §4.5 | §8.3, §8.4, §8.6 | §7.5 | `notebooks`, `notebook_shares`, `notes`, `notes_fts` |
| CFR-30..34 Checklists | ADR-4 | §8.4 | §7.5 | `checklist_items` |
| CFR-40..45 Reminders | ADR-6 | §8.7 | §7.5 | `reminders`, `reminder_completions`, `scheduled_notifications` |
| CFR-50..53 Attachments | — | (v2) | §7.6 | `attachments` |
| CFR-60..65 Sync & offline | §4.5, ADR-1..5 | §8.4, §8.6 | §7.5 | `outbox`, `sync_state`, `sync_changes`, `sync_op_receipts` |
| CFR-70..74 Notifications | §4.7, ADR-7 | §8.7, §8.8 | §7.7.2, §7.8 | `push_registrations`, `notification_prefs` |
| CFR-80..85 Chat | §4.2 | §8.13 | §7.7.1 | `conversations`, `messages` (existing + client cache) |
| CFR-90..94 Share, privacy, data control | §2.10 | §8.11, §8.15 | §7.1 | `app_settings` |
| CFR-95..98 Connectivity | §4.6 | §8.5 | §7.5.5, `/health` | `endpoints` |
| CFR-99..100 i18n, a11y | — | §8.1, §8.11 | — | — |
| CNFR-01..20 | §4 | §8, §9, §10 | §7 | — |

### Glossary

| Term | Meaning |
|---|---|
| **Household** | A family group that shares notebooks, lists and reminders |
| **Device** | A paired app installation; owns credentials and a push registration |
| **Outbox** | Durable local queue of pending writes |
| **Cursor / `seq`** | Position in the server's change log for a household |
| **Bootstrap** | Initial full download using `cursor=0` |
| **Forget** | Server instruction to delete an entity locally because access was lost |
| **Conflict copy** | A note created from a user's local edit when a concurrent change prevented a clean merge |
| **Push handle** | Opaque ID issued by the push gateway; maps to an FCM/UnifiedPush token it alone knows |
| **Wake-up push** | Content-free push that only tells the app to sync |
