"""Read-only database access for the VIRA Chatbot and agents.

This module is deliberately separate from the HTTP API.  It exposes:

* a compact, secret-free schema catalogue so a model can write SQL;
* a SQL validator and a read-only connection;
* curated examples and a safe per-account summary.

It is used by ``vira/mcp/servers/database/server.py`` (the MCP server) and is
kept importable without an MCP runtime so it can be unit-tested directly.
"""
from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Tables that are internal, secret-bearing, or too large to be useful.
HIDDEN_TABLES = {
    "sqlite_sequence",
    "schema_migrations",
    "memory_embeddings",
    "plugin_storage",
    "device_push_tokens",
    "device_pairing_codes",
    "sync_op_receipts",
    "family_changes",
}

# Columns that must never be returned to a model.
HIDDEN_COLUMNS: Dict[str, set] = {
    "users": {"password_hash", "recovery_code_hash"},
    "sessions": {"session_id_hash"},
    "device_credentials": {"credential_hash"},
    "auth_audit": {"session_id_hash"},
    "mcp_servers": {"env", "command", "args", "url"},
    "objects": {"storage_key"},
    "rag_chunks": {"vector"},
    "memory_embeddings": {"vector"},
}

# Identifiers rejected even when a table/column is not in the catalogue.
BLOCKED_IDENTIFIERS = {
    "password_hash", "recovery_code_hash", "session_id_hash", "credential_hash",
    "code_hash", "token", "storage_key", "vector", "env",
    "plugin_storage", "device_push_tokens", "device_pairing_codes",
    "memory_embeddings", "schema_migrations", "sqlite_sequence",
}

WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "REPLACE", "UPSERT", "MERGE",
    "DROP", "ALTER", "CREATE", "TRUNCATE", "ATTACH", "DETACH",
    "PRAGMA", "VACUUM", "REINDEX", "ANALYZE", "GRANT", "REVOKE",
    "CALL", "COPY", "DO", "SET", "RESET", "BEGIN", "COMMIT",
    "ROLLBACK", "SAVEPOINT", "RELEASE", "LOCK", "UNLOCK", "EXEC",
    "EXECUTE", "INTO", "LOAD", "IMPORT", "EXPORT", "SHUTDOWN", "KILL",
}
BLOCKED_FUNCTIONS = {
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer",
}

TOOL_DESCRIPTIONS: Dict[str, str] = {
    "users": "User accounts. role is admin/user; status is active/disabled.",
    "sessions": "Signed-in user sessions (hashes only).",
    "devices": "Endpoint devices. status=pending/active/revoked/retired; "
               "is_server_local=1 is the VIRA host; queue_backlog is unsent events.",
    "user_device_access": "Which user can use which device. "
                          "Join a.user_id -> users.id and a.device_id -> devices.id; "
                          "status='active' grants access.",
    "device_credentials": "Device credential metadata (hash hidden).",
    "device_events": "Telemetry events from devices. Prefer COUNT/GROUP BY; "
                     "payload is JSON and can be large.",
    "device_latest_state": "Latest event per device and event_type.",
    "device_consents": "Per-device collector consent choices.",
    "device_commands": "Commands queued for devices.",
    "insight_daily": "Daily aggregated device insights: app_ms, screen_ms, unlocks, focus.",
    "agent_definitions": "Configured agents. enabled=1 means active.",
    "agent_runs": "Agent/chat run history and status.",
    "agent_run_events": "Per-run progress events.",
    "conversations": "Chat conversations per user.",
    "messages": "Chat messages (content can be large).",
    "memories": "Long-term memory records.",
    "tool_calls": "Audit of every tool execution, including status and duration.",
    "llm_usage": "Token and cost usage per model request.",
    "mcp_servers": "Installed MCP servers (secret env/command hidden).",
    "jobs": "Durable background job queue.",
    "workflows": "Durable workflow definitions and status.",
    "auth_audit": "Authentication and administrator audit log.",
    "organizations": "Organizations and members.",
    "objects": "Object storage metadata.",
    "plugins": "Installed plugins.",
    "rag_documents": "RAG document metadata.",
    "rag_chunks": "RAG chunks (vectors hidden).",
    "households": "Households and members.",
    "notebooks": "Household notebooks.",
    "family_notes": "Household notes.",
    "reminders": "Household reminders.",
    "user_notifications": "User notifications.",
    "llm_quotas": "LLM quota settings.",
    "update_releases": "Update release metadata.",
    "event_schemas": "Known device event schemas.",
}

