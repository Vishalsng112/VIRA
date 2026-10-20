import hashlib
import shutil
import sqlite3
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
