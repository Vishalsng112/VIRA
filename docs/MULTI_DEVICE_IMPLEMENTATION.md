# VIRA Multi-Device Implementation Notes

Implements `VIRA_MULTI_DEVICE_DESIGN.md` against the current code base. The
server is a platform; endpoint devices connect through `/api/v1`. **The server
installation is itself an endpoint device** (`devices.is_server_local = 1`): its
in-process sensors publish through the same `EventIngestionService` as remote
devices (via `LocalDeviceDispatcher`), so server events have device provenance,
the same allow-list, deduplication and retention.

## What changed

| Area | Change | Files |
|---|---|---|
| Schema | Versioned migrations (`schema_migrations`): `users.public_id/status/deleted_at`, `devices`, `device_credentials`, `user_device_access`, `device_events`, `device_latest_state`, `messages.created_by_device_id`, `memories.device_id`, `outbox_events.device_id`, extra `auth_audit` columns, WAL mode | `auth/migrations.py`, `auth/database.py` |
| Identity | Typed principals (`UserPrincipal`, `DevicePrincipal`, `ServicePrincipal`); bootstrap-once (atomic); disabled/deleted users cannot authenticate; password change revokes sessions | `auth/principals.py`, `auth/auth.py` |
| Admin | User create/list/get/update/delete (soft), last-admin protection, audit | `auth/admin.py`, `api/routes_admin.py` |
| Devices | Register (credential shown once, hash stored), list/get/rename, rotate (step-up password), revoke, retire, access grants (`owner/operator/viewer`), heartbeat, capability status, state machine | `devices/service.py`, `devices/store.py`, `api/routes_devices.py` |
| Ingestion | `POST /api/v1/devices/{id}/events:batch`: credential-derived device id, allow-list, schema/time/size validation, idempotent by `event_id`, conflict audit, event row + outbox in one transaction, per-device rate limit | `devices/ingestion.py`, `devices/policy.py`, `devices/ratelimit.py` |
| Server as device | Local device created at boot, owned by admins, heartbeat + retention task; sensors publish via local ingestion | `devices/local_device.py`, `kernel/kernel.py` |
| Isolation | SSE filtered per user/device grant (viewer payloads redacted, revocation honoured); `agent.response` addressed to the requester only; admin-only kernel/config/ops routes; `/config` redacts secrets; device-scoped memories | `devices/visibility.py`, `api/streams.py`, `api/app.py`, `auth/database.py` |
| Chat | Optional `device_id` validated against grants; stored on messages; `POST /api/v1/conversations/{id}/messages` | `api/app.py` |
| Agents | Router passes `device_id`/`actor_user_id`; scheduler queues events instead of dropping them; `ChatAgent` is re-entrant (no per-request instance state); a failed event no longer disables an agent; `AutonomousAgent` keeps baselines per device | `agent_orchestration/*`, `agent/*` |
| API conventions | `/api/v1` aliases for legacy routes, error body `{detail, error:{code,message,correlation_id}}`, server-side `X-Correlation-ID`, cursor pagination | `api/deps.py` |
| Client | Reference endpoint client: enroll, secure credential file, offline SQLite queue, backoff, heartbeat | `clients/endpoint_agent.py` |

## Requirement traceability (implemented)

FR-ID-01..07, FR-DEV-01..08, FR-EVT-01..08 and 10, FR-APP-01..03, NFR-SEC-01/02/04,
NFR-REL-01, NFR-OBS-01, NFR-COMP-01 map to the tests in
`vira/tests/test_multi_device.py` (46 tests).

## Not implemented / known limits

* PostgreSQL adapter, external broker, time-series store (SQLite/WAL only; design lists these as production options).
* `Idempotency-Key` for `POST /devices` (chat already requires it).
* Request-level rate limiting for user APIs and login throttling (device ingest and heartbeat are limited; limiter is in-process).
* TLS termination, `https_only` cookies and CSRF protection are deployment/config work.
* Hard user deletion / retention workflow (delete is a tombstone; conversations and memories are kept).
* A web UI for user/device administration (use the API).
* Android/iOS clients (only the reference Python client).
* The unversioned legacy routes remain as adapters; the web UI still uses them.
* `docs/SYSTEM_DESIGN.md` / `VIRA_DOCS.md` / diagrams were not rewritten.

## Operating notes

* After upgrading, existing users are kept (all are `admin`); each gets a `public_id`. Run once; migrations are idempotent.
* Create users: `POST /api/v1/admin/users`. Enrol a laptop: `python -m vira.clients.endpoint_agent enroll --server http://HOST:8000 --username alice`.
* Set `auth.secret_key` and serve behind TLS before exposing remote devices.
* Run tests: `python -m unittest vira.tests.test_multi_device -v`.