# The short schema returned when the model calls database_schema with no filter.
CORE_TABLES = [
    "users", "devices", "user_device_access", "device_events",
    "agent_definitions", "conversations", "messages", "tool_calls",
    "llm_usage", "insight_daily", "mcp_servers", "jobs",
]


# --------------------------------------------------------------------------- #
# connections
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def read_connection():
    """Open a guaranteed read-only database connection."""
    from vira.auth import database as vdb

    if vdb.is_postgres():
        from vira.db.postgres import connect

        url = vdb.READ_DATABASE_URL or vdb.DATABASE_URL
        conn = connect(url)
        try:
            # Defence in depth: the validator blocks writes too.
            conn.execute("SET default_transaction_read_only = on")
            conn.execute("SET statement_timeout = '8s'")
            yield conn
        finally:
            conn.close()
        return

    path = Path(vdb.DB_PATH)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    # mode=ro is enforced by SQLite itself, regardless of the SQL sent.
    uri = path.expanduser().resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    deadline = time.monotonic() + 8.0

    def _abort() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_abort, 10_000)
    try:
        yield conn
    finally:
        conn.close()


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _table_names(conn) -> List[str]:
    from vira.auth import database as vdb

    if vdb.is_postgres():
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()
        names = [row["table_name"] if isinstance(row, dict) else row[0] for row in rows]
    else:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        names = [row["name"] for row in rows]
    return [name for name in names if name not in HIDDEN_TABLES]


def _columns(conn, table: str) -> List[Dict[str, Any]]:
    from vira.auth import database as vdb

    hidden = HIDDEN_COLUMNS.get(table, set())
    result: List[Dict[str, Any]] = []
    if vdb.is_postgres():
        rows = conn.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ? ORDER BY ordinal_position",
            (table,),
        ).fetchall()
        for row in rows:
            item = dict(row) if isinstance(row, dict) else {
                "column_name": row[0], "data_type": row[1], "is_nullable": row[2]
            }
            name = item["column_name"]
            if name in hidden:
                continue
            result.append({
                "name": name,
                "type": item.get("data_type") or "",
                "nullable": str(item.get("is_nullable", "YES")).upper() == "YES",
                "primary_key": False,
                "references": None,
            })
    else:
        rows = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        for row in rows:
            name = row["name"]
            if name in hidden:
                continue
            result.append({
                "name": name,
                "type": row["type"] or "",
                "nullable": not bool(row["notnull"]),
                "primary_key": bool(row["pk"]),
                "references": None,
            })

    # Foreign keys (SQLite and PostgreSQL).
    if vdb.is_postgres():
        fks = conn.execute(
            "SELECT kcu.column_name, ccu.table_name AS foreign_table, "
            "ccu.column_name AS foreign_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            " AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = tc.constraint_name "
            " AND ccu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "AND tc.table_schema = 'public' AND tc.table_name = ?",
            (table,),
        ).fetchall()
        refs = {
            (row["column_name"] if isinstance(row, dict) else row[0]):
                f"{row['foreign_table'] if isinstance(row, dict) else row[1]}."
                f"{row['foreign_column'] if isinstance(row, dict) else row[2]}"
            for row in fks
        }
    else:
        fks = conn.execute(f"PRAGMA foreign_key_list({_quote(table)})").fetchall()
        refs = {row["from"]: f"{row['table']}.{row['to']}" for row in fks}

    for column in result:
        column["references"] = refs.get(column["name"])
    return result


