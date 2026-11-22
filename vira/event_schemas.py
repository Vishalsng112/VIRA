"""Versioned event schemas for device ingestion and client discovery."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "device.telemetry.state": {
        "description": "Device identity and app version.",
        "required": [],
        "properties": {"app": {"type": "string"}, "platform": {"type": "string"}},
    },
    "device.telemetry.test": {
        "description": "Manual test event from the device client.",
        "required": [],
        "properties": {"message": {"type": "string"}},
    },
    "device.app.usage": {
        "description": "Aggregated foreground application time.",
        "required": ["apps", "total_foreground_ms"],
        "properties": {
            "apps": {"type": "array"},
            "total_foreground_ms": {"type": "integer"},
            "categories": {"type": "object"},
        },
    },
    "device.focus.state": {
        "description": "Focus/distraction summary for an interval.",
        "required": ["state"],
        "properties": {"state": {"type": "string"}, "focus_ms": {"type": "integer"}},
    },
    "device.focus.session": {
        "description": "User-started focus session.",
        "required": ["duration_seconds"],
        "properties": {"duration_seconds": {"type": "integer"}, "completed": {"type": "boolean"}},
    },
    "device.session.state": {
        "description": "Screen interactive time, unlocks and interactions.",
        "required": ["interactive_ms"],
        "properties": {"interactive_ms": {"type": "integer"}, "unlocks": {"type": "integer"}},
    },
    "device.battery.state": {
        "description": "Battery level, charging and temperature.",
        "required": [],
        "properties": {"level_percent": {"type": "integer"}, "charging": {"type": "boolean"}},
    },
    "device.health.state": {
        "description": "Storage, memory, thermal and health warnings.",
        "required": [],
        "properties": {"storage_percent": {"type": "integer"}, "warnings": {"type": "array"}},
    },
    "device.idle.state": {
        "description": "Desktop or Android focus/idle state.",
        "required": ["idle_seconds"],
        "properties": {"idle_seconds": {"type": "integer"}, "state": {"type": "string"}},
    },
    "sensor.hardware.state": {
        "description": "CPU, memory and uptime snapshot.",
        "required": [],
        "properties": {"cpu": {"type": "object"}, "memory": {"type": "object"}},
    },
    "sensor.network.state": {
        "description": "Network interface availability.",
        "required": [],
        "properties": {"interface_count": {"type": "integer"}},
    },
}


def seed_schemas(conn) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for event_type, schema in SCHEMAS.items():
        conn.execute(
            "INSERT INTO event_schemas (event_type, version, schema_json, description, created_at) "
            "VALUES (?, 1, ?, ?, ?) ON CONFLICT(event_type, version) DO UPDATE SET "
            "schema_json = excluded.schema_json, description = excluded.description",
            (event_type, json.dumps(schema, sort_keys=True), schema.get("description", ""), now),
        )


def validate_event(event_type: str, payload: Any, version: int = 1) -> Optional[str]:
    schema = SCHEMAS.get(event_type)
    if schema is None:
        return None
    if not isinstance(payload, dict):
        return "payload must be an object"
    for field in schema.get("required", []):
        if field not in payload:
            return f"missing required field '{field}'"
    properties = schema.get("properties", {})
    for field, rules in properties.items():
        if field not in payload:
            continue
        value = payload[field]
        expected = rules.get("type")
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"'{field}' must be an integer"
        if expected == "boolean" and not isinstance(value, bool):
            return f"'{field}' must be a boolean"
        if expected == "string" and not isinstance(value, str):
            return f"'{field}' must be a string"
        if expected == "array" and not isinstance(value, list):
            return f"'{field}' must be an array"
        if expected == "object" and not isinstance(value, dict):
            return f"'{field}' must be an object"
    return None
