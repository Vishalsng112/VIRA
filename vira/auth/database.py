import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

DEFAULT_DB_PATH = Path("data/vira.sqlite3")
LEGACY_DB_PATH = Path("data/vira.db")
DB_PATH = DEFAULT_DB_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def init_db() -> None:
    """Create and migrate the local identity database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH == DEFAULT_DB_PATH and LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        shutil.move(str(LEGACY_DB_PATH), str(DB_PATH))
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        existing_session_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sessions)")
        }
        if "session_id" in existing_session_columns and "session_id_hash" not in existing_session_columns:
            conn.execute("ALTER TABLE sessions RENAME TO sessions_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                recovery_code_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "role" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id_hash TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                last_seen_at TIMESTAMP NOT NULL,
                revoked_at TIMESTAMP
            )
            """
        )
        session_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sessions)")
        }
        if "sessions_legacy" in {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }:
            conn.execute(
                """
                INSERT INTO sessions
                    (session_id_hash, user_id, created_at, expires_at, last_seen_at)
                SELECT lower(hex(randomblob(32))), user_id, created_at,
                       COALESCE(expires_at, ?), COALESCE(created_at, ?)
                FROM sessions_legacy
                """,
                (_utc_now(), _utc_now()),
            )
            conn.execute("DROP TABLE sessions_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                session_id_hash TEXT,
                action TEXT NOT NULL,
                resource TEXT,
                allowed INTEGER NOT NULL,
                correlation_id TEXT,
                details TEXT,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                source TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                causation_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at TIMESTAMP NOT NULL,
                locked_at TIMESTAMP,
                published_at TIMESTAMP,
                last_error TEXT,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbox_pending
            ON outbox_events(status, available_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_consumptions (
                consumer_name TEXT NOT NULL,
                event_id TEXT NOT NULL,
                processed_at TIMESTAMP NOT NULL,
                PRIMARY KEY (consumer_name, event_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_definitions (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                module TEXT NOT NULL,
                class_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                capabilities TEXT NOT NULL,
                subscribed_events TEXT NOT NULL,
                config TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_calls (
                id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                request TEXT NOT NULL,
                result TEXT,
                status TEXT NOT NULL,
                permission_allowed INTEGER NOT NULL,
                permission_action TEXT NOT NULL,
                error TEXT,
                duration_seconds REAL NOT NULL,
                correlation_id TEXT,
                agent_id TEXT,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT 'New conversation',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                correlation_id TEXT,
                run_id TEXT,
                idempotency_key TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL,
                UNIQUE(user_id, idempotency_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id TEXT,
                status TEXT NOT NULL,
                input_message_id TEXT,
                result_message_id TEXT,
                error TEXT,
                correlation_id TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                agent_id TEXT,
                conversation_id TEXT,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                importance REAL NOT NULL DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, sequence_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(user_id, agent_id, conversation_id, created_at)")
        conn.commit()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_user(username: str, password_hash: str, recovery_code_hash: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, recovery_code_hash, role) "
            "VALUES (?, ?, ?, 'admin')",
            (username, password_hash, recovery_code_hash),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_password(username: str, new_hash: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username))
        conn.commit()


def count_users() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        return int(row["cnt"]) if row else 0


def create_session(session_id: str, user_id: int, expires_at: str) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sessions
                (session_id_hash, user_id, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (hash_session_id(session_id), user_id, now, expires_at, now),
        )
        conn.commit()


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT s.*, u.username, u.role
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.session_id_hash = ?
            """,
            (hash_session_id(session_id),),
        ).fetchone()
        return dict(row) if row else None


def touch_session(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE session_id_hash = ?",
            (_utc_now(), hash_session_id(session_id)),
        )
        conn.commit()


def revoke_session(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE session_id_hash = ? AND revoked_at IS NULL",
            (_utc_now(), hash_session_id(session_id)),
        )
        conn.commit()


def revoke_user_sessions(user_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (_utc_now(), user_id),
        )
        conn.commit()


def record_auth_audit(
    event_type: str,
    action: str,
    allowed: bool,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    resource: Optional[str] = None,
    correlation_id: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_audit
                (event_type, user_id, session_id_hash, action, resource, allowed,
                 correlation_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                user_id,
                hash_session_id(session_id) if session_id else None,
                action,
                resource,
                int(allowed),
                correlation_id,
                details,
                _utc_now(),
            ),
        )
        conn.commit()


def enqueue_outbox_event(event: Dict[str, Any]) -> None:
    """Persist a durable event before it is delivered to in-process consumers."""
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO outbox_events
                (id, event_type, event_kind, payload, source, correlation_id,
                 causation_id, available_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["type"],
                event["kind"],
                json.dumps(event, default=str),
                event["source"],
                event["correlation_id"],
                event.get("causation_id"),
                now,
                now,
            ),
        )
        conn.commit()


def claim_outbox_events(limit: int = 100) -> list[Dict[str, Any]]:
    """Claim pending outbox rows for publication."""
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE outbox_events
            SET status = 'pending', locked_at = NULL
            WHERE status = 'processing'
              AND julianday(locked_at) < julianday(?) - (5.0 / 1440.0)
            """,
            (now,),
        )
        rows = conn.execute(
            """
            SELECT * FROM outbox_events
            WHERE status = 'pending' AND available_at <= ?
            ORDER BY created_at
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        events = [dict(row) for row in rows]
        for row in events:
            conn.execute(
                """
                UPDATE outbox_events
                SET status = 'processing', locked_at = ?, attempts = attempts + 1
                WHERE id = ? AND status = 'pending'
                """,
                (now, row["id"]),
            )
        conn.commit()
        return events


def mark_outbox_published(event_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE outbox_events
            SET status = 'published', published_at = ?, locked_at = NULL
            WHERE id = ?
            """,
            (_utc_now(), event_id),
        )
        conn.commit()


def mark_outbox_retry(event_id: str, error: str, retry_at: str, dead_letter: bool = False) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE outbox_events
            SET status = ?, available_at = ?, locked_at = NULL, last_error = ?
            WHERE id = ?
            """,
            ("dead_letter" if dead_letter else "pending", retry_at, error, event_id),
        )
        conn.commit()


def outbox_counts() -> Dict[str, int]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM outbox_events GROUP BY status"
        ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}


def has_event_consumption(consumer_name: str, event_id: str) -> bool:
    with get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM event_consumptions WHERE consumer_name = ? AND event_id = ?",
            (consumer_name, event_id),
        ).fetchone() is not None


def record_event_consumption(consumer_name: str, event_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO event_consumptions
                (consumer_name, event_id, processed_at)
            VALUES (?, ?, ?)
            """,
            (consumer_name, event_id, _utc_now()),
        )
        conn.commit()


def upsert_agent_definition(definition: Dict[str, Any]) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_definitions
                (agent_id, name, version, module, class_name, description,
                 capabilities, subscribed_events, config, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                name=excluded.name, version=excluded.version, module=excluded.module,
                class_name=excluded.class_name, description=excluded.description,
                capabilities=excluded.capabilities, subscribed_events=excluded.subscribed_events,
                config=excluded.config, enabled=excluded.enabled, updated_at=excluded.updated_at
            """,
            (
                definition["agent_id"], definition["name"], definition.get("version", "1.0.0"),
                definition["module"], definition["class_name"], definition.get("description", ""),
                json.dumps(definition.get("capabilities", []), default=str),
                json.dumps(definition.get("subscribed_events", [])),
                json.dumps(definition.get("config", {}), default=str),
                int(definition.get("enabled", True)), now, now,
            ),
        )
        conn.commit()


def set_agent_definition_enabled(agent_id: str, enabled: bool) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE agent_definitions SET enabled = ?, updated_at = ? WHERE agent_id = ?",
            (int(enabled), _utc_now(), agent_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def list_agent_definitions() -> list[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_definitions ORDER BY name"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item["capabilities"])
            item["subscribed_events"] = json.loads(item["subscribed_events"])
            item["config"] = json.loads(item["config"])
            item["enabled"] = bool(item["enabled"])
            result.append(item)
        return result


def delete_agent_definition(agent_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM agent_definitions WHERE agent_id = ?", (agent_id,))
        conn.commit()
        return cursor.rowcount == 1


def record_tool_call(
    tool_name: str,
    request: Dict[str, Any],
    result: Any,
    status: str,
    permission_allowed: bool,
    permission_action: str,
    duration_seconds: float,
    error: Optional[str] = None,
    correlation_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> str:
    call_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO tool_calls
                (id, tool_name, request, result, status, permission_allowed,
                 permission_action, error, duration_seconds, correlation_id,
                 agent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id, tool_name, json.dumps(request, default=str),
                json.dumps(result, default=str) if result is not None else None,
                status, int(permission_allowed), permission_action, error,
                duration_seconds, correlation_id, agent_id, _utc_now(),
            ),
        )
        conn.commit()
    return call_id


def list_tool_calls(limit: int = 100) -> list[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_calls ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def create_conversation(user_id: int, title: str = "New conversation", conversation_id: Optional[str] = None) -> str:
    conversation_id = conversation_id or str(uuid.uuid4())
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, user_id, title, now, now),
        )
        conn.commit()
    return conversation_id


def get_conversation(conversation_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["archived"] = bool(item["archived"])
        return item


def list_conversations(user_id: int, limit: int = 50, offset: int = 0) -> list[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (user_id, min(max(limit, 1), 100), max(offset, 0)),
        ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["archived"] = bool(item["archived"])
        return result


def update_conversation(conversation_id: str, user_id: int, title: Optional[str] = None, archived: Optional[bool] = None) -> bool:
    fields, values = [], []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if archived is not None:
        fields.append("archived = ?")
        values.append(int(archived))
    if not fields:
        return False
    fields.append("updated_at = ?")
    values.extend([_utc_now(), conversation_id, user_id])
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE conversations SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount == 1


def delete_conversation(conversation_id: str, user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def append_message(
    conversation_id: str,
    user_id: int,
    role: str,
    content: Any,
    correlation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    message_id = str(uuid.uuid4())
    now = _utc_now()
    serialized = json.dumps(content, default=str) if not isinstance(content, str) else content
    with get_connection() as conn:
        existing = None
        if idempotency_key:
            existing = conn.execute(
                "SELECT * FROM messages WHERE user_id = ? AND idempotency_key = ?",
                (user_id, idempotency_key),
            ).fetchone()
        if existing:
            return dict(existing)
        owner = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not owner:
            raise ValueError("Conversation not found")
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()["next_sequence"]
        conn.execute(
            """
            INSERT INTO messages
                (id, conversation_id, user_id, role, content, sequence_no,
                 correlation_id, run_id, idempotency_key, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, user_id, role, serialized, sequence,
             correlation_id, run_id, idempotency_key, json.dumps(metadata or {}, default=str), now),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
    return {
        "id": message_id, "conversation_id": conversation_id, "user_id": user_id,
        "role": role, "content": content, "sequence_no": sequence,
        "correlation_id": correlation_id, "run_id": run_id,
        "idempotency_key": idempotency_key, "metadata": metadata or {}, "created_at": now,
    }


def get_message_by_idempotency(user_id: int, idempotency_key: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key),
        ).fetchone()
        return dict(row) if row else None


def list_messages(conversation_id: str, user_id: int, limit: int = 50, offset: int = 0) -> list[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT m.* FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.conversation_id = ? AND c.user_id = ?
            ORDER BY m.sequence_no LIMIT ? OFFSET ?
            """,
            (conversation_id, user_id, min(max(limit, 1), 100), max(offset, 0)),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item["metadata"])
            except json.JSONDecodeError:
                item["metadata"] = {}
            result.append(item)
        return result


def create_run(conversation_id: str, user_id: int, input_message_id: str, agent_id: Optional[str], correlation_id: str) -> str:
    run_id = str(uuid.uuid4())
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_runs
                (id, conversation_id, user_id, agent_id, status, input_message_id, correlation_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (run_id, conversation_id, user_id, agent_id, input_message_id, correlation_id, now, now),
        )
        conn.commit()
    return run_id


def update_run(run_id: str, status: str, result_message_id: Optional[str] = None, error: Optional[str] = None) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE agent_runs SET status = ?, result_message_id = COALESCE(?, result_message_id),
                error = ?, updated_at = ? WHERE id = ?
            """,
            (status, result_message_id, error, _utc_now(), run_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def get_run(run_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE id = ? AND user_id = ?", (run_id, user_id)).fetchone()
        return dict(row) if row else None


def store_memory(
    user_id: Optional[int],
    content: str,
    agent_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    memory_type: str = "long_term",
    metadata: Optional[Dict[str, Any]] = None,
    importance: float = 0.0,
    expires_at: Optional[str] = None,
) -> str:
    memory_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO memories
                (id, user_id, agent_id, conversation_id, memory_type, content,
                 metadata, importance, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, user_id, agent_id, conversation_id, memory_type, content,
             json.dumps(metadata or {}, default=str), importance, expires_at, _utc_now()),
        )
        conn.commit()
    return memory_id


def search_memories(
    user_id: Optional[int],
    query: Optional[str] = None,
    limit: int = 10,
    agent_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    memory_type: Optional[str] = None,
) -> list[Dict[str, Any]]:
    clauses = ["(user_id = ? OR user_id IS NULL)", "(expires_at IS NULL OR expires_at > ?)"]
    values: list[Any] = [user_id, _utc_now()]
    if query:
        clauses.append("content LIKE ?")
        values.append(f"%{query}%")
    if agent_id:
        clauses.append("(agent_id = ? OR agent_id IS NULL)")
        values.append(agent_id)
    if conversation_id:
        clauses.append("(conversation_id = ? OR conversation_id IS NULL)")
        values.append(conversation_id)
    if memory_type:
        clauses.append("memory_type = ?")
        values.append(memory_type)
    values.append(min(max(limit, 1), 100))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            values,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item["metadata"])
            result.append(item)
        return result


def delete_memory(memory_id: str, user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user_id))
        conn.commit()
        return cursor.rowcount == 1


def compact_memories(user_id: Optional[int], before: Optional[str] = None) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM memories
            WHERE (user_id = ? OR user_id IS NULL)
              AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (user_id, before or _utc_now()),
        )
        conn.commit()
        return cursor.rowcount
