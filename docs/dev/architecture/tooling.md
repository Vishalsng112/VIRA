# Tooling and domain MCP servers

VIRA's tooling layer is deliberately split into:

- a **framework** for contracts, discovery, policies and execution;
- **domain MCP servers** for isolation, credentials and lifecycle;
- a **catalog** that gives the model one small, relevant tool shortlist.

MCP is an integration boundary, not a code-organization mechanism. VIRA-owned
tools stay in-process; external, plugin, privileged or separately-versioned
tools can run as MCP servers.

The legacy `vira.tools` package has been removed. All agents, plugins, generated
tools, local domain packs and MCP servers use this contract and qualified names.

## Pydantic or JSON?

**Use Pydantic as the source of truth.** JSON is the wire format, not the
programming model.

```text
Pydantic input model  -> JSON Schema  -> LLM/MCP input validation
Pydantic output model -> JSON Schema  -> stable structured output
```

Why:

- one definition for validation, docs and schema;
- generated JSON Schema stays in sync;
- typed outputs make prompt/tool contracts testable;
- invalid arguments produce structured failures, not exceptions;
- MCP clients still receive plain JSON Schema and JSON results.

Every tool has:

```python
input_model: type[BaseModel]
output_model: type[BaseModel]
```

The MCP `outputSchema` is the generic envelope for that output:

```json
{
  "ok": true,
  "data": { "...": "tool-specific output" },
  "error": null,
  "truncated": false,
  "next_cursor": null
}
```

## Foundation

```text
vira/tooling/
  contract.py      BaseTool, Pydantic models, ToolEnvelope, ToolContext
  catalog.py       CatalogEntry, ToolCatalog, retrieval scoring
  policy.py        per-agent allow/deny/pinned globs
  registry.py      qualified tool registry
  toolbox.py       per-agent view, tool_search/tool_describe
  manifest.py      domain server manifest
  mcp.py           low-level MCP stdio adapter
  servers/         domain tool packs
```

### Abstract tool

A concrete tool extends `BaseTool`, declares metadata, and implements `run`:

```python
class WebSearchTool(BaseTool):
    namespace = "web"
    name = "search"
    title = "Search the web"
    description = "Search the public web."
    when_to_use = "Current facts, news, prices, people."
    when_not_to_use = "Private VIRA data."
    category = "web"
    tags = ("web", "search", "news")
    input_model = WebSearchInput
    output_model = TextOutput

    async def run(self, params, context):
        ...
```

The framework supplies:

- qualified name (`web.search`);
- JSON Schemas;
- input validation;
- timeouts;
- typed error envelope;
- MCP tool descriptor;
- audit-friendly output.

`ToolContext` carries `user_id`, `agent_id`, organization, run and workspace
identity explicitly. Tools never read ambient globals.

## Domain topology

| Server | Namespace | Tools |
|---|---|---|
| `web` | `web.` | `search`, `browse`, `research` |
| `runtime` | `runtime.` | `run` |
| `workspace` | `workspace.` | `read_file`, `write_file`, `list_directory`, `search_files`, `make_directory`, `sandbox` |
| `database` | `database.` | `tables`, `schema`, `examples`, `account_summary`, `query` |
| `vira` | `vira.` | `context`, `insights`, `chat_statistics`, `knowledge_search` |

Future domains follow the same rule:

- `automation` — schedules/workflows, long-running side effects;
- `admin` — fleet, users, config, backups (never general agents);
- vendor integrations — separate credentials and lifecycle.

### Server command

```bash
python -m vira.mcp.servers.web.server
python -m vira.mcp.servers.runtime.server
python -m vira.mcp.servers.workspace.server
python -m vira.mcp.servers.database.server
python -m vira.mcp.servers.vira_core.server
```

Each server exposes only its domain tools and its own instructions.

## Tool naming

Use `namespace.verb_noun` or `namespace.verb`:

```text
web.search
web.browse
runtime.run
workspace.read_file
database.query
vira.insights
```

Rules:

- one intent per tool;
- no `do_everything`;
- no generic `run`, `query` outside a namespace;
- read and write are separate tools;
- deprecated names are not silently aliased.

## Discovery

The model does not need to know which server owns a tool. It sees a shortlist
from `ToolCatalog`:

- `tool_search` expands the candidate set;
- `tool_describe` returns the full schema for one candidate;
- pinned tools are always present;
- per-agent policies filter before the model sees anything.

Score inputs:

- tool name and title;
- description and `when_to_use`;
- tags, aliases and app names;
- category;
- future: embeddings, usage success, latency and cost.

Prompt budget:

- 8–15 tools per step;
- one-line summaries for the shortlist;
- full schemas only for likely calls;
- hard description character budget.

## Policies

`ToolPolicy` supports:

```python
ToolPolicy(
    allow=["web.*", "workspace.*", "vira.context"],
    deny=["workspace.write_file"],
    pinned=["vira.context"],
)
```

Policies are applied at discovery and execution. MCP server allow-lists remain
an additional layer.

## Adding a domain

1. Add `vira/tooling/servers/<domain>/tools.py`.
2. Add a `ServerManifest`.
3. Export `TOOLS` and `MANIFEST`.
4. Add `vira/mcp/servers/<domain>/server.py`.
5. Register the domain in `vira/tooling/servers/__init__.py`.
6. Add contract tests and a real MCP handshake test.

Do not add a new server merely because a tool is new. Add one when security,
credentials, runtime, lifecycle or ownership differs.
