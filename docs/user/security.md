# Security and privacy overview

VIRA is local-first by design, but “local” is not a complete security model. This
page describes what is implemented, what it protects, and where the limits are.

For reporting a vulnerability, see [SECURITY.md](https://github.com/Vishalsng112/VIRA/blob/main/SECURITY.md).
The engineering threat model is in
[the developer manual](../dev/security/threat-model.md).

## Principles

- **Local-first:** the server, database, model and device data run on infrastructure
  you control. Cloud model providers are optional.
- **Least privilege:** users, devices, agents, tools and plugins have separate
  identities and permissions.
- **Explicit consent:** device collectors are opt-in and can be revoked per device.
- **Auditable:** authentication, admin actions and tool calls are recorded.
- **Bounded execution:** tool calls have permissions, timeouts and (where available)
  a sandbox.
- **No security theatre:** known limitations are listed below.

## Authentication and sessions

- Passwords and recovery codes are hashed with bcrypt; plaintext passwords are
  never stored.
- User sessions are random tokens stored as hashes with an expiry. Logout,
  password reset and admin disable/delete revoke sessions.
- Device credentials are separate from user sessions, scoped, expiring and
  revocable. Raw device tokens are shown once and stored as hashes.
- The session cookie is signed with `auth.secret_key`. Set a random value before
  exposing the server.
- `auth.https_only` must be enabled when the server is behind HTTPS/TLS.
- Prefer private network access (Tailscale) over public exposure. See
  [Remote access with Tailscale](remote-access.md).

## Authorization

- Users have `admin` or `user` roles.
- Device access is granted per user/device through explicit access rows.
- Admin-only routes cover users, fleet, audit, jobs, backups, health, metrics,
  configuration, plugins, MCP servers and updates.
- Tool execution checks the tool permission, the agent’s runtime permission, and
  installed-MCP allow/deny policies.
- Database tools add a further role gate: custom SQL requires an administrator;
  every user can read only their own account summary.

## Destructive tool approvals

Destructive calls do not execute immediately. Shell, filesystem writes, sandbox
writes/execute/install and any tool configured as destructive create a
**single-use approval request** and return `APPROVAL_REQUIRED` to the agent.

- The request records the tool, action, redacted arguments, caller, agent, run
  and expiry (30 minutes by default).
- The dashboard **Security** page shows the pending queue with Approve/Deny
  buttons; the same actions are available at `/api/v1/approvals`.
- The next identical call from the same user consumes the approval once.
- Every decision is written to the audit log.
- Approvals are enabled by `security.approvals.enabled` in `config.yaml`; the
  tool/operation lists can be extended without changing code.

This is a human gate, not a sandbox. It limits accidental or injected destructive
actions and leaves an audit trail.

## Device sensing and consent

- VIRA Link collectors are individually enabled and can be disabled at any time.
- Consent is stored per device and collector with purpose and retention.
- The ingestion path rejects events for collectors that are not consented
  (`consent_denied`) and applies retention overrides.
- The server itself is registered as a device, but local sensors are separate from
  remote device data.
- Inside Docker, host sensor visibility is limited by the container boundary. This
  is a deliberate safety trade-off, not a promise of full host telemetry.

## Encryption

- Sensitive configuration values and device event payloads are encrypted with
  Fernet using a master key.
- The default key file is `data/.vira_master_key`. `VIRA_MASTER_KEY` and
  `VIRA_MASTER_KEY_FILE` can override it.
- **Back up the master key separately.** Without it, encrypted values cannot be
  recovered.
- This is field-level encryption for sensitive values, not full-database
  encryption. Protect the host and the database file with OS permissions and disk
  encryption as well.

## Container and sandbox

- The server image runs as a non-root user.
- The default Compose services use `no-new-privileges: true`, drop **all** Linux
  capabilities, run with a **read-only root filesystem** and a small `noexec`
  `/tmp` tmpfs, and set process limits.
- The default Compose file does **not** use `privileged`, does not mount the Docker
  socket, and mounts only the data volume and `config.yaml`.
- The Bubblewrap sandbox gives agents a private filesystem namespace with CPU,
  memory, process and timeout limits. It is designed for development workloads,
  **not** for running hostile code. Use a container or VM for a stronger boundary.
- Sandbox workspaces are persistent and owned by an agent plus the signed-in
  user; explicit sandbox IDs owned by another user are rejected. Commands run
  with a cleared environment, read-only system paths, `--cap-drop ALL`, and only
  the workspace and artifacts mounts writable.
- The shipped `config.yaml` lists `sandbox` in `security.approvals.safe_tools`,
  so a ChatAgent can build, write and execute inside its isolated environment
  without a prompt for every file or command. Remove it from `safe_tools` to
  restore per-call approval. Read-only inspection operations never need
  approval, and shell/filesystem tools remain gated regardless.
- Plugins run in-process and are treated as trusted local code. Install only
  plugins you trust.

### What host sensing looks like inside Docker

Docker is a boundary, not magic. Inside the server container:

- hardware/CPU/memory/process sensors see the **container's** view of the host,
  subject to cgroup limits and the container's PID namespace;
- filesystem sensors see only paths mounted into the container (by default the
  data volume and `/app`);
- network sensors see the container network namespace;
- phone/desktop signals (app usage, focus, battery, health) come from **VIRA
  Link**, not from the server container.

If you need richer host telemetry, run trusted sensors outside the container and
ingest through the normal consent-gated event path. Do not mount the Docker
socket or run the container privileged to work around this.

## Database tools

The read-only database MCP server (`database_query`) is deliberately constrained:

- one `SELECT` or `WITH` statement;
- read-only SQLite connection (`mode=ro`, `query_only`) or read-only PostgreSQL
  session;
- write keywords, multiple statements, `PRAGMA`, `ATTACH`, secret columns and
  internal tables rejected;
- maximum 200 rows, statement timeout and result-size caps;
- custom SQL restricted to administrators;
- caller identity injected by the agent loop, never trusted from the model;
- `{{caller_user_id}}` for the signed-in user.

See [Database tools](../dev/architecture/database-tools.md).

## Audit and observability

- `auth_audit` records authentication, admin and device actions with allowed/denied
  status and correlation IDs.
- `tool_calls` records tool name, request, result, status, permission decision,
  duration and agent. Treat this table as sensitive; it can contain tool inputs and
  outputs.
- The dashboard exposes audit, metrics, health, jobs and alerts to administrators.
- Administrators can export a **redacted** audit trail:

  ```bash
  curl -s "http://localhost:8000/api/v1/admin/audit/export?kind=all&format=json" \
    -H "Authorization: Bearer <admin-session>" > vira-audit.json
  ```

  Secret-looking keys and token-shaped values are replaced with `[REDACTED]`,
  session hashes are not exported, and the export itself is audited. CSV is
  available with `format=csv`; `kind` is `audit`, `tool_calls` or `all`.

## Backups, RPO and RTO

- The worker schedules a database backup every **24 hours**; this gives a
  documented **RPO target of 24 hours**. `jobs.backup_keep` controls retention.
- **RTO** depends on database size and host speed. Measure it on your own data
  rather than assuming a number.
- Run the non-destructive drill to record both on your machine:

  ```bash
  python3 scripts/backup_drill.py --write docs/dev/runbooks/backup-restore.md
  ```

  The drill creates a real backup, copies it, opens it independently and runs
  `PRAGMA integrity_check`. It never overwrites the live database.
- Restore procedure: stop the API and worker, run `scripts/restore.sh <backup>`,
  start the services and verify `/livez`, sign-in and recent conversations. A
  `pre-restore` safety copy is kept.
- **Back up the master key separately.** A database backup without
  `data/.vira_master_key` (or `VIRA_MASTER_KEY`) cannot decrypt sensitive fields.

Current drill evidence: [backup and restore drill](../dev/runbooks/backup-restore.md).

## Supply chain and CI

- The repository CI runs **gitleaks** secret scanning and **pip-audit** against
  `requirements.txt` on every push and pull request, plus a weekly scheduled run.
- Release artifacts include checksums where the release workflow produces them.
- Plugins/MCP servers are third-party code. Review the manifest and permissions
  before installing.

## Generated tools and agents

Generated artifacts follow **draft → approved → enabled** and can only be
approved/enabled by an administrator. A draft or disabled artifact is never
registered and is re-checked at invocation time, so it cannot execute just
because a model asked for it. Generated tools are restricted to one HTTPS GET
with an explicit host allow-list, no custom headers or secrets, SSRF checks and
bounded, optionally JSON-validated output. Generated agents run with an
allow-listed tool set and a step budget. Every transition is audited in
**Agents → Generated tools and agents**.

## Client diagnostics

VIRA Link diagnostics are **off by default**. When enabled, errors are stored
locally with a bounded history and are uploaded only when the user chooses **Send
diagnostic report**. The client removes credentials, URLs, token-shaped text,
device identifiers, usernames and chat/event content before storage; the server
applies a second redaction pass and stores the report in the administrator audit
view. See the [platform matrix](platforms.md#diagnostics).

## Network exposure

- By default, Compose publishes port 8000 on `0.0.0.0`. To restrict it to the local
  machine, set `VIRA_BIND_ADDRESS=127.0.0.1` in `.env`.
- Put VIRA behind a TLS-terminating reverse proxy before exposing it beyond a
  trusted network.
- Do not publish Ollama (`11434`) to the internet.
- Rate limits are configured in `config.yaml` under `rate_limits`.

## Known limitations

- Prompt injection is an open problem. Tool output and retrieved documents are
  treated as untrusted, but no system can guarantee safe behaviour for every model.
- The Bubblewrap sandbox is not a virtual-machine boundary.
- Plugins are trusted in-process code.
- CORS is intentionally narrow for local HTTP; a production reverse proxy still
  needs its own policy.
- SQLite file access is protected by OS permissions, not by application-level
  encryption of the whole file.
- There is no formal verification of generated tools or agents. Do not treat
  “verified” as a current capability.
- Backups are only as good as the tested restore process. Run the drill.
- Multi-user isolation has tests, but it is not a formally audited multi-tenant
  boundary.
- Approval gates require a human decision and are not a sandbox or a policy
  engine. A destructive tool outside the configured list is not automatically
  gated.

## How to verify

```bash
# approvals, isolation, redaction and audit export
python3 -m unittest vira.tests.test_security_phase3 -v

# multi-user / multi-device isolation and stream ACL
python3 -m unittest vira.tests.test_multi_device -v

# read-only database tool boundary
python3 -m unittest vira.tests.test_database_query -v

# backup/restore drill
python3 scripts/backup_drill.py --json

# whole suite (recommended before a release)
python3 -m unittest $(ls vira/tests/test_*.py | sed 's#/#.#g; s#\.py$##')
```

Security-sensitive deployments should also run their own dependency scanning,
secret scanning, backup restore drills and penetration testing. The engineering
detail for each threat is in the
[threat model](../dev/security/threat-model.md).
