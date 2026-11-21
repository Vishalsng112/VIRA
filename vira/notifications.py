"""In-app notification queue, delivery providers and push-token registration.

In-app notifications are delivered immediately (they are visible in the API as
soon as they are created). External channels are queued with ``status=pending``
and delivered by the worker through a provider. The first provider is a generic
JSON webhook, which also makes FCM/APNs gateways easy to add at deployment time.
"""
import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["data"] = json.loads(item.get("data") or "{}")
    except ValueError:
        item["data"] = {}
    return item


def create(user_id: int, title: str, body: str = "", kind: str = "system",
           device_id: Optional[str] = None, data: Optional[dict] = None,
           channel: str = "inapp", dedupe_key: Optional[str] = None) -> Dict[str, Any]:
    """Create a notification.

    ``inapp`` is immediately delivered; any other channel stays pending for the
    delivery worker. A repeated ``(user_id, dedupe_key)`` returns the existing
    notification instead of creating a duplicate.
    """
    now = _now()
    if dedupe_key:
        with database.get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM user_notifications WHERE user_id = ? AND dedupe_key = ?",
                (user_id, dedupe_key),
            ).fetchone()
        if existing:
            return _row(existing)

    notification_id = str(uuid.uuid4())
    delivered = now if channel == "inapp" else None
    status = "delivered" if channel == "inapp" else "pending"
    with database.transaction() as conn:
        try:
            conn.execute(
                "INSERT INTO user_notifications "
                "(id, user_id, device_id, kind, title, body, data, status, "
                "channel, dedupe_key, attempts, created_at, delivered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (notification_id, user_id, device_id, kind, title[:200], body,
                 json.dumps(data or {}, default=str), status, channel,
                 dedupe_key, now, delivered),
            )
        except Exception:
            if dedupe_key:
                with database.get_connection() as conn:
                    existing = conn.execute(
                        "SELECT * FROM user_notifications WHERE user_id = ? AND dedupe_key = ?",
                        (user_id, dedupe_key),
                    ).fetchone()
                if existing:
                    return _row(existing)
            raise
    return {"id": notification_id, "title": title, "body": body, "kind": kind,
            "channel": channel, "status": status}


def list_for_user(user_id: int, limit: int = 100, unread_only: bool = False) -> List[Dict[str, Any]]:
    clause = "AND read_at IS NULL" if unread_only else ""
    with database.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM user_notifications WHERE user_id = ? {clause} "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, min(max(limit, 1), 500)),
        ).fetchall()
    return [_row(row) for row in rows]


def mark_read(user_id: int, notification_id: str) -> bool:
    with database.transaction() as conn:
        return bool(conn.execute(
            "UPDATE user_notifications SET read_at = ?, status = 'read' "
            "WHERE id = ? AND user_id = ?",
            (_now(), notification_id, user_id),
        ).rowcount)


def unread_count(user_id: int) -> int:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM user_notifications "
            "WHERE user_id = ? AND read_at IS NULL", (user_id,)
        ).fetchone()
    return int(row["count"] or 0)


def register_push_token(device_id: str, platform: str, token: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO device_push_tokens (device_id, platform, token, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(device_id, token) DO UPDATE SET "
            "platform = excluded.platform, updated_at = excluded.updated_at",
            (device_id, platform, token[:512], _now()),
        )


def _post_webhook(url: str, payload: Dict[str, Any], timeout: float = 10) -> bool:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "VIRA-notifier"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            return 200 <= int(response.status) < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("Notification webhook failed: {}", exc)
        return False


def _deliver_one(item: Dict[str, Any], *, webhook_url: Optional[str],
                 timeout: float) -> bool:
    channel = item.get("channel") or "inapp"
    if channel == "webhook":
        if not webhook_url:
            logger.warning("Webhook notification {} has no configured URL", item["id"])
            return False
        return _post_webhook(webhook_url, {
            "id": item["id"],
            "user_id": item["user_id"],
            "title": item["title"],
            "body": item["body"],
            "kind": item["kind"],
            "data": item.get("data") or {},
            "created_at": item.get("created_at"),
        }, timeout=timeout)
    # Unknown external channels are failed rather than retried forever.
    return False


def deliver_pending(limit: int = 50, *, webhook_url: Optional[str] = None,
                    timeout: float = 10, max_attempts: int = 3) -> Dict[str, int]:
    """Deliver queued external notifications. Safe to run periodically."""
    limit = max(1, min(int(limit), 200))
    max_attempts = max(1, int(max_attempts))
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM user_notifications WHERE status = 'pending' "
            "AND channel != 'inapp' AND attempts < ? "
            "ORDER BY created_at LIMIT ?",
            (max_attempts, limit),
        ).fetchall()
    delivered = failed = 0
    for row in rows:
        item = _row(row)
        success = _deliver_one(item, webhook_url=webhook_url, timeout=timeout)
        attempts = int(item.get("attempts") or 0) + 1
        now = _now()
        with database.transaction() as conn:
            if success:
                conn.execute(
                    "UPDATE user_notifications SET status = 'delivered', "
                    "delivered_at = ?, attempts = ?, last_error = NULL WHERE id = ?",
                    (now, attempts, item["id"]),
                )
                delivered += 1
            else:
                exhausted = attempts >= max_attempts
                conn.execute(
                    "UPDATE user_notifications SET status = ?, attempts = ?, "
                    "last_error = ? WHERE id = ?",
                    ("failed" if exhausted else "pending", attempts,
                     "delivery failed or channel not configured", item["id"]),
                )
                failed += 1
    return {"delivered": delivered, "failed": failed, "checked": len(rows)}
