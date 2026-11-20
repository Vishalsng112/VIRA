"""Durable agent run event timeline."""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(run_id: str, event_type: str, data: Any) -> str:
    event_id = str(uuid.uuid4())
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM agent_run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        seq = int(row["next_seq"])
        conn.execute(
            "INSERT INTO agent_run_events (id, run_id, seq, event_type, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, run_id, seq, event_type,
             json.dumps(data, default=str, ensure_ascii=False)[:20000], _now()),
        )
    return event_id


def timeline(run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Redacted tool/thinking timeline for operators and the chat UI."""
    from vira.security.redaction import redact

    items = []
    for event in list_events(run_id, 0, limit):
        data = redact(event.get("data") or {})
        if isinstance(data, dict):
            if "params" in data:
                data["params"] = redact(data["params"])
            if "preview" in data and isinstance(data["preview"], str):
                data["preview"] = data["preview"][:1200]
        items.append({
            "seq": event.get("seq"),
            "type": event.get("event_type"),
            "created_at": event.get("created_at"),
            "data": data,
        })
    return items


def list_events(run_id: str, after_seq: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_run_events WHERE run_id = ? AND seq > ? "
            "ORDER BY seq LIMIT ?",
            (run_id, max(0, after_seq), min(max(limit, 1), 2000)),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["data"] = json.loads(item["data"])
        except ValueError:
            item["data"] = {}
        result.append(item)
    return result