def _row_count(conn, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()
        return int(row[0] if not isinstance(row, dict) else next(iter(row.values())))
    except Exception:
        return 0


def _compact_columns(columns: Sequence[Dict[str, Any]], limit: int = 8) -> List[str]:
    names = [column["name"] for column in columns]
    primary = [column["name"] for column in columns if column.get("primary_key")]
    ordered = primary + [name for name in names if name not in primary]
    return ordered[:limit]


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
def table_catalog(query: str = "", limit: int = 20) -> Dict[str, Any]:
    """List discoverable tables with one-line descriptions."""
    limit = _clamp(limit, 1, 60)
    tokens = _tokens(query)
    with read_connection() as conn:
        names = _table_names(conn)
        rows = []
        for name in names:
            columns = _columns(conn, name)
            description = TOOL_DESCRIPTIONS.get(name, "Server table.")
            haystack = f"{name} {description} {' '.join(c['name'] for c in columns)}".lower()
            score = sum(3 for token in tokens if token in name.lower())
            score += sum(1 for token in tokens if token in haystack)
            if not tokens:
                score = 100 if name in CORE_TABLES else 0
            if tokens and score == 0:
                continue
            rows.append({
                "name": name,
                "description": description,
                "columns": len(columns),
                "key_columns": _compact_columns(columns, 6),
                "_score": score,
            })
        rows.sort(key=lambda item: (-item["_score"], item["name"]))
        for item in rows:
            item.pop("_score", None)
        return {
            "ok": True,
            "tables": rows[:limit],
            "total_tables": len(rows),
            "hint": "Call database_schema with table='name' for full columns and relationships.",
        }


def describe_schema(
    table: str = "",
    search: str = "",
    include_row_counts: bool = False,
    limit: int = 8,
) -> Dict[str, Any]:
    """Return full columns, types and relationships for matching tables."""
    limit = _clamp(limit, 1, 20)
    with read_connection() as conn:
        names = _table_names(conn)
        query = (table or search or "").strip()
        if query:
            tokens = _tokens(query)
            selected = []
            for name in names:
                columns = _columns(conn, name)
                description = TOOL_DESCRIPTIONS.get(name, "")
                haystack = f"{name} {description} {' '.join(c['name'] for c in columns)}".lower()
                score = 10 if name.lower() == query.lower() else 0
                score += sum(3 for token in tokens if token in name.lower())
                score += sum(1 for token in tokens if token in haystack)
                if score:
                    selected.append((score, name, columns))
            selected.sort(key=lambda item: (-item[0], item[1]))
            chosen = selected[:limit]
        else:
            chosen = [
                (0, name, _columns(conn, name))
                for name in CORE_TABLES
                if name in names
            ][:limit]

        tables = []
        for _, name, columns in chosen:
            tables.append({
                "name": name,
                "description": TOOL_DESCRIPTIONS.get(name, "Server table."),
                "columns": columns,
                **({"row_count": _row_count(conn, name)} if include_row_counts else {}),
            })
        return {
            "ok": True,
            "tables": tables,
            "notes": [
                "Use {{caller_user_id}} for the signed-in user, for example "
                "WHERE a.user_id = {{caller_user_id}}.",
                "Custom SQL is SELECT/WITH only, one statement, maximum 200 rows.",
                "Sensitive columns (password hashes, credential hashes, tokens, vectors) are hidden.",
            ],
        }


def examples() -> Dict[str, Any]:
    """Curated read-only queries for common questions."""
    return {
        "ok": True,
        "examples": [
            {
                "question": "How many devices are connected with my account?",
                "sql": "SELECT COUNT(DISTINCT d.id) AS devices "
                       "FROM devices d JOIN user_device_access a ON a.device_id = d.id "
                       "WHERE a.user_id = {{caller_user_id}} AND a.status = 'active' "
                       "AND d.status = 'active'",
                "scope": "caller",
            },
            {
                "question": "How many devices are connected with the server?",
                "sql": "SELECT status, COUNT(*) AS count FROM devices GROUP BY status",
                "scope": "server",
            },
            {
                "question": "Which agents are active?",
                "sql": "SELECT name, enabled, created_at FROM agent_definitions "
                       "WHERE enabled = 1 ORDER BY name",
                "scope": "server",
            },
            {
                "question": "What are my recent conversations?",
                "sql": "SELECT id, title, created_at, updated_at FROM conversations "
                       "WHERE user_id = {{caller_user_id}} ORDER BY updated_at DESC LIMIT 10",
                "scope": "caller",
            },
            {
                "question": "How many tool calls succeeded or failed today?",
                "sql": "SELECT status, COUNT(*) AS count FROM tool_calls "
                       "WHERE created_at >= date('now') GROUP BY status",
                "scope": "server",
            },
            {
                "question": "Which devices have not reported recently?",
                "sql": "SELECT display_name, platform, status, last_seen_at "
                       "FROM devices WHERE status = 'active' "
                       "AND (last_seen_at IS NULL OR last_seen_at < datetime('now','-7 day'))",
                "scope": "server",
            },
        ],
        "note": "For questions about the signed-in user's own account, use "
                "database_account_summary or {{caller_user_id}} in SQL. "
                "Timestamp expressions in the examples are SQLite-style; on "
                "PostgreSQL use now() and intervals instead.",
    }


# --------------------------------------------------------------------------- #
# safe SQL
# --------------------------------------------------------------------------- #
def _clamp(value: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return low


def _tokens(value: str) -> set:
    return {
        token for token in re.findall(r"[a-z0-9_]+", (value or "").lower())
        if len(token) > 1
    }


def _strip_literals(sql: str) -> str:
    """Replace strings and comments with spaces, preserving structure."""
    out: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == "\\" and quote == "'" and i + 1 < n:
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i + 2)
            i = n if end == -1 else end + 1
            out.append(" ")
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def validate_sql(sql: str) -> Tuple[bool, str]:
    """Validate a single read-only statement. Returns (ok, reason)."""
    raw = (sql or "").strip()
    if not raw:
        return False, "SQL is empty."
    if len(raw) > 5000:
        return False, "SQL is too long (maximum 5000 characters)."
    if "\x00" in raw or "$$" in raw:
        return False, "Unsupported characters in SQL."

    clean = _strip_literals(raw).strip()
    if not clean:
        return False, "SQL does not contain a statement."

    if ";" in clean:
        if clean.count(";") == 1 and clean.endswith(";"):
            clean = clean[:-1].rstrip()
        else:
            return False, "Only one statement is allowed (remove extra semicolons)."
    if ";" in clean:
        return False, "Only one statement is allowed."

    first = clean.split(None, 1)[0].upper()
    if first not in {"SELECT", "WITH"}:
        return False, "Only SELECT or WITH queries are allowed."

    upper = clean.upper()
    for keyword in WRITE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", upper):
            return False, f"Write operation '{keyword}' is not allowed."

    identifiers = set(re.findall(r"[a-z_][a-z0-9_]*", clean.lower()))
    blocked = identifiers & BLOCKED_IDENTIFIERS
    if blocked:
        return False, "Restricted identifier(s): " + ", ".join(sorted(blocked))
    blocked_functions = identifiers & BLOCKED_FUNCTIONS
    if blocked_functions:
        return False, "Restricted function(s): " + ", ".join(sorted(blocked_functions))
    if re.search(r"\bFOR\s+(UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b", upper):
        return False, "Locking clauses are not allowed."
    return True, ""


# --------------------------------------------------------------------------- #
# query execution
# --------------------------------------------------------------------------- #
def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000] + "…[truncated]"
    return value


