"""Durable, append-only event trail for the knowledge base.

Every write, supersession, deprecation and promotion is recorded locally and,
when an event bus is attached, published as a domain event.  This is the seam a
future consolidation algorithm subscribes to; the algorithm itself is out of
scope for now.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from vira.auth import database
from loguru import logger

KNOWLEDGE_WRITTEN = "knowledge.written"
KNOWLEDGE_SUPERSEDED = "knowledge.superseded"
KNOWLEDGE_DEPRECATED = "knowledge.deprecated"
KNOWLEDGE_PROMOTED = "knowledge.promoted"

_event_bus = None


def set_event_bus(event_bus) -> None:
    global _event_bus
    _event_bus = event_bus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(event: str, item_id: Optional[str] = None, *, actor: Optional[str] = None,
           agent_role: Optional[str] = None, data: Optional[dict] = None,
           publish: bool = True) -> None:
    payload = data or {}
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO knowledge_events "
            "(id, item_id, event, actor, agent_role, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), item_id, event, actor, agent_role,
             json.dumps(payload, default=str), _now()),
        )
    if publish and _event_bus is not None:
        try:
            from vira.kernel.event_bus import Event
            event_obj = Event(type=event, data={"item_id": item_id, **payload},
                              source=actor or "knowledge")
            _event_bus.publish(event_obj)
        except Exception:  # pragma: no cover - event publication is best effort
            logger.exception("failed to publish {}", event)


def list_events(item_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    with database.get_connection() as conn:
        if item_id:
            rows = conn.execute(
                "SELECT * FROM knowledge_events WHERE item_id = ? "
                "ORDER BY created_at DESC LIMIT ?", (item_id, min(max(limit, 1), 500))
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_events ORDER BY created_at DESC LIMIT ?",
                (min(max(limit, 1), 500),),
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
