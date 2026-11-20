"""Curated MCP marketplace entries.

These are reference servers from the Model Context Protocol ecosystem.  An
entry is only metadata: installing it creates a disabled-by-default record that
an administrator can review before connecting.
"""
from typing import Any, Dict, List

MARKETPLACE: List[Dict[str, Any]] = [
    {
        "id": "filesystem",
        "name": "filesystem",
        "display_name": "Filesystem",
        "description": "Read and write files inside an explicitly allowed workspace directory.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE}"],
        "permissions": ["read", "write"],
        "categories": ["workspace", "files"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "git",
        "name": "git",
        "display_name": "Git",
        "description": "Inspect repositories, diffs, commits and branches.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-git"],
        "permissions": ["read"],
        "categories": ["developer", "runtime"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "fetch",
        "name": "fetch",
        "display_name": "Web Fetch",
        "description": "Fetch a URL and convert the page to readable markdown.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "permissions": ["read"],
        "categories": ["web", "research"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "memory",
        "name": "memory",
        "display_name": "Knowledge Graph Memory",
        "description": "Persistent entities and relations for long-running agents.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "permissions": ["read", "write"],
        "categories": ["memory", "agent"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "sequential-thinking",
        "name": "sequential-thinking",
        "display_name": "Sequential Thinking",
        "description": "Structured step-by-step reasoning scratchpad.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "permissions": ["read"],
        "categories": ["agent", "reasoning"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "sqlite",
        "name": "sqlite",
        "display_name": "SQLite",
        "description": "Query and inspect a local SQLite database.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "${DATABASE}"],
        "permissions": ["read"],
        "categories": ["database", "developer"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "puppeteer",
        "name": "puppeteer",
        "display_name": "Browser Automation",
        "description": "Control a headless browser for screenshots and page interaction.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "permissions": ["read", "execute"],
        "categories": ["web", "automation"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "time",
        "name": "time",
        "display_name": "Time",
        "description": "Current time and timezone conversion.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "permissions": ["read"],
        "categories": ["utility"],
        "version": "1.0.0",
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
]


def search(query: str = "", category: str = "") -> List[Dict[str, Any]]:
    query = (query or "").strip().lower()
    category = (category or "").strip().lower()
    results = []
    for entry in MARKETPLACE:
        if category and category not in [c.lower() for c in entry["categories"]]:
            continue
        haystack = " ".join([
            entry["id"], entry["name"], entry["display_name"], entry["description"],
            " ".join(entry["categories"]),
        ]).lower()
        if query and not all(part in haystack for part in query.split()):
            continue
        results.append(dict(entry))
    return results


def get(entry_id: str):
    return next((dict(item) for item in MARKETPLACE if item["id"] == entry_id), None)
