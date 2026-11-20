"""In-app notification queue and device push-token registration."""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(user_id: int, title: str, body: str = "", kind: str = "system",
           device_id: Optional[str] = None, data: Optional[dict] = None) -> Dict[str, Any]:
    notification_id = str(uuid.uuid4())
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO user_notifications "
            "(id, user_id, device_id, kind, title, body, data, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (notification_id, user_id, device_id, kind, title, body,
             json.dumps(data or {}, default=str), _now()),
        )
    return {"id": notification_id, "title": title, "body": body, "kind": kind,
            "status": "pending"}


def list_for_user(user_id: int, limit: int = 100, unread_only: bool = False) -> List[Dict[str, Any]]:
    clause = "AND read_at IS NULL" if unread_only else ""
    with database.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM user_notifications WHERE user_id = ? {clause} "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, min(max(limit, 1), 500)),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["data"] = json.loads(item.get("data") or "{}")
        except ValueError:
            item["data"] = {}
        result.append(item)
    return result


def mark_read(user_id: int, notification_id: str) -> bool:
    with database.transaction() as conn:
        return bool(conn.execute(
            "UPDATE user_notifications SET read_at = ?, status = 'read' "
            "WHERE id = ? AND user_id = ?",
            (_now(), notification_id, user_id),
        ).rowcount)


def register_push_token(device_id: str, platform: str, token: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO device_push_tokens (device_id, platform, token, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(device_id, token) DO UPDATE SET "
            "platform = excluded.platform, updated_at = excluded.updated_at",
            (device_id, platform, token[:512], _now()),
        )
