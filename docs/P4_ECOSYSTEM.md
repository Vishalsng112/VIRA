# P4 — Ecosystem and scale

This phase makes VIRA extensible and deployable beyond a single household.

## Plugin and extension API

See [PLUGIN_SDK.md](PLUGIN_SDK.md). Highlights:

- manifest-based plugin discovery (`vira-plugin.json`)
- stable `Plugin` / `PluginContext` SDK
- declared permissions enforced before load
- tools, HTTP routes, sensors, agents, prompt specialists, events and jobs
- enable/disable/reload without restarting tools and agents
- plugin state and data directories
- compatibility and dependency checks
- failure isolation per plugin

## MCP tool marketplace and allow-lists

The server ships a curated catalogue of reference MCP servers (filesystem, git,
fetch, memory, sequential-thinking, SQLite, browser automation, time).

```text
GET  /api/v1/mcp/marketplace?q=browser
POST /api/v1/mcp/servers                  install from marketplace or manually
GET  /api/v1/mcp/servers
POST /api/v1/mcp/servers/{id}/connect
POST /api/v1/mcp/servers/{id}/disconnect
POST /api/v1/mcp/servers/{id}/enable
POST /api/v1/mcp/servers/{id}/disable
```

Installed servers are disabled by default after marketplace installation so an
administrator can review command, arguments and permissions before connecting.

Tool policies support `default`, `user`, `role` and `org` subjects with
precedence `user > org > role > default`. A policy can allow/deny a whole server
or specific tool names. Server-level `allowed_tools` and `denied_tools` apply
before user policies. Tools without any policy remain allowed, preserving
pre-P4 installations.

## Organizations and teams

```text
GET/POST        /api/v1/organizations
GET/PATCH/DELETE /api/v1/organizations/{id}
POST            /api/v1/organizations/{id}/members
PATCH/DELETE    /api/v1/organizations/{id}/members/{user_id}
```

Roles: `owner`, `admin`, `member`. Org-scoped resources use the
`X-Organization-ID` header:

- durable workflows (`/api/v1/workflows`)
- RAG documents and search (`/api/v1/rag`)
- object storage (`/api/v1/objects`)
- LLM usage summaries (`/api/v1/usage/summary`)

Personal resources keep `organization_id = NULL`, so existing behavior is
unchanged.

## Object storage

The `objects` API stores attachments, exports and large artifacts:

```text
POST   /api/v1/objects              multipart file upload
GET    /api/v1/objects              list personal or org objects
GET    /api/v1/objects/{id}         download
DELETE /api/v1/objects/{id}
```

Backends:

- `local` (default): `./data/objects`, SHA-256 addresses
- `s3`: AWS S3, MinIO, Cloudflare R2, Backblaze S3 and compatible services

```bash
VIRA_OBJECT_STORE=s3
VIRA_S3_BUCKET=vira
VIRA_S3_ACCESS_KEY=...
VIRA_S3_SECRET_KEY=...
VIRA_S3_REGION=us-east-1
VIRA_S3_ENDPOINT=https://s3.example.com
VIRA_S3_PREFIX=vira/
VIRA_S3_PATH_STYLE=1
```

The S3 backend uses SigV4 directly (no SDK dependency). Metadata lives in the
database; bytes live in the backend.

## Horizontal scaling, broker and replicas

The API process is stateless apart from the shared database. Run one or more
workers:

```bash
python -m vira.worker --interval 5
```

Durable jobs are claimed atomically, so multiple workers can run safely.

Broker selection:

```bash
VIRA_BROKER=database   # default, shared DB jobs table
VIRA_BROKER=redis      # requires the redis package; VIRA_REDIS_URL
VIRA_BROKER=nats       # requires the nats package; VIRA_NATS_URL
```

PostgreSQL read-replica routing for reporting helpers:

```bash
VIRA_DATABASE_URL=postgresql://...
VIRA_DATABASE_READ_URL=postgresql://replica...
```

SQLite remains the default for local installs.

## Update channel

Administrators publish releases to channels (`stable`, `beta`, `dev`) for
`server` and `client`:

```text
POST   /api/v1/updates/releases
GET    /api/v1/updates/releases
DELETE /api/v1/updates/releases/{id}
GET    /api/v1/updates/check?product=client&channel=stable&current_version=1.2.0
```

Checks use semantic version ordering (including prereleases). `min_version`
prevents offering an update to installations that must upgrade through an
intermediate release.

## Cost and quota dashboard

Every LLM call records provider, model, prompt/completion tokens, estimated
cost, latency, user, organization and agent in `llm_usage`. The same dashboard
also reports object-storage bytes/count and device-event volume for the
personal, organization or fleet scope.

```text
GET /api/v1/usage/summary?days=30        personal or org dashboard
GET /api/v1/admin/usage?days=30          fleet dashboard
GET /api/v1/admin/quotas
PUT /api/v1/admin/quotas                 user/org/global, day/month
```

Quotas can limit tokens, cost or both. A call that would exceed a quota is
rejected with HTTP 429 (`quota_exceeded`). Cost rates default to a built-in
table and can be overridden with `VIRA_LLM_RATES` JSON (`USD per 1M tokens`).
