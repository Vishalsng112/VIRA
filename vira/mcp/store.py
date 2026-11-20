"""Persistence for installed MCP servers and allow-list policies."""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_server(item: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("args", "env", "permissions", "allowed_tools", "denied_tools", "categories"):
        try:
            item[key] = json.loads(item.get(key) or ("{}" if key == "env" else "[]"))
        except (TypeError, ValueError):
            item[key] = {} if key == "env" else []
    item["enabled"] = bool(item.get("enabled"))
    return item


def _decode_policy(item: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("allowed_tools", "denied_tools"):
        try:
            item[key] = json.loads(item.get(key) or "[]")
        except (TypeError, ValueError):
            item[key] = []
    item["allowed"] = bool(item.get("allowed"))
    return item


def upsert_server(data: Dict[str, Any], user_id: Optional[int] = None) -> Dict[str, Any]:
    now = _now()
    name = str(data["name"]).strip()
    existing = get_server_by_name(name)
    server_id = existing["id"] if existing else str(data.get("id") or uuid.uuid4())
    values = {
        "id": server_id,
        "name": name,
        "description": str(data.get("description") or ""),
        "transport": str(data.get("transport") or "stdio"),
        "command": data.get("command") or None,
        "args": json.dumps(data.get("args") or []),
        "url": data.get("url") or None,
        "env": json.dumps(data.get("env") or {}),
        "permissions": json.dumps(data.get("permissions") or ["read", "execute"]),
        "allowed_tools": json.dumps(data.get("allowed_tools") or []),
        "denied_tools": json.dumps(data.get("denied_tools") or []),
        "categories": json.dumps(data.get("categories") or []),
        "version": str(data.get("version") or "1.0.0"),
        "source": str(data.get("source") or "manual"),
        "enabled": 1 if data.get("enabled", True) else 0,
        "created_by_user_id": user_id,
        "created_at": now,
        "updated_at": now,
    }
    with database.transaction() as conn:
        if existing:
            conn.execute(
                "UPDATE mcp_servers SET description = ?, transport = ?, command = ?, args = ?, "
                "url = ?, env = ?, permissions = ?, allowed_tools = ?, denied_tools = ?, "
                "categories = ?, version = ?, source = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (values["description"], values["transport"], values["command"], values["args"],
                 values["url"], values["env"], values["permissions"], values["allowed_tools"],
                 values["denied_tools"], values["categories"], values["version"], values["source"],
                 values["enabled"], values["updated_at"], server_id),
            )
        else:
            conn.execute(
                "INSERT INTO mcp_servers (id, name, description, transport, command, args, url, env, "
                "permissions, allowed_tools, denied_tools, categories, version, source, enabled, "
                "created_by_user_id, created_at, updated_at) VALUES (:id, :name, :description, "
                ":transport, :command, :args, :url, :env, :permissions, :allowed_tools, "
                ":denied_tools, :categories, :version, :source, :enabled, :created_by_user_id, "
                ":created_at, :updated_at)",
                values,
            )
    return get_server(server_id)


def get_server(server_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    return _decode_server(dict(row)) if row else None


def get_server_by_name(name: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM mcp_servers WHERE name = ?", (name,)).fetchone()
    return _decode_server(dict(row)) if row else None


def list_servers(enabled_only: bool = False) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        sql = "SELECT * FROM mcp_servers"
        if enabled_only:
            sql += " WHERE enabled = 1"
        rows = conn.execute(sql + " ORDER BY name").fetchall()
    return [_decode_server(dict(row)) for row in rows]


def set_enabled(server_id: str, enabled: bool) -> bool:
    with database.transaction() as conn:
        cur = conn.execute(
            "UPDATE mcp_servers SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), server_id),
        )
        return bool(cur.rowcount)


def delete_server(server_id: str) -> bool:
    with database.transaction() as conn:
        cur = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        return bool(cur.rowcount)


def set_policy(server_id: str, subject_type: str, subject_id: str, allowed: bool,
               allowed_tools: Optional[List[str]] = None,
               denied_tools: Optional[List[str]] = None) -> Dict[str, Any]:
    now = _now()
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM mcp_policies WHERE server_id = ? AND subject_type = ? AND subject_id = ?",
            (server_id, subject_type, subject_id),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE mcp_policies SET allowed = ?, allowed_tools = ?, denied_tools = ? WHERE id = ?",
                (1 if allowed else 0, json.dumps(allowed_tools or []),
                 json.dumps(denied_tools or []), row["id"]),
            )
            policy_id = row["id"]
        else:
            policy_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO mcp_policies (id, server_id, subject_type, subject_id, allowed, "
                "allowed_tools, denied_tools, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (policy_id, server_id, subject_type, subject_id, 1 if allowed else 0,
                 json.dumps(allowed_tools or []), json.dumps(denied_tools or []), now),
            )
    return get_policy(policy_id)


def get_policy(policy_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM mcp_policies WHERE id = ?", (policy_id,)).fetchone()
    return _decode_policy(dict(row)) if row else None


def list_policies(server_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        if server_id:
            rows = conn.execute(
                "SELECT * FROM mcp_policies WHERE server_id = ?", (server_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM mcp_policies").fetchall()
    return [_decode_policy(dict(row)) for row in rows]


def delete_policy(policy_id: str) -> bool:
    with database.transaction() as conn:
        cur = conn.execute("DELETE FROM mcp_policies WHERE id = ?", (policy_id,))
        return bool(cur.rowcount)
