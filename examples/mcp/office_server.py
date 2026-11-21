"""Read-only local office connector for VIRA's Chief of Staff agent.

It reads three JSON files from ``VIRA_OFFICE_DIR`` (default ``data/office``):

    emails.json    [{"from","subject","body","received_at","link"}]
    calendar.json  {"events": [{"title","start","end","link"}]}
    tasks.json     {"tasks": [{"title","due","done","link"}]}

No network, credentials or writes. Copy it and replace the loaders with your
email/calendar/task provider when you are ready.

Run:

    VIRA_OFFICE_DIR=data/office python examples/mcp/office_server.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

server = FastMCP("office")


def _office_dir() -> Path:
    return Path(os.environ.get("VIRA_OFFICE_DIR", "data/office")).expanduser()


def _load(name: str) -> Any:
    path = _office_dir() / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": f"cannot read {path}: {exc}"}


def _rows(value: Any, key: str) -> List[Dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return [item for item in value[key] if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _line(item: Dict[str, Any], fields: List[str]) -> str:
    parts = [str(item.get(field) or "").strip() for field in fields]
    return " | ".join(part for part in parts if part)


@server.tool()
async def email_inbox(limit: int = 10) -> str:
    """List recent emails from the local office connector.

    Args:
        limit: Maximum number of messages to return (1-50).
    """
    value = _load("emails.json")
    if isinstance(value, dict) and value.get("error"):
        return f"ERROR: {value['error']}"
    if value is None:
        return ("No local email connector data found. Export messages to "
                f"{_office_dir() / 'emails.json'} or configure a real MCP email server.")
    rows = _rows(value, "emails")[:max(1, min(int(limit or 10), 50))]
    if not rows:
        return "No messages in the local email connector."
    return "\n\n".join(
        f"[{index}] {_line(item, ['from', 'received_at'])}\n"
        f"Subject: {item.get('subject') or '(no subject)'}\n"
        f"Link: {item.get('link') or '(no link)'}\n"
        f"{str(item.get('body') or '')[:1500]}"
        for index, item in enumerate(rows, start=1)
    )


@server.tool()
async def calendar_today(date: str = "") -> str:
    """List calendar events for a date (YYYY-MM-DD, default today, UTC)."""
    value = _load("calendar.json")
    if isinstance(value, dict) and value.get("error"):
        return f"ERROR: {value['error']}"
    if value is None:
        return ("No local calendar connector data found. Export events to "
                f"{_office_dir() / 'calendar.json'} or configure a real MCP calendar server.")
    target = date.strip() or datetime.now(timezone.utc).date().isoformat()
    events = []
    for item in _rows(value, "events"):
        start = str(item.get("start") or "")
        if not start.startswith(target):
            continue
        events.append(item)
    if not events:
        return f"No calendar events on {target} in the local connector."
    return "\n".join(
        f"- {item.get('start')}–{item.get('end') or '?'}: "
        f"{item.get('title') or '(untitled)'}"
        + (f" ({item['link']})" if item.get("link") else "")
        for item in sorted(events, key=lambda row: str(row.get("start") or ""))
    )


@server.tool()
async def tasks_due(days: int = 7) -> str:
    """List open tasks due within the next N days (0-90), including overdue."""
    value = _load("tasks.json")
    if isinstance(value, dict) and value.get("error"):
        return f"ERROR: {value['error']}"
    if value is None:
        return ("No local task connector data found. Export tasks to "
                f"{_office_dir() / 'tasks.json'} or configure a real MCP task server.")
    cutoff = datetime.now(timezone.utc) + timedelta(days=max(0, min(int(days or 7), 90)))
    rows = []
    for item in _rows(value, "tasks"):
        if item.get("done"):
            continue
        due_raw = str(item.get("due") or "").strip()
        due = None
        if due_raw:
            try:
                due = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
            except ValueError:
                due = None
        if due is None or due <= cutoff:
            rows.append(item)
    if not rows:
        return "No open tasks due in the selected window."
    return "\n".join(
        f"- {item.get('title') or '(untitled)'} (due {item.get('due') or 'unscheduled'})"
        + (f" ({item['link']})" if item.get("link") else "")
        for item in rows
    )


if __name__ == "__main__":
    server.run()
