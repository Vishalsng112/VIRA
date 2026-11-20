"""Example local MCP server for VIRA.

It exposes a tiny in-memory notes store over stdio. No network, no credentials
and no filesystem writes; it is meant as a copyable starting point for your own
MCP tools.

Run manually:

    python examples/mcp/notes_server.py

Register it in VIRA with the MCP marketplace/API, or add a config entry:

    {
      "name": "notes",
      "transport": "stdio",
      "command": "python",
      "args": ["examples/mcp/notes_server.py"],
      "permissions": ["read", "write"]
    }
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("notes")

_NOTES: dict[int, dict[str, str]] = {}
_NEXT_ID = 1


@server.tool()
async def notes_save(title: str, body: str = "") -> str:
    """Save a note and return its id.

    Args:
        title: Short title, 1-120 characters.
        body: Optional note body.
    """
    global _NEXT_ID
    title = " ".join(title.split())[:120]
    if not title:
        return "ERROR: title is required"
    note_id = _NEXT_ID
    _NEXT_ID += 1
    _NOTES[note_id] = {"title": title, "body": body[:4000]}
    return f"saved note {note_id}"


@server.tool()
async def notes_list(limit: int = 20) -> str:
    """List saved note ids and titles."""
    limit = max(1, min(int(limit or 20), 100))
    if not _NOTES:
        return "No notes saved."
    return "\n".join(
        f"{note_id}. {note['title']}"
        for note_id, note in list(_NOTES.items())[:limit]
    )


@server.tool()
async def notes_search(query: str) -> str:
    """Search note titles and bodies for a case-insensitive phrase."""
    needle = (query or "").lower().strip()
    if not needle:
        return "ERROR: query is required"
    matches = [
        f"{note_id}. {note['title']}"
        for note_id, note in _NOTES.items()
        if needle in note["title"].lower() or needle in note["body"].lower()
    ]
    return "\n".join(matches) if matches else "No matching notes."


@server.resource("notes://all")
def all_notes() -> str:
    """Return every note as plain text."""
    return "\n\n".join(
        f"# {note['title']}\n{note['body']}" for note in _NOTES.values()
    ) or "No notes saved."


if __name__ == "__main__":
    server.run()
