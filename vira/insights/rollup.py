"""Materialised daily insight rollups from device events."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from vira.auth import database
from vira import secrets as vira_secrets
from vira.insights.aggregate import aggregate_events
from vira.insights.service import INSIGHT_EVENT_TYPES


def refresh_daily(days: int = 3) -> int:
    """Rebuild ``insight_daily`` for the recent window. Returns rows written."""
    days = min(max(int(days), 1), 90)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    placeholders = ",".join("?" for _ in INSIGHT_EVENT_TYPES)
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT device_id, event_type, occurred_at, payload FROM device_events "
            "WHERE occurred_at >= ? AND payload IS NOT NULL "
            f"AND event_type IN ({placeholders}) ORDER BY device_id, occurred_at",
            (cutoff, *INSIGHT_EVENT_TYPES),
        ).fetchall()
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(vira_secrets.decrypt_payload(item["payload"]))
        except (TypeError, ValueError):
            continue
        day = str(item["occurred_at"])[:10]
        grouped[(item["device_id"], day)].append(item)

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    with database.transaction() as conn:
        for (device_id, day), events in grouped.items():
            summary = aggregate_events(events, 1)
            totals = summary["totals"]
            conn.execute(
                """
                INSERT INTO insight_daily
                    (device_id, day, app_ms, screen_ms, unlocks, focus_ms, distraction_ms,
                     focus_sessions, focus_score, top_apps, categories, warnings, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, day) DO UPDATE SET
                    app_ms = excluded.app_ms, screen_ms = excluded.screen_ms,
                    unlocks = excluded.unlocks, focus_ms = excluded.focus_ms,
                    distraction_ms = excluded.distraction_ms,
                    focus_sessions = excluded.focus_sessions, focus_score = excluded.focus_score,
                    top_apps = excluded.top_apps, categories = excluded.categories,
                    warnings = excluded.warnings, updated_at = excluded.updated_at
                """,
                (
                    device_id, day, totals.get("app_ms", 0), totals.get("screen_ms", 0),
                    totals.get("unlocks", 0), totals.get("focus_ms", 0),
                    totals.get("distraction_ms", 0), totals.get("focus_sessions", 0),
                    totals.get("focus_score", 0),
                    json.dumps(summary.get("top_apps", []), default=str),
                    json.dumps(summary.get("categories", []), default=str),
                    json.dumps(summary.get("health", {}).get("warnings", []), default=str),
                    now,
                ),
            )
            written += 1
    return written


def list_daily(device_id: str, days: int = 7) -> List[Dict[str, Any]]:
    days = min(max(int(days), 1), 90)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM insight_daily WHERE device_id = ? AND day >= ? ORDER BY day",
            (device_id, cutoff),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("top_apps", "categories", "warnings"):
            try:
                item[key] = json.loads(item[key])
            except (TypeError, ValueError):
                item[key] = []
        result.append(item)
    return result
