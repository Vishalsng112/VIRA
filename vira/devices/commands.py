"""Server-to-device command queue (remote control channel)."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database

COMMAND_KINDS = {
    "capture.pause": "Pause all capture on the device",
    "capture.resume": "Resume capture on the device",
    "config.update": "Apply client configuration",
    "queue.flush": "Flush the local outbox now",
    "queue.clear": "Delete the local outbox",
    "update.check": "Check for a client update",
    "export.request": "Produce a local export",
    "consent.update": "Refresh collector consent state",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(device_id: str, kind: str, payload: Optional[Dict[str, Any]] = None,
           user_id: Optional[int] = None, ttl_hours: int = 24) -> Dict[str, Any]:
    if kind not in COMMAND_KINDS:
        raise ValueError(f"kind must be one of {sorted(COMMAND_KINDS)}")
    command_id = str(uuid.uuid4())
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=max(1, ttl_hours))).isoformat()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO device_commands (id, device_id, kind, payload, status, "
            "created_by_user_id, created_at, expires_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (command_id, device_id, kind, json.dumps(payload or {}, default=str),
             user_id, now, expires),
        )
    return {"id": command_id, "device_id": device_id, "kind": kind,
            "payload": payload or {}, "status": "pending", "expires_at": expires}


def list_for_device(device_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM device_commands WHERE device_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (device_id, min(max(limit, 1), 200)),
        ).fetchall()
    return [_row(row) for row in rows]


def claim_pending(device_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            "UPDATE device_commands SET status = 'expired' "
            "WHERE device_id = ? AND status = 'pending' AND expires_at <= ?",
            (device_id, now),
        )
        rows = conn.execute(
            "SELECT * FROM device_commands WHERE device_id = ? AND status = 'pending' "
            "ORDER BY created_at LIMIT ?",
            (device_id, min(max(limit, 1), 100)),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE device_commands SET status = 'delivered', delivered_at = ? WHERE id = ?",
                (now, row["id"]),
            )
    return [_row(row) for row in rows]


def complete(device_id: str, command_id: str, status: str = "completed",
             result: Any = None) -> bool:
    if status not in ("completed", "failed"):
        raise ValueError("status must be completed or failed")
    with database.transaction() as conn:
        changed = conn.execute(
            "UPDATE device_commands SET status = ?, completed_at = ?, result = ? "
            "WHERE id = ? AND device_id = ? AND status IN ('pending','delivered')",
            (status, _now(), json.dumps(result, default=str), command_id, device_id),
        ).rowcount
    return bool(changed)


def purge_expired() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with database.transaction() as conn:
        cur = conn.execute(
            "DELETE FROM device_commands WHERE status IN ('completed','failed','expired') "
            "AND created_at < ?",
            (cutoff,),
        )
        return cur.rowcount


def _row(row) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["payload"] = json.loads(item.get("payload") or "{}")
    except ValueError:
        item["payload"] = {}
    if item.get("result"):
        try:
            item["result"] = json.loads(item["result"])
        except ValueError:
            pass
    return item
