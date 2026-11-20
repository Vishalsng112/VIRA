"""Loading and summarising device insight events."""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from vira.auth import database
from vira import secrets as vira_secrets
from vira.insights.aggregate import aggregate_events

INSIGHT_EVENT_TYPES = (
    "device.app.usage",
    "device.session.state",
    "device.focus.state",
    "device.focus.session",
    "device.battery.state",
    "device.health.state",
)


def load_events(device_id: str, days: int) -> Tuple[int, List[Dict[str, Any]]]:
    days = min(max(int(days), 1), 90)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    placeholders = ",".join("?" for _ in INSIGHT_EVENT_TYPES)
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT event_type, occurred_at, payload FROM device_events "
            f"WHERE device_id = ? AND occurred_at >= ? AND payload IS NOT NULL "
            f"AND event_type IN ({placeholders}) ORDER BY occurred_at LIMIT 20000",
            (device_id, cutoff, *INSIGHT_EVENT_TYPES),
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(vira_secrets.decrypt_payload(item["payload"]))
        except (TypeError, ValueError):
            item["payload"] = None
        events.append(item)
    return days, events


def summarize_device(device_id: str, days: int) -> Dict[str, Any]:
    days, events = load_events(device_id, days)
    result = aggregate_events(events, days)
    result["device_id"] = device_id
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result
