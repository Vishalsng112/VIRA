# Sandbox execution environments

Status: implemented

The sandbox is VIRA's local execution environment for agents. It is built for
development work: writing projects, running builds and tests, installing
dependencies, starting background servers, and archiving the resulting
workspace. It is **not** a virtual machine and must not be used for hostile
code. Use a container or VM for a stronger boundary.

## Model

```text
AgentTool("sandbox")
        │
        ▼
SandboxManager  ── ownership, policy, file operations, jobs, archive
        │
        ▼
BubblewrapBackend ── namespace, mounts, limits, process execution
        │
        ▼
$sandbox.root/<sandbox_id>/
    metadata.json        # lifecycle, policy, owner, timestamps, counters
    workspace/           # bind-mounted at /workspace
    artifacts/           # bind-mounted at /artifacts
```

A sandbox is persistent across tool calls and server restarts. On start-up the
backend scans `metadata.json` files and restores the registry. Sandboxes that
were running when the server stopped are marked idle.

### Ownership

Each sandbox records both the owning agent and (when available) the signed-in
user. Every tool call provides the caller identity; explicit IDs that belong to
another agent or user are rejected. Omitting `sandbox_id` reuses the current
sandbox for `(agent_id, user_id)` or creates one on demand.

### Isolation

Bubblewrap provides:

- a private PID, UTS, IPC and (by default) network namespace;
- read-only `/usr`, `/bin`, `/lib`, `/usr/local` and `/etc`;
- an empty `/tmp`, private `/home`, `/root`, `/run`, `/var`, `/opt`, `/srv`,
  `/mnt`, `/media`, `/data` and a hidden sandbox root;
- only the sandbox `workspace` and `artifacts` are writable bind mounts;
- cleared environment (`--clearenv`) with a minimal allow-list plus explicit
  variables supplied by the caller;
- `--cap-drop ALL`, `--die-with-parent` and a new session;
- RLIMIT CPU, address space and process counts, plus a wall-clock timeout.

The workspace is always mounted before the sandbox root is hidden; Bubblewrap
resolves bind sources in the new namespace.

## Policies

`SandboxPolicy` is immutable and stored with each sandbox. Defaults come from
`config.yaml` and can be overridden per sandbox at creation.

| Field | Default | Meaning |
|---|---|---|
| `network_enabled` | `false` | Attach a network namespace with outbound access |
| `timeout_seconds` | `900` | Maximum wall clock per command |
| `max_processes` | `128` | Process/thread headroom for the sandbox |
| `cpu_seconds` | `600` | RLIMIT_CPU per process |
| `memory_mb` | `2048` | RLIMIT_AS address-space limit |
| `allow_package_install` | `true` | Allow `pip`/`npm` installs |
| `allow_shell` | `true` | Allow shell strings (`bash -lc`) |
| `workspace_quota_mb` | `2048` | Soft quota for project files after writes |
| `max_output_bytes` | `200000` | Per-stream output cap |

Changing a policy requires `operation="update"`; it is not silently mutated by
an execute call.

## Tool surface

The `sandbox` tool has one explicit `operation` field. Paths are always relative
to the workspace (absolute `/workspace/...` is accepted and normalized).

| Group | Operations |
|---|---|
| Lifecycle | `create`, `sandboxes`, `info`, `update`, `delete` |
| Files | `write`, `write_many`, `read`, `list`, `stat`, `search`, `mkdir`, `delete_file`, `move`, `copy` |
| Execution | `execute`, `install`, `jobs`, `job`, `job_logs`, `job_kill` |
| Persistence | `archive`, `restore`, `usage` |

Common aliases (`run`, `exec`, `bash`, `ls`, `cat`, `mv`, `cp`, `rm`, `stats`,
`export`, `import`) are normalized rather than rejected, so small models can
recover from naming mistakes.

### Execution

- A command **string** runs as `/bin/bash -lc "<script>"` inside the sandbox, so
  pipes, `&&`, redirections and multi-line build scripts work.
- A command **array** is executed directly with no shell.
- `cwd` must stay inside `/workspace` or `/artifacts`.
- `env` is validated and merged over the minimal sandbox environment.
- `stdin` is supported for interactive-looking scripts and patch application.
- `execute` returns `exit_code`, `stdout`, `stderr`, `truncated` and
  `duration_ms`. A non-zero exit is reported as a tool error so the agent can
  correct it.
- `background=true` starts a job and returns a `job_id`. Use `job`,
  `job_logs` and `job_kill` to poll, read and stop it. Output is capped and both
  streams are drained concurrently to avoid pipe deadlocks.

### Dependencies

`install` supports two ecosystems:

- `pip` (default/auto): creates `/workspace/.venv` on first use and installs into
  it. Python commands are rewritten to the venv interpreter when an agent asks
  to install packages and run a Python script in the same call.
- `npm`: installs into `/workspace/node_modules` with
  `--prefix /workspace`.

Install commands run with network access enabled for that operation only, even
when the sandbox policy disables network. `apt` is intentionally unsupported
because host system paths are read-only.

### Archives

`archive` writes `$root/<sandbox_id>.tar.gz`. Dependency and cache directories
(`.venv`, `node_modules`, `__pycache__`, etc.) are excluded by default; pass
`include_dependencies=true` to keep them. `restore` validates every member,
rejects path traversal, device files, FIFOs and links, and creates a new sandbox
owned by the caller.

## Agent permission

VIRA has three layers, all of which remain in force:

1. **Tool permission** — `ToolPermission(actions=["read", "write", "execute"])`
   and the runtime's `tool.use.<tool>.<agent>` check.
2. **Agent tool list** — `ChatAgent` accepts a `tools` config block:
   - `allow`: patterns available to this agent (`[]` = every registered tool);
   - `deny`: patterns always removed;
   - `pinned`: tools always offered to the tool loop even when the dynamic
     catalog would not rank them.

   `config.yaml` pins `sandbox` for the Chatbot, so code/build requests use a
   real environment instead of only discussing code.
3. **Human approval** — sandbox operations are destructive by classification,
   but the shipped configuration lists `sandbox` in
   `security.approvals.safe_tools` because the environment is isolated with its
   own filesystem, namespaces and resource limits. That lets a ChatAgent build
   and run projects without a prompt for every file or command. Remove it from
   `safe_tools` to restore per-call approval; `destructive_tools` and
   `security.approvals.tools.sandbox` can also force approval for selected
   operations. Shell and host-filesystem tools remain gated either way.

Long builds are bounded by `tool_timeouts` in the ChatAgent config
(`sandbox: 600` seconds by default in the shipped configuration) and by the
sandbox's own `timeout_seconds`.

## Operational notes

- Docker deployments must mount a writable volume at `sandbox.root` and allow
  unprivileged user namespaces (see the Bubblewrap troubleshooting hint).
- On Ubuntu 24.04+, AppArmor may require
  `kernel.apparmor_restrict_unprivileged_userns=0` or a bwrap profile.
- Deleted sandboxes remove their workspace and archive. Archives restored after
  restart are discovered from disk, not from a database.
- The host process never accepts a host path from the model; all file
  operations resolve inside the workspace and reject symlink escapes.
