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
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from vira.auth import database

_SUBSCRIBERS: Dict[int, Set[Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["data"] = json.loads(item.get("data") or "{}")
    except ValueError:
        item["data"] = {}
    return item


def subscribe(user_id: int):
    """Return a queue that receives new in-app notifications for this user."""
    import asyncio

    queue: Any = asyncio.Queue()
    _SUBSCRIBERS.setdefault(int(user_id), set()).add(queue)
    return queue


def unsubscribe(user_id: int, queue: Any) -> None:
    queues = _SUBSCRIBERS.get(int(user_id))
    if not queues:
        return
    queues.discard(queue)
    if not queues:
        _SUBSCRIBERS.pop(int(user_id), None)


def _publish(user_id: int, item: Dict[str, Any]) -> None:
    for queue in list(_SUBSCRIBERS.get(int(user_id), ())):
        try:
            queue.put_nowait(item)
        except Exception:
            pass


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
    result = {"id": notification_id, "title": title, "body": body,
              "kind": kind, "channel": channel, "status": status,
              "data": data or {}}
    _publish(user_id, result)
    return result


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


def push_tokens_for_user(user_id: int) -> List[Dict[str, str]]:
    """Device push tokens the user may receive notifications on."""
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT t.device_id, t.platform, t.token
            FROM device_push_tokens t
            JOIN devices d ON d.id = t.device_id
            LEFT JOIN user_device_access a
                ON a.device_id = d.id AND a.user_id = ? AND a.status = 'active'
            WHERE (d.created_by_user_id = ? OR a.user_id IS NOT NULL)
              AND d.status = 'active' AND d.revoked_at IS NULL
            """,
            (user_id, user_id),
        ).fetchall()
    return [
        {"device_id": row["device_id"], "platform": row["platform"],
         "token": row["token"]}
        for row in rows
    ]


def _post_webhook(url: str, payload: Dict[str, Any], timeout: float = 10,
                  headers: Optional[Dict[str, str]] = None) -> bool:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "VIRA-notifier",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            return 200 <= int(response.status) < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("Notification webhook failed: {}", exc)
        return False


def _payload(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item["id"],
        "user_id": item["user_id"],
        "title": item["title"],
        "body": item["body"],
        "kind": item["kind"],
        "data": item.get("data") or {},
        "created_at": item.get("created_at"),
    }


def _deliver_one(item: Dict[str, Any], *, webhook_url: Optional[str],
                 timeout: float, push_relay_url: Optional[str] = None,
                 push_relay_token: Optional[str] = None,
                 push_timeout: float = 10) -> bool:
    channel = item.get("channel") or "inapp"
    if channel == "webhook":
        if not webhook_url:
            logger.warning("Webhook notification {} has no configured URL", item["id"])
            return False
        return _post_webhook(webhook_url, _payload(item), timeout=timeout)
    if channel == "push":
        if not push_relay_url:
            logger.warning("Push notification {} has no relay URL", item["id"])
            return False
        tokens = push_tokens_for_user(int(item["user_id"]))
        if not tokens:
            logger.info("No push tokens registered for user {}", item["user_id"])
            return False
        headers = (
            {"Authorization": f"Bearer {push_relay_token}"}
            if push_relay_token else None
        )
        return _post_webhook(
            push_relay_url,
            {"tokens": tokens, "notification": _payload(item)},
            timeout=push_timeout,
            headers=headers,
        )
    # Unknown external channels are failed rather than retried forever.
    return False


def deliver_pending(limit: int = 50, *, webhook_url: Optional[str] = None,
                    timeout: float = 10, max_attempts: int = 3,
                    push_relay_url: Optional[str] = None,
                    push_relay_token: Optional[str] = None,
                    push_timeout: float = 10) -> Dict[str, int]:
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
        success = _deliver_one(
            item, webhook_url=webhook_url, timeout=timeout,
            push_relay_url=push_relay_url, push_relay_token=push_relay_token,
            push_timeout=push_timeout)
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
