# VIRA threat model

This is a working threat model for the self-hosted VIRA Server and the VIRA Link
device companion. It names assets, trust boundaries, realistic threats and the
controls that exist today. It is deliberately concrete: every control points at
code, a test or an operational command.

See the [security overview](../../user/security.md) for the user-facing version.

## Scope

**In scope**

- VIRA Server API, dashboard, chat, memory, RAG, workflows, tools, MCP, plugins.
- Multi-user and multi-device authorization and consent.
- Docker deployment, backups, master key and audit trail.
- VIRA Link device enrollment, credentials and event ingestion.

**Out of scope**

- A compromised host, hypervisor, Docker daemon or supply-chain compromise of the
  base image.
- Physical access to an unlocked device.
- The security of third-party cloud model providers.
- Formal multi-tenant SaaS isolation. VIRA is local-first, not a hosted service.

## Assets

| Asset | Why it matters |
|---|---|
| User sessions and passwords | Account takeover |
| Device credentials | Spoofed telemetry, data injection |
| Device telemetry and insights | Private behavioural data |
| Conversations, memories and RAG documents | Private personal/work content |
| Master key (`data/.vira_master_key`) | Decrypts sensitive fields |
| Provider API keys and MCP secrets | Financial loss, third-party access |
| Tool execution capability | Shell, filesystem, sandbox and network actions |
| Audit and tool-call records | Accountability and incident response |
| Backups | Recovery after data loss or ransomware |

## Trust boundaries

```text
Browser / VIRA Link
        │  authenticated HTTP(S)
        ▼
VIRA Server process ── tool executor ── local tools / sandbox / MCP servers
        │                    │
        │                    └── destructive calls ── approval queue ── human
        ▼
SQLite/PostgreSQL + data volume + master key
        │
        └── optional cloud model provider (outbound)
```

1. **User/device ↔ server.** Untrusted input: messages, events, uploaded files.
2. **Server ↔ model.** Model output is untrusted. It may propose tool calls.
3. **Server ↔ tools/MCP/plugins.** Tool output is untrusted and may contain
   prompt injection; MCP servers and plugins are separate code.
4. **Server ↔ host.** Shell, filesystem and sandbox tools cross this boundary.
5. **Server ↔ backup media.** Backups contain the whole database and need the
   master key to be useful.

## Threats and controls

### 1. Malicious prompts and tool injection

**Threat.** A user message, web page, document, memory or MCP result tells the
model to ignore its instructions, call a destructive tool, exfiltrate data or
hide the action from the user.

**Controls**

- Tool output and retrieved text are observations, not instructions; the loop
  prompt says never invent tool results and never repeat identical calls.
- Tools are allow-listed per caller and per MCP policy before execution.
- Database tools are read-only, single-statement, admin-only for custom SQL and
  reject secret columns/functions.
- Destructive local calls now stop at a human approval gate (see threat 4).
- Every tool call is recorded with status, permission decision and caller.
- Web tools apply SSRF checks and bounded output.

**Residual risk.** Prompt injection is not solved. A model can still be tricked
into proposing an allowed but harmful call. Approval gates and least privilege
limit the blast radius; they do not make the model trustworthy.

**Verify**

```bash
python3 -m unittest vira.tests.test_security_phase3 vira.tests.test_database_query -v
```

### 2. Cross-user data access

**Threat.** User B reads, mutates or deletes user A's conversations, memories,
RAG documents, devices, insights or workflows; or an agent's context crosses
users.

**Controls**

- Every chat/memory/RAG/workflow query is scoped by `user_id`.
- Device access is deny-by-default through `user_device_access`; unknown and
  unauthorised devices both return 404 to avoid existence disclosure.
- Insight routes call `DeviceService.authorize` before loading events.
- Agent tool context injects the authenticated caller identity; database MCP
  tools never trust an identity supplied by the model.
- SSE fan-out filters every event through `visibility.authorize_event`.

**Residual risk.** Admin roles intentionally see fleet-wide metadata. System
memories (`user_id IS NULL`) are visible to all active users by design.

**Verify**

```bash
python3 -m unittest vira.tests.test_security_phase3 vira.tests.test_multi_device -v
```

### 3. Device credential leakage

**Threat.** A stolen device token injects events as another device, reads queued
commands or keeps reporting after revocation.

**Controls**

- Device credentials are random, scoped, expiring, revocable and stored hashed.
- Raw tokens are shown once at enrollment.
- Ingestion checks the path device against the credential's device.
- Heartbeat/ingestion have separate per-device rate limits.
- Revocation is terminal for that credential; re-enrollment issues a new one.
- Credential rotation and expiry are visible in fleet operations.

**Residual risk.** A token captured before rotation is valid until it expires or
is revoked. Use TLS and device disk protection.

**Verify**

