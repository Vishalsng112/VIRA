"""Human approval gates for destructive tool calls.

A call is *classified* before execution. When it is destructive, the executor
creates a short-lived approval request and returns ``APPROVAL_REQUIRED`` to the
agent instead of running the tool. An administrator (or the owning user) can
approve or deny it through ``/api/v1/approvals``. The next identical call from
the same user consumes the approved request exactly once.

Approvals are single-use, expire, and never contain raw secrets: arguments are
redacted with :mod:`vira.security.redaction` before storage.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database
from vira.security.redaction import redact

APPROVAL_REQUIRED_PREFIX = "APPROVAL_REQUIRED"
DEFAULT_TTL_MINUTES = 30

_WORKSPACE_WRITE_TOOLS = {"workspace.write_file", "workspace.make_directory"}
_WORKSPACE_SAFE = {
    "workspace.read_file", "workspace.list_directory", "workspace.search_files",
}
_SANDBOX_SAFE = {
    "read", "list", "stat", "search", "jobs", "job", "job_logs", "usage",
    "sandboxes", "info", "read_file", "list_files", "cat", "ls",
}
_ALWAYS_DESTRUCTIVE = {"runtime.run"}
_MCP_SAFE_PREFIXES = ("database.", "vira.", "web.")
_MCP_SAFE_TOOLS = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _matches(name: str, patterns: List[str]) -> bool:
    for pattern in patterns:
        pattern = str(pattern).strip()
        if not pattern:
            continue
        if name == pattern or name.startswith(pattern + ".") or name.startswith(pattern + "*"):
            return True
    return False


def approval_reason(tool_name: str, action: str, arguments: Dict[str, Any],
                    config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Return a human-readable reason when a call needs approval, else None."""
    config = config or {}
    if config.get("enabled", True) is False:
        return None

    qualified = str(tool_name)
    short = qualified.split(".")[-1].lower()
    operation = str((arguments or {}).get("operation", "")).strip().lower()

    forced = config.get("destructive_tools") or []
    if _matches(qualified, forced) or _matches(short, forced):
        return f"'{short}' is configured as a destructive tool"
    safe = config.get("safe_tools") or []
    if _matches(qualified, safe) or _matches(short, safe):
        return None

    overrides = config.get("tools") or {}
    for key, operations in overrides.items():
        if _matches(qualified, [key]) or _matches(short, [key]):
            if operations in ("*", "all", True):
                return f"'{short}' requires approval for every operation (policy)"
            if operation in {str(item).lower() for item in (operations or [])}:
                return f"'{short}' operation '{operation}' requires approval (policy)"
            return None

    if qualified in _WORKSPACE_WRITE_TOOLS:
        return f"'{short}' can modify the workspace"
    if qualified in _WORKSPACE_SAFE:
        return None
    if qualified == "workspace.sandbox":
        if operation not in _SANDBOX_SAFE:
            return f"Sandbox '{operation or 'create'}' can write files or run code"
        return None
    if qualified in _ALWAYS_DESTRUCTIVE:
        return "Runtime commands can affect the host"
    if qualified.startswith(_MCP_SAFE_PREFIXES) or short in _MCP_SAFE_TOOLS:
        return None
    # Unknown MCP/plugin tools are only gated when explicitly configured.
    if config.get("unknown_tools", False):
        return f"'{short}' is not on the approval safe-list"
    return None


def fingerprint(tool_name: str, action: str, arguments: Dict[str, Any]) -> str:
    payload = json.dumps(
        {"tool": tool_name, "action": action, "arguments": arguments or {}},
        sort_keys=True, default=str, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    item = dict(row)
    try:
        item["arguments"] = json.loads(item.get("arguments") or "{}")
    except (TypeError, ValueError):
        item["arguments"] = {}
    return item


def expire_stale() -> int:
    with database.transaction() as conn:
        cursor = conn.execute(
            "UPDATE agent_approvals SET status = 'expired', decided_at = ? "
            "WHERE status = 'pending' AND expires_at < ?",
            (_iso(_now()), _iso(_now())),
        )
        return int(cursor.rowcount or 0)


def request_approval(
    tool_name: str,
    action: str,
    arguments: Dict[str, Any],
    *,
    user_id: Optional[int],
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    reason: str = "",
    ttl_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    expire_stale()
    approval_id = str(uuid.uuid4())
    created = _now()
    expires = created + timedelta(minutes=max(1, int(ttl_minutes or DEFAULT_TTL_MINUTES)))
    safe_arguments = redact(arguments or {})
    digest = fingerprint(tool_name, action, arguments or {})
    with database.transaction() as conn:
        # Repeated identical calls reuse the pending request instead of creating
        # an approval-queue spam loop.
        existing = conn.execute(
            "SELECT * FROM agent_approvals WHERE "
            "(user_id = ? OR (user_id IS NULL AND ? IS NULL)) "
            "AND tool_name = ? AND fingerprint = ? AND status = 'pending' "
            "AND expires_at >= ? ORDER BY created_at DESC LIMIT 1",
            (user_id, user_id, tool_name, digest, _iso(created)),
        ).fetchone()
        if existing is not None:
            return _row(existing)
        conn.execute(
            "INSERT INTO agent_approvals "
            "(id, run_id, user_id, agent_id, tool_name, action, fingerprint, arguments, "
            " reason, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (approval_id, run_id, user_id, agent_id, tool_name, action, digest,
             json.dumps(safe_arguments, default=str, ensure_ascii=False),
             str(reason or "")[:500], _iso(created), _iso(expires)),
        )
    return get_request(approval_id) or {}


def get_request(approval_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_approvals WHERE id = ?", (approval_id,)
        ).fetchone()
    return _row(row)


def list_requests(user_id: Optional[int] = None, status: Optional[str] = None,
                  limit: int = 100, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    clauses, values = [], []
    if user_id is not None:
        clauses.append("user_id = ?")
        values.append(user_id)
    if status:
        clauses.append("status = ?")
        values.append(status)
    if run_id:
        clauses.append("run_id = ?")
        values.append(run_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(min(max(int(limit), 1), 500))
    with database.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_approvals {where} ORDER BY created_at DESC LIMIT ?",
            values,
        ).fetchall()
    return [_row(row) for row in rows]


def decide(approval_id: str, approved: bool, decided_by: Optional[int],
           note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    now = _iso(_now())
    with database.transaction() as conn:
        cursor = conn.execute(
            "UPDATE agent_approvals SET status = ?, decided_at = ?, "
            "decided_by_user_id = ?, decision_note = ? "
            "WHERE id = ? AND status = 'pending' AND expires_at >= ?",
            ("approved" if approved else "denied", now, decided_by,
             (note or "")[:500], approval_id, now),
        )
        if cursor.rowcount != 1:
            return None
    return get_request(approval_id)


def find_approved(user_id: Optional[int], tool_name: str, action: str,
                  arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Consume one matching approved request, if it exists and is unexpired."""
    if user_id is None:
        return None
    now = _iso(_now())
    digest = fingerprint(tool_name, action, arguments or {})
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM agent_approvals WHERE user_id = ? AND tool_name = ? "
            "AND fingerprint = ? AND status = 'approved' AND consumed_at IS NULL "
            "AND expires_at >= ? ORDER BY decided_at LIMIT 1",
            (user_id, tool_name, digest, now),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE agent_approvals SET consumed_at = ? WHERE id = ?",
            (now, row["id"]),
        )
    return _row(row)
