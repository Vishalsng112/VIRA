"""Persistence for workspace records.

Primary storage is the ``workspaces`` table.  The workspace layer must still
work for tools/tests that use a database without the migration applied, so every
operation falls back to an in-process registry.  The filesystem directory itself
is always the source of truth; this table is an index for listing and lookups.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["metadata"] = json.loads(item.get("metadata") or "{}")
    except ValueError:
        item["metadata"] = {}
    return item


_memory: Dict[str, Dict[str, Any]] = {}
_db_available = True


def _fallback() -> bool:
    global _db_available
    if not _db_available:
        return True
    return False


def _drop_db() -> None:
    global _db_available
    _db_available = False


def _mem_find(**filters: Any) -> Optional[Dict[str, Any]]:
    for item in _memory.values():
        if all(item.get(key) == value for key, value in filters.items()):
            return dict(item)
    return None


def upsert(*, name: str, path: str, owner_user_id: Optional[int],
           organization_id: Optional[str] = None,
           execution_mode: str = "bubblewrap",
           metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    now = _now()
    payload = {
        "name": name, "path": path, "owner_user_id": owner_user_id,
        "organization_id": organization_id, "execution_mode": execution_mode,
        "metadata": dict(metadata or {}), "updated_at": now,
    }
    if not _fallback():
        try:
            with database.transaction() as conn:
                existing = conn.execute(
                    "SELECT * FROM workspaces WHERE owner_user_id IS ? AND name = ?",
                    (owner_user_id, name),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE workspaces SET path = ?, execution_mode = ?, "
                        "metadata = ?, organization_id = ?, updated_at = ? WHERE id = ?",
                        (path, execution_mode,
                         json.dumps(metadata or {}, default=str),
                         organization_id, now, existing["id"]),
                    )
                    workspace_id = existing["id"]
                else:
                    workspace_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO workspaces (id, name, path, owner_user_id, "
                        "organization_id, execution_mode, metadata, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (workspace_id, name, path, owner_user_id, organization_id,
                         execution_mode, json.dumps(metadata or {}, default=str),
                         now, now),
                    )
                row = conn.execute("SELECT * FROM workspaces WHERE id = ?",
                                   (workspace_id,)).fetchone()
            return _row(row)
        except Exception:
            _drop_db()
    existing = _mem_find(name=name, owner_user_id=owner_user_id)
    if existing:
        existing.update(payload)
        _memory[existing["id"]] = existing
        return dict(existing)
    record = {"id": str(uuid.uuid4()), "created_at": now, **payload}
    _memory[record["id"]] = record
    return dict(record)


def get(workspace_id: str) -> Optional[Dict[str, Any]]:
    if not _fallback():
        try:
            with database.get_connection() as conn:
                row = conn.execute("SELECT * FROM workspaces WHERE id = ?",
                                   (workspace_id,)).fetchone()
            return _row(row) if row else None
        except Exception:
            _drop_db()
    item = _memory.get(workspace_id)
    return dict(item) if item else None


def find_by_path(path: str) -> Optional[Dict[str, Any]]:
    if not _fallback():
        try:
            with database.get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM workspaces WHERE path = ? "
                    "ORDER BY updated_at DESC LIMIT 1", (path,)).fetchone()
            return _row(row) if row else None
        except Exception:
            _drop_db()
    return _mem_find(path=path)


def find_by_name(name: str, owner_user_id: Optional[int]) -> Optional[Dict[str, Any]]:
    if not _fallback():
        try:
            with database.get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM workspaces WHERE name = ? AND owner_user_id IS ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (name, owner_user_id)).fetchone()
            return _row(row) if row else None
        except Exception:
            _drop_db()
    return _mem_find(name=name, owner_user_id=owner_user_id)


def list_for_user(user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    if not _fallback():
        try:
            with database.get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM workspaces WHERE owner_user_id = ? "
                    "ORDER BY updated_at DESC LIMIT ?", (user_id, limit)).fetchall()
            return [_row(row) for row in rows]
        except Exception:
            _drop_db()
    items = [dict(item) for item in _memory.values()
             if item.get("owner_user_id") == user_id]
    items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return items[:limit]


def delete(workspace_id: str, owner_user_id: Optional[int] = None) -> bool:
    if not _fallback():
        try:
            with database.transaction() as conn:
                if owner_user_id is None:
                    cur = conn.execute("DELETE FROM workspaces WHERE id = ?",
                                       (workspace_id,))
                else:
                    cur = conn.execute(
                        "DELETE FROM workspaces WHERE id = ? AND owner_user_id = ?",
                        (workspace_id, owner_user_id))
            return bool(cur.rowcount)
        except Exception:
            _drop_db()
    item = _memory.get(workspace_id)
    if item is None or (owner_user_id is not None
                        and item.get("owner_user_id") != owner_user_id):
        return False
    _memory.pop(workspace_id, None)
    return True
