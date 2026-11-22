# Domain MCP servers

Each directory is one deployable stdio MCP server:

```bash
python -m vira.mcp.servers.web.server
python -m vira.mcp.servers.runtime.server
python -m vira.mcp.servers.workspace.server
python -m vira.mcp.servers.database.server
python -m vira.mcp.servers.vira_core.server
```

Tools are defined once under `vira/tooling/servers/<domain>/tools.py` using the
Pydantic-first `BaseTool` contract. The server entrypoint only selects the
manifest and tool pack.

See `docs/dev/architecture/tooling.md`.
