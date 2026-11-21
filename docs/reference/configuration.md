# Configuration reference

VIRA reads `config.yaml` from the repository root (override with `VIRA_CONFIG`).
The dashboard can edit it and reload the runtime.

The canonical file is
[`config.yaml`](https://github.com/Vishalsng112/VIRA/blob/main/config.yaml).
The table below is a map of the top-level sections, not a replacement for the
file's inline comments.

| Section | Controls |
|---|---|
| `kernel` | Name, checkpoint, log, plugin, module and sensor directories |
| `plugins` | Plugin search paths, write-tool permission and plugin data directory |
| `auth` | Session secret, cookie name, session lifetime, HTTPS-only and database URL |
| `devices` | Device credential lifetime, local device backend and event policy |
| `event_bus` | Event queue size |
| `scheduler` | Tick interval |
| `sandbox` | Backend, workspace root, network, timeouts, CPU/memory limits |
| `tools` | Tool workspace root |
| `security` | Default tool permissions |
| `rate_limits` | Enablement and per-route limits |
| `jobs` | Worker interval, rollup and retention windows, backup count |
| `agent_scheduler` | Proactive schedule tick, concurrency, locks, timeout and quiet-hours defaults |
| `notifications` | In-app notification delivery and optional webhook provider |
| `metrics` | Enablement and retention |
| `sensors` | Per-sensor enablement and polling settings |
| `llm` | Default model and provider/model catalogue |
| `agents` | Enabled agents and their settings |
| `mcp_server` | MCP server command and permissions |
| `database_mcp` | Built-in read-only database MCP server |
| `agent_policy` | Persisted-agent loading and allowed modules |

## Environment overrides

Docker deployments use `.env` for the values that most often change:

| Variable | Purpose | Default |
|---|---|---|
| `VIRA_BIND_ADDRESS` | Interface the server binds to | `127.0.0.1` |
| `VIRA_PORT` | Host port | `8000` |
| `VIRA_OLLAMA_MODEL` | Model the bundled Ollama pulls | `qwen3.5:9b` |
| `VIRA_CONFIG` | Path to an alternate `config.yaml` | `config.yaml` |
| `VIRA_TRUSTED_PROXIES` | Proxy IPs trusted for forwarded headers | `127.0.0.1` |

See [`.env.example`](https://github.com/Vishalsng112/VIRA/blob/main/.env.example)
for the full set.

## Proactive agents and notifications

```yaml
agent_scheduler:
  enabled: true
  tick_seconds: 20          # how often due schedules are claimed
  max_concurrent: 2         # simultaneous scheduled agent runs
  max_runs_per_tick: 10
  lock_seconds: 300         # crash-safe claim expiry
  run_timeout_seconds: 240
  notify_on_error: true

notifications:
  webhook_url: ""           # optional external delivery
  webhook_timeout_seconds: 10
  max_attempts: 3
  push_provider: "relay"    # relay | fcm
  push_relay_url: ""        # gateway mode
  push_relay_token: ""
  push_timeout_seconds: 10
  fcm_service_account_file: ""   # FCM mode
  fcm_project_id: ""
```

Schedules are created per user through `/api/v1/agent-schedules`. Each schedule
can carry a structured `input` object (for example
`{"mode": "evening"}`) that is merged into the agent's `TaskRequest.input`.
See [Proactive agents](../user/proactive-agents.md) for the workflow.

## Security-critical keys

!!! danger "Before exposing VIRA beyond localhost"
    - Set `auth.secret_key` to a long random value.
    - Set `auth.https_only: true` and terminate TLS at a reverse proxy.
    - Review `tools` and `security.default_permissions`.
    - Keep port `8000` behind the reverse proxy.

The Bubblewrap sandbox is for development workloads, not hostile code. Use a
container or VM for a stronger boundary. See
[Sandbox execution environments](../dev/designs/sandbox-execution.md) for the
full lifecycle, operations and policy reference.

### Sandbox keys

| Key | Default | Purpose |
|---|---|---|
| `backend` | `bubblewrap` | Execution backend (Bubblewrap is the supported backend) |
| `root` | `/AgentWorkspace` | Writable root for sandbox workspaces and archives |
| `bwrap_binary` | `bwrap` | Override the Bubblewrap executable path |
| `network_enabled` | `false` | Default outbound network access |
| `timeout_seconds` | `900` | Maximum wall clock per command |
| `max_processes` | `128` | Process/thread headroom |
| `cpu_seconds` | `600` | RLIMIT_CPU |
| `memory_mb` | `2048` | RLIMIT_AS |
| `allow_package_install` | `true` | Enable `pip`/`npm` installs |
| `allow_shell` | `true` | Allow shell command strings (`bash -lc`) |
| `workspace_quota_mb` | `2048` | Soft quota for project files |
| `max_output_bytes` | `200000` | Per-stream output cap |

Individual sandboxes may override these values at creation with the
`policy` argument of the `sandbox` tool. `security.approvals` still gates
destructive operations.

## Related

- [Docker and deployment](../user/install/docker.md)
- [Framework config reference](../dev/architecture/framework.md#config-reference)
- [LLM providers](../dev/architecture/framework.md#llm-providers)
