"""Persistence for installed plugin manifests and namespaced plugin state."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert(manifest) -> None:
    now = _now()
    with database.transaction() as conn:
        existing = conn.execute(
            "SELECT enabled FROM plugins WHERE id = ?", (manifest.id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO plugins (id, name, version, api_version, description, author, "
                "entrypoint, manifest, permissions, status, enabled, installed_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', 1, ?, ?)",
                (manifest.id, manifest.name, manifest.version, manifest.api_version,
                 manifest.description, manifest.author, manifest.entrypoint,
                 json.dumps(manifest.as_dict()), json.dumps(manifest.permissions),
                 now, now),
            )
        else:
            conn.execute(
                "UPDATE plugins SET name = ?, version = ?, api_version = ?, description = ?, "
                "author = ?, entrypoint = ?, manifest = ?, permissions = ?, updated_at = ? "
                "WHERE id = ?",
                (manifest.name, manifest.version, manifest.api_version, manifest.description,
                 manifest.author, manifest.entrypoint, json.dumps(manifest.as_dict()),
                 json.dumps(manifest.permissions), now, manifest.id),
            )


def get(plugin_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
    return _decode(dict(row)) if row else None


def list_all() -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute("SELECT * FROM plugins ORDER BY name").fetchall()
    return [_decode(dict(row)) for row in rows]


def set_enabled(plugin_id: str, enabled: bool) -> bool:
    with database.transaction() as conn:
        cur = conn.execute(
            "UPDATE plugins SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), plugin_id),
        )
        return bool(cur.rowcount)


def set_status(plugin_id: str, status: str, error: Optional[str] = None) -> None:
    with database.transaction() as conn:
        conn.execute(
            "UPDATE plugins SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, _now(), plugin_id),
        )


def delete(plugin_id: str) -> bool:
    with database.transaction() as conn:
        conn.execute("DELETE FROM plugin_storage WHERE plugin_id = ?", (plugin_id,))
        cur = conn.execute("DELETE FROM plugins WHERE id = ?", (plugin_id,))
        return bool(cur.rowcount)


def storage_get(plugin_id: str, key: str, default: Any = None) -> Any:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM plugin_storage WHERE plugin_id = ? AND key = ?",
            (plugin_id, key),
        ).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return default


def storage_set(plugin_id: str, key: str, value: Any) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO plugin_storage (plugin_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(plugin_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (plugin_id, key, json.dumps(value, default=str), _now()),
        )


def storage_delete(plugin_id: str, key: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "DELETE FROM plugin_storage WHERE plugin_id = ? AND key = ?", (plugin_id, key)
        )


def _decode(item: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("manifest", "permissions"):
        try:
            item[key] = json.loads(item.get(key) or "{}")
        except ValueError:
            item[key] = {} if key == "manifest" else []
    item["enabled"] = bool(item.get("enabled"))
    return item
