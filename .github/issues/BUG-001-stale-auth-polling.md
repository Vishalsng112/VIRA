# BUG-001: Stale sessions and revoked device credentials cause endless 401 polling

**Status:** fixed on `fix/stale-auth-polling`
**Severity:** medium
**Area:** authentication, VIRA Link, web dashboard
**Labels:** `bug`, `auth`, `client`, `dashboard`

## Summary

After a session expires or a device credential is revoked, VIRA Link and the web
dashboard keep calling protected endpoints and receive `401 Unauthorized` every
30 seconds. The client has no recovery path and the dashboard refresh loop keeps
retrying until navigation completes.

## Environment

- VIRA Server started with `python run.py`
- Browser dashboard at `http://localhost:8000`
- VIRA Link client enrolled as a device
- Session or device credential previously rotated, revoked or expired

## Steps to reproduce

1. Sign in to the dashboard and leave it open until the session expires or is
   revoked.
2. Open VIRA Link with a device credential that has been revoked or replaced.
3. Observe the server log.

## Expected behaviour

- A stale dashboard session redirects to login once and stops polling.
- A stale device credential stops sync and command polling, clears the invalid
  device credential and returns the client to a sign-in state with a clear
  message.
- No repeated `401` requests every 30 seconds.

## Actual behaviour

```text
INFO: 127.0.0.1:50812 - "GET /health HTTP/1.1" 401 Unauthorized
INFO: 127.0.0.1:50820 - "GET /api/v1/devices/11eaa989-7f24-4438-a435-5dab213793be/commands/pending HTTP/1.1" 401 Unauthorized
```

Both requests repeat on their polling intervals.

## Root cause

- `/health` is admin-only and requires a valid browser session.
- `/api/v1/devices/{id}/commands/pending` requires a valid device credential.
- `SyncService` stopped on device-auth failure, but the separate 30-second
  command poller was never cancelled.
- `_stopServices()` also did not cancel the command timer.
- The dashboard redirected on `401` but kept its refresh interval alive.

## Fix

- Cancel the command timer when services stop.
- Treat device/session auth failures as a terminal connection state:
  stop services, clear the stale device credential, disconnect and show an
  actionable sign-in message.
- Stop the dashboard refresh interval on the first `401` and redirect once.
- Do not poll from hidden dashboard tabs.

## Acceptance criteria

- [x] No repeated `401` polling from VIRA Link after a revoked device credential.
- [x] No repeated `401` polling from the dashboard after session expiry.
- [x] Client shows a clear re-enrollment/sign-in message.
- [x] Command timer is cancelled on disconnect.
- [x] Existing capture/sync behaviour is unchanged while credentials are valid.
- [x] Backend and Flutter test suites pass.

## Verification

```bash
python3 -m unittest discover -s vira/tests -q
cd client && flutter analyze && flutter test
node --check vira/web/static/app.js
```

## Notes

This is **not** caused by a legacy duplicate route. There is a single `/health`
route and a single device command endpoint; both correctly enforce
authentication. The defect was in client-side recovery and polling lifecycle.
