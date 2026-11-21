# Workspaces, sandboxes and host tools

The durable unit is a **workspace**, not an agent. A workspace is a directory on
the host that users can open, back up or version. Sandboxes are execution
contexts attached to a workspace.

```
workspace (shared directory, user-visible)
├── agent A sandbox (isolated namespace) ── same files
├── agent B sandbox (isolated namespace) ── same files
└── user opens the directory directly
```

## Resolution

`vira/workspace/service.py`:

* plain name `my-project` → `workspace.root/my-project`
* absolute path or `~/...` → used as-is when `workspace.allow_user_paths: true`
* no workspace supplied → `<root>/user-<id>`, shared by every agent for that user

```yaml
workspace:
  root: "~/VIRA/workspaces"
  allow_user_paths: true
  default_execution_mode: bubblewrap   # bubblewrap | host
```

The user can select a workspace per chat turn:

```json
{ "message": "work on this", "workspace": "/home/me/code/project" }
```

The API puts it in the event, and it is injected into every `sandbox` tool call
for that run, so the model does not have to repeat it. A workspace id is also
accepted.

The API exposes:

* `GET /api/v1/workspaces`
* `POST /api/v1/workspaces` `{name, path?, execution_mode?}`
* `PATCH /api/v1/workspaces/{id}` `{execution_mode}`

## Sharing across agents

`sandbox` resolves the workspace and creates one sandbox per agent/workspace
pair. Each sandbox has its own process namespace and artifacts directory, but all
of them bind the same workspace directory:

* two agents see the same files;
* different projects use different workspace names;
* deleting one sandbox never deletes a shared workspace.

## Host tools

There are two ways to expose host-installed tools (Node, Python, compilers, SDKs,
etc.).

### 1. Host execution mode

```yaml
workspace:
  default_execution_mode: host
```

or per workspace:

```bash
curl -X PATCH /api/v1/workspaces/<id> -d '{"execution_mode":"host"}'
```

Commands run directly in the workspace with the host `PATH`. `/workspace` and
`/artifacts` in commands are translated to the real directories. The sandbox
still owns file operations, quotas, timeouts and job tracking. Host mode is an
explicit admin / workspace choice; it is equivalent to granting shell access as
the VIRA user and cannot be selected by a model (the sandbox tool strips it from
policy input).

### 2. Read-only mounts in bubblewrap

```yaml
sandbox:
  readonly_mounts: ["/opt/toolchain", "/snap"]
  extra_path: "/opt/toolchain/bin:/snap/bin"
workspace:
  default_execution_mode: bubblewrap
```

This keeps namespace isolation while making a host toolchain visible.

## Notes

* `workspace.allow_user_paths: false` restricts users to names under
  `workspace.root`.
* System directories (`/etc`, `/usr`, `/`, …) are rejected as workspace paths.
* Workspaces are indexed in the `workspaces` table (migration 16); the
  filesystem is always the source of truth. Tools remain usable if the table is
  absent.
* Host mode does not enforce network isolation.
