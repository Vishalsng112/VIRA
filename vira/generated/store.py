"""Persistence for generated tools and agents (draft → review → enable)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database

KINDS = ("tool", "agent")
STATUSES = ("draft", "approved", "rejected", "enabled", "disabled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    item = dict(row)
    try:
        item["spec"] = json.loads(item.get("spec") or "{}")
    except (TypeError, ValueError):
        item["spec"] = {}
    return item


def create(*, kind: str, name: str, version: str, description: str,
           spec: Dict[str, Any], checksum: str,
           created_by_user_id: Optional[int]) -> Dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO generated_artifacts "
            "(id, kind, name, version, description, spec, status, checksum, "
            " created_by_user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)",
            (artifact_id, kind, name, version, description,
             json.dumps(spec, default=str, ensure_ascii=False), checksum,
             created_by_user_id, now, now),
        )
    return get(artifact_id) or {}


def get(artifact_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM generated_artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    return _row(row)


def find(kind: str, name: str, version: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM generated_artifacts WHERE kind = ? AND name = ? AND version = ?",
            (kind, name, version),
        ).fetchone()
    return _row(row)


def list_artifacts(kind: Optional[str] = None, status: Optional[str] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
    clauses, values = [], []
    if kind:
        clauses.append("kind = ?")
        values.append(kind)
    if status:
        clauses.append("status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(min(max(int(limit), 1), 500))
    with database.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM generated_artifacts {where} ORDER BY updated_at DESC LIMIT ?",
            values,
        ).fetchall()
    return [_row(row) for row in rows]


def set_status(artifact_id: str, status: str, *, approved_by_user_id: Optional[int] = None,
               rejection_reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if status not in STATUSES:
        raise ValueError("invalid status")
    now = _now()
    fields = ["status = ?", "updated_at = ?"]
    values: List[Any] = [status, now]
    if status == "approved":
        fields += ["approved_by_user_id = ?", "approved_at = ?"]
        values += [approved_by_user_id, now]
    if status == "enabled":
        fields += ["enabled_at = ?"]
        values += [now]
    if status == "rejected":
        fields += ["rejection_reason = ?"]
        values += [(rejection_reason or "")[:1000]]
    values.append(artifact_id)
    with database.transaction() as conn:
        cursor = conn.execute(
            f"UPDATE generated_artifacts SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        if cursor.rowcount != 1:
            return None
    return get(artifact_id)


def delete(artifact_id: str) -> bool:
    with database.transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM generated_artifacts WHERE id = ?", (artifact_id,)
        )
        return cursor.rowcount == 1