def _user(conn, caller_user_id: int) -> Optional[Dict[str, Any]]:
    try:
        row = conn.execute(
            "SELECT id, username, role, status FROM users WHERE id = ?",
            (caller_user_id,),
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return dict(row) if not isinstance(row, sqlite3.Row) else dict(row)


def run_query(
    sql: str,
    limit: int = 100,
    caller_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute one validated read-only query for an administrator caller."""
    if caller_user_id is None:
        return {
            "ok": False,
            "error": "A caller identity is required for custom database queries.",
            "hint": "Use database_account_summary for the signed-in user.",
        }
    limit = _clamp(limit, 1, 200)
    prepared = re.sub(
        r"\{\{\s*caller_user_id\s*\}\}",
        str(int(caller_user_id)),
        sql or "",
    )
    if "{{" in prepared or "}}" in prepared:
        return {
            "ok": False,
            "error": "Unknown placeholder. Only {{caller_user_id}} is supported.",
        }

    ok, reason = validate_sql(prepared)
    if not ok:
        return {
            "ok": False,
            "error": reason,
            "hint": "Call database_schema first, then write a SELECT/WITH query.",
        }

    with read_connection() as conn:
        user = _user(conn, caller_user_id)
        if not user:
            return {"ok": False, "error": "Caller account was not found."}
        if str(user.get("status") or "") != "active":
            return {"ok": False, "error": "Caller account is not active."}
        if str(user.get("role") or "") != "admin":
            return {
                "ok": False,
                "error": "Custom database queries require an administrator account.",
                "hint": "Use database_account_summary for your own account information.",
            }

        statement = prepared.strip().rstrip(";").strip()
        wrapped = f"SELECT * FROM ({statement}) AS vira_query LIMIT {limit + 1}"
        started = time.perf_counter()
        try:
            cursor = conn.execute(wrapped)
            columns = [item[0] for item in (cursor.description or [])]
            fetched = cursor.fetchmany(limit + 1)
            truncated = len(fetched) > limit
            fetched = fetched[:limit]
            rows = []
            size = 0
            for row in fetched:
                if isinstance(row, dict):
                    values = [_serialize(row.get(name)) for name in columns]
                else:
                    values = [_serialize(value) for value in row]
                row_size = len(json.dumps(values, ensure_ascii=False, default=str))
                if rows and size + row_size > 12000:
                    truncated = True
                    break
                rows.append(values)
                size += row_size
            return {
                "ok": True,
                "sql": statement,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "limit": limit,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "scope": {"caller_user_id": caller_user_id, "caller": user.get("username")},
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "Check column/table names with database_schema and try again.",
            }


# --------------------------------------------------------------------------- #
# account summary
# --------------------------------------------------------------------------- #
def account_summary(caller_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Safe aggregate summary of the signed-in user's own account."""
    if caller_user_id is None:
        return {"ok": False, "error": "A caller identity is required."}
    with read_connection() as conn:
        user = _user(conn, caller_user_id)
        if not user:
            return {"ok": False, "error": "Caller account was not found."}
        summary: Dict[str, Any] = {
            "ok": True,
            "account": {
                "username": user.get("username"),
                "role": user.get("role"),
                "status": user.get("status"),
            },
        }

        def scalar(sql: str, params: Sequence[Any] = ()) -> int:
            try:
                row = conn.execute(sql, params).fetchone()
                if row is None:
                    return 0
                return int(row[0] if not isinstance(row, dict) else next(iter(row.values())))
            except Exception:
                return 0

        def group(sql: str, params: Sequence[Any] = ()) -> Dict[str, int]:
            try:
                rows = conn.execute(sql, params).fetchall()
                result: Dict[str, int] = {}
                for row in rows:
                    if isinstance(row, dict):
                        key = row.get("k", "")
                        value = row.get("c", 0)
                    else:
                        key, value = row[0], row[1]
                    result[str(key)] = int(value)
                return result
            except Exception:
                return {}

        # Prefer explicit grants; fall back to devices created by the user.
        devices_by_status = group(
            "SELECT d.status AS k, COUNT(DISTINCT d.id) AS c FROM devices d "
            "JOIN user_device_access a ON a.device_id = d.id "
            "WHERE a.user_id = ? AND a.status = 'active' GROUP BY d.status",
            (caller_user_id,),
        )
        if not devices_by_status:
            devices_by_status = group(
                "SELECT status AS k, COUNT(*) AS c FROM devices "
                "WHERE created_by_user_id = ? GROUP BY status",
                (caller_user_id,),
            )

        summary["devices"] = {
            "by_status": devices_by_status,
            "total": sum(devices_by_status.values()),
            "active": devices_by_status.get("active", 0),
            "queued_events": scalar(
                "SELECT COALESCE(SUM(d.queue_backlog), 0) FROM devices d "
                "JOIN user_device_access a ON a.device_id = d.id "
                "WHERE a.user_id = ? AND a.status = 'active'",
                (caller_user_id,),
            ),
        }
        summary["chat"] = {
            "conversations": scalar(
                "SELECT COUNT(*) FROM conversations WHERE user_id = ?",
                (caller_user_id,),
            ),
            "messages": scalar(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?",
                (caller_user_id,),
            ),
            "memories": scalar(
                "SELECT COUNT(*) FROM memories WHERE user_id = ?",
                (caller_user_id,),
            ),
        }
        summary["sessions"] = {
            "active": scalar(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ? "
                "AND revoked_at IS NULL AND expires_at > ?",
                (caller_user_id, datetime.now(timezone.utc).isoformat()),
            )
        }
        summary["notifications"] = {
            "unread": scalar(
                "SELECT COUNT(*) FROM user_notifications "
                "WHERE user_id = ? AND read_at IS NULL",
                (caller_user_id,),
            )
        }
        return summary


# --------------------------------------------------------------------------- #
# JSON helper used by the MCP layer
# --------------------------------------------------------------------------- #
def as_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=_serialize)


def safe_identifier_list(values: Iterable[str]) -> List[str]:
    return sorted({str(value) for value in values})
