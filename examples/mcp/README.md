# Example MCP server

`notes_server.py` is a complete, dependency-light MCP server built with the
official Python MCP SDK. It exposes:

- `notes_save(title, body)`
- `notes_list(limit)`
- `notes_search(query)`
- resource `notes://all`

It stores notes in memory only and performs no network or filesystem I/O, so it
is safe to copy and extend.

## Run it

```bash
python examples/mcp/notes_server.py
```

## Connect it to VIRA

Install it through the MCP marketplace/API or add a server record:

```json
{
  "name": "notes",
  "transport": "stdio",
  "command": "python",
  "args": ["examples/mcp/notes_server.py"],
  "permissions": ["read", "write"]
}
```

Then enable it and restrict tools with MCP policies in the dashboard or
`/api/v1/mcp/servers/{server_id}/policies`.

The example test performs a real stdio handshake, lists tools and calls one:

```bash
python3 -m unittest vira.tests.test_examples -v
```