```bash
python3 -m unittest vira.tests.test_multi_device -v
python3 -m vira doctor
```

### 4. Destructive tool calls

**Threat.** The model calls shell, filesystem writes, sandbox execute/install or
a custom MCP tool and changes the host, deletes data or runs untrusted code.

**Controls**

- Shell is a read-only command allow-list with no shell expansion, chaining,
  pipes or redirects.
- Filesystem is confined to the configured workspace root.
- Sandbox applies CPU, memory, process and timeout limits; it is not a VM.
- **Approval gates:** destructive calls create a single-use, expiring request
  and return `APPROVAL_REQUIRED` instead of executing. A user/admin must approve
  the exact tool + arguments in `/api/v1/approvals`; the next identical call
  consumes it once.
- Approval arguments are redacted before storage and decisions are audited.

**Residual risk.** An approval is a human decision; a distracted approver can
authorize a harmful call. The request shows the tool and arguments, not the
model's hidden intent.

**Verify**

```bash
python3 -m unittest vira.tests.test_security_phase3.ApprovalTests -v
```

### 5. Plugin and MCP supply chain

**Threat.** A third-party plugin or MCP server declares one capability, then
reads secrets, registers dangerous tools or calls the network.

**Controls**

- Plugins declare permissions in their manifest; undeclared permissions fail
  loading. They run in-process, so they are trusted local code.
- MCP servers are installed explicitly and can be enabled/disabled.
- MCP policy supports `default`, `user`, `role` and `org` allow-lists; the tool
  executor enforces them per caller.
- MCP environment/command/URL fields are hidden from the database tools.
- Installed MCP servers must be explicitly connected; connection failures do not
  silently grant tools.
- CI runs secret scanning and a dependency audit.

**Residual risk.** A malicious plugin that declares the permissions it needs can
still act within them. Install only code you trust.

**Verify**

```bash
python3 -m unittest vira.tests.test_p4 -v
```

### 6. Backup and key loss

**Threat.** The database is lost, corrupted or ransomware-encrypted; the master
key is lost; a backup is untested and cannot be restored.

**Controls**

- The worker schedules a consistent database backup every 24 hours and prunes
  old copies (`jobs.backup_keep`).
- `scripts/backup.sh` / `scripts/restore.sh` wrap the same helpers.
- Restore keeps a `pre-restore` safety copy.
- `scripts/backup_drill.py` creates a backup, copies it, opens it and runs
  `PRAGMA integrity_check`, recording RPO/RTO without touching the live DB.
- The master key is stored separately and can be supplied by env or file.

**Residual risk.** Backups are not application-encrypted as a whole. Protect the
backup directory with OS permissions and disk encryption, and back up the master
key **separately** from the database.

**Verify**

```bash
python3 scripts/backup_drill.py --json
python3 -m unittest vira.tests.test_backup_drill -v
```

### 7. Audit tampering and data leakage in exports

**Threat.** An administrator exports logs containing passwords, bearer tokens or
raw tool payloads and shares them; or an attacker deletes/edits audit rows.

**Controls**

- Authentication, admin, device and approval actions are appended to
  `auth_audit`; tool calls go to `tool_calls`.
- `/api/v1/admin/audit/export` redacts secret-looking keys and token-shaped
  values before JSON/CSV serialization and records the export itself.
- Session hashes are redacted; payload columns are not part of the export.
- Database tools hide secret columns and internal tables.

**Residual risk.** Audit tables live in the same database. A host-level attacker
who can write the database can alter them; ship logs off-host for high-assurance
deployments.

**Verify**

```bash
python3 -m unittest vira.tests.test_security_phase3.AuditExportApiTests -v
```

### 8. Container escape and host sensing

**Threat.** An agent escapes the Bubblewrap sandbox or the container and reaches
the host; or users assume Docker gives full host telemetry.

**Controls**

- The container runs as a non-root user with `no-new-privileges`, all Linux
  capabilities dropped, a read-only root filesystem and a small `noexec` `/tmp`.
- No Docker socket mount, no `privileged`, only the data volume and `config.yaml`.
- Bubblewrap provides a private filesystem namespace with resource limits.
- Process limits bound fork bombs.

**Residual risk.** Bubblewrap and containers share the host kernel. They are not
a VM boundary. Host sensors inside Docker see only what the container exposes:
the container's CPU/memory/process view, mounted paths and network namespace.
Phone/desktop signals come from VIRA Link, not from the server container.

**Verify**

```bash
docker compose config | grep -E 'privileged|cap_drop|read_only|no-new-privileges|docker.sock'
python3 -m unittest vira.tests.test_sandbox -v
```

## Disclosure

Report vulnerabilities privately as described in
[SECURITY.md](https://github.com/Vishalsng112/VIRA/blob/main/SECURITY.md).
