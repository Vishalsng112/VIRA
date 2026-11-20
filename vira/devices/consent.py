"""Per-device collector consent and purpose/retention policy."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from vira.auth import database

COLLECTORS = {
    "device_status": {"title": "Device status", "events": ["device.telemetry.state"]},
    "hardware_state": {"title": "Hardware", "events": ["sensor.hardware.state"]},
    "network_state": {"title": "Network", "events": ["sensor.network.state"]},
    "app_usage": {"title": "App usage", "events": ["device.app.usage", "device.focus.state"]},
    "active_window": {"title": "Active window", "events": ["device.app.usage", "device.focus.state"]},
    "screen_session": {"title": "Screen & sessions", "events": ["device.session.state"]},
    "battery_state": {"title": "Battery", "events": ["device.battery.state"]},
    "device_health": {"title": "Device health", "events": ["device.health.state"]},
    "idle_state": {"title": "Idle state", "events": ["device.idle.state"]},
    "focus_session": {"title": "Focus sessions", "events": ["device.focus.session"]},
}

_EVENT_COLLECTORS: Dict[str, Tuple[str, ...]] = {}
for _collector, _meta in COLLECTORS.items():
    for _event in _meta["events"]:
        _EVENT_COLLECTORS.setdefault(_event, tuple())
        _EVENT_COLLECTORS[_event] = _EVENT_COLLECTORS[_event] + (_collector,)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def consent_map(device_id: str) -> Dict[str, Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM device_consents WHERE device_id = ?", (device_id,)
        ).fetchall()
    return {row["collector"]: dict(row) for row in rows}


def list_for_device(device_id: str) -> List[Dict[str, Any]]:
    current = consent_map(device_id)
    result = []
    for collector, meta in COLLECTORS.items():
        row = current.get(collector)
        result.append({
            "collector": collector,
            "title": meta["title"],
            "events": list(meta["events"]),
            "enabled": bool(row["enabled"]) if row else True,
            "purpose": row["purpose"] if row else "device_insights",
            "retention_hours": row["retention_hours"] if row else None,
            "updated_at": row["updated_at"] if row else None,
            "revoked_at": row["revoked_at"] if row else None,
            "explicit": row is not None,
        })
    return result


def set_consent(device_id: str, collector: str, enabled: bool,
                purpose: str = "device_insights", retention_hours: Optional[int] = None,
                user_id: Optional[int] = None) -> Dict[str, Any]:
    if collector not in COLLECTORS:
        raise ValueError("unknown collector")
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            """
            INSERT INTO device_consents
                (device_id, collector, enabled, purpose, retention_hours, updated_at,
                 updated_by_user_id, revoked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, collector) DO UPDATE SET
                enabled = excluded.enabled, purpose = excluded.purpose,
                retention_hours = excluded.retention_hours, updated_at = excluded.updated_at,
                updated_by_user_id = excluded.updated_by_user_id, revoked_at = excluded.revoked_at
            """,
            (device_id, collector, 1 if enabled else 0, purpose, retention_hours, now,
             user_id, None if enabled else now),
        )
    return list_for_device(device_id)[list(COLLECTORS).index(collector)]


def _collectors_for(event_type: str, payload: Optional[Dict[str, Any]] = None):
    if event_type in ("device.app.usage", "device.focus.state") and payload:
        method = payload.get("capture_method")
        if method == "desktop_active_window":
            return ("active_window",)
        if method == "android_usage_stats":
            return ("app_usage",)
    return _EVENT_COLLECTORS.get(event_type, ())


def is_allowed(consents: Dict[str, Dict[str, Any]], event_type: str,
               payload: Optional[Dict[str, Any]] = None) -> bool:
    collectors = _collectors_for(event_type, payload)
    if not collectors:
        return True
    explicit = [consents.get(collector) for collector in collectors]
    explicit = [row for row in explicit if row is not None]
    if not explicit:
        # Backwards compatible default: existing devices keep sending until
        # the user sets an explicit consent row.
        return True
    return any(bool(row.get("enabled")) and not row.get("revoked_at")
               for row in explicit)


def retention_for(consents: Dict[str, Dict[str, Any]], event_type: str,
                  payload: Optional[Dict[str, Any]] = None) -> Optional[int]:
    for collector in _collectors_for(event_type, payload):
        row = consents.get(collector)
        if row and row.get("retention_hours"):
            return int(row["retention_hours"])
    return None
