"""Per-user export and deletion across all VIRA stores."""
from typing import Any, Dict, List

from vira.auth import auth, database
from vira.auth.principals import UserPrincipal
from vira.devices import store as device_store
from vira.devices import consent as consent_store
from vira.devices import commands as command_store
from vira.insights.rollup import list_daily
from vira.knowledge.store import get_store as get_knowledge_store

MAX_EVENTS_PER_DEVICE = 5000


def _messages(user_id: int, conversation_id: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = database.list_messages(conversation_id, user_id, limit=100, offset=offset)
        if not page:
            break
        result.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    return result


def export_user(user: UserPrincipal) -> Dict[str, Any]:
    record = database.get_user_by_id(user.user_id) or {}
    devices = device_store.list_devices_for_user(user.user_id, limit=200)
    device_items = []
    for device in devices:
        device_id = device["id"]
        device_items.append({
            "device": device,
            "consent": consent_store.list_for_device(device_id),
            "commands": command_store.list_for_device(device_id, limit=200),
            "insights": list_daily(device_id, days=90),
            "events": device_store.list_events(
                device_id, limit=MAX_EVENTS_PER_DEVICE, include_payload=True
            ),
        })
    conversations = []
    for conversation in database.list_conversations(user.user_id, limit=100):
        conversations.append({
            **conversation,
            "messages": _messages(user.user_id, conversation["id"]),
        })
    memories = database.search_memories(user.user_id, query=None, limit=1000)
    with database.get_connection() as conn:
        notifications = [dict(row) for row in conn.execute(
            "SELECT * FROM user_notifications WHERE user_id = ? ORDER BY created_at DESC",
            (user.user_id,),
        ).fetchall()]
        audit = [dict(row) for row in conn.execute(
            "SELECT * FROM auth_audit WHERE user_id = ? ORDER BY created_at DESC LIMIT 1000",
            (user.user_id,),
        ).fetchall()]
    return {
        "user": {
            "user_id": record.get("public_id"),
            "username": record.get("username"),
            "role": record.get("role"),
            "status": record.get("status"),
            "created_at": record.get("created_at"),
        },
        "devices": device_items,
        "conversations": conversations,
        "memories": memories,
        "knowledge": get_knowledge_store().export_user(user.user_id),
        "notifications": notifications,
        "audit": audit,
    }


def delete_user_data(user: UserPrincipal, delete_devices: bool = True) -> Dict[str, int]:
    user_id = user.user_id
    with database.transaction() as conn:
        device_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM devices WHERE created_by_user_id = ?", (user_id,)
        ).fetchall()]
        counts = {"devices": len(device_ids), "events": 0, "conversations": 0,
                  "memories": 0, "knowledge": 0}
        if device_ids:
            placeholders = ",".join("?" for _ in device_ids)
            for table in ("device_events", "device_latest_state", "insight_daily",
                          "device_consents", "device_commands"):
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE device_id IN ({placeholders})",
                    tuple(device_ids),
                )
                if table == "device_events":
                    counts["events"] = cur.rowcount
            if delete_devices:
                conn.execute(f"DELETE FROM devices WHERE id IN ({placeholders})", tuple(device_ids))
        cur = conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        counts["conversations"] = cur.rowcount
        conn.execute("DELETE FROM incognito_conversations WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        counts["memories"] = cur.rowcount
        conn.execute("DELETE FROM user_notifications WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM device_pairing_codes WHERE created_by_user_id = ?", (user_id,))
    # Knowledge deletion goes through the storage port, not raw SQL. It runs
    # after the transaction above because the adapter owns its own transaction.
    counts["knowledge"] = get_knowledge_store().delete_for_user(user_id)
    return counts
