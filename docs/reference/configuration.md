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
| `VIRA_OLLAMA_MODEL` | Model the bundled Ollama pulls | `ornith-1.5:9b` |
| `VIRA_CONFIG` | Path to an alternate `config.yaml` | `config.yaml` |
| `VIRA_TRUSTED_PROXIES` | Proxy IPs trusted for forwarded headers | `127.0.0.1` |

See [`.env.example`](https://github.com/Vishalsng112/VIRA/blob/main/.env.example)
for the full set.

## Security-critical keys

!!! danger "Before exposing VIRA beyond localhost"
    - Set `auth.secret_key` to a long random value.
    - Set `auth.https_only: true` and terminate TLS at a reverse proxy.
    - Review `tools` and `security.default_permissions`.
    - Keep port `8000` behind the reverse proxy.

The Bubblewrap sandbox is for development workloads, not hostile code. Use a
container or VM for a stronger boundary.

## Related

- [Docker and deployment](../user/install/docker.md)
- [Framework config reference](../dev/architecture/framework.md#config-reference)
- [LLM providers](../dev/architecture/framework.md#llm-providers)
