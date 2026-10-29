"""Explicit, versioned schema migrations (VIRA multi-device design, section 6.3).

``database.init_db`` still creates the legacy baseline tables with
``CREATE TABLE IF NOT EXISTS``.  Everything introduced by the multi-user /
multi-device design is applied here, exactly once, and recorded in
``schema_migrations``.  The module is stdlib-only and independent of
``database`` so it can be unit-tested against any sqlite3 connection.
"""
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Set, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if _table_exists(conn, table) and column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


# --------------------------------------------------------------------------- #
# 001 - users: public_id, lifecycle status
# --------------------------------------------------------------------------- #
def _m001_users(conn: sqlite3.Connection) -> None:
    _add_column(conn, "users", "public_id", "TEXT")
    _add_column(conn, "users", "status", "TEXT NOT NULL DEFAULT 'active'")
    _add_column(conn, "users", "deleted_at", "TIMESTAMP")
    _add_column(conn, "users", "updated_at", "TIMESTAMP")
    rows = conn.execute("SELECT id FROM users WHERE public_id IS NULL").fetchall()
    for row in rows:
        conn.execute("UPDATE users SET public_id = ? WHERE id = ?", (str(uuid.uuid4()), row[0]))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_public_id_uq ON users(public_id)")


# --------------------------------------------------------------------------- #
# 002 - devices, credentials, user-device access, event provenance
# --------------------------------------------------------------------------- #
def _m002_devices(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            device_type TEXT NOT NULL,
            os_version TEXT,
            client_version TEXT,
            capabilities TEXT NOT NULL DEFAULT '[]',
            capability_status TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'revoked', 'retired')),
            is_server_local INTEGER NOT NULL DEFAULT 0,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            last_seen_at TIMESTAMP,
            last_event_at TIMESTAMP,
            revoked_at TIMESTAMP,
            ingest_error_count INTEGER NOT NULL DEFAULT 0,
            last_accepted_sequence INTEGER,
            queue_backlog INTEGER
        )
        """
    )
    # At most one device represents the VIRA server installation itself.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS devices_server_local_uq "
        "ON devices(is_server_local) WHERE is_server_local = 1"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS devices_by_status ON devices(status, created_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_credentials (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            credential_hash TEXT NOT NULL,
            scopes TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP,
            revoked_at TIMESTAMP,
            last_used_at TIMESTAMP,
            rotated_from TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS devices_credentials_hash_uq "
        "ON device_credentials(credential_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_credentials_by_device "
        "ON device_credentials(device_id, revoked_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_device_access (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            access_role TEXT NOT NULL CHECK (access_role IN ('owner', 'operator', 'viewer')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
            granted_at TIMESTAMP NOT NULL,
            granted_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            revoked_at TIMESTAMP,
            PRIMARY KEY (user_id, device_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS user_device_access_by_user "
        "ON user_device_access(user_id, status, device_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS user_device_access_by_device "
        "ON user_device_access(device_id, status, user_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_events (
            event_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            source_component TEXT NOT NULL,
            source_instance_id TEXT,
            event_type TEXT NOT NULL,
            event_class TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            device_sequence INTEGER,
            occurred_at TIMESTAMP NOT NULL,
            received_at TIMESTAMP NOT NULL,
            correlation_id TEXT NOT NULL,
            causation_id TEXT,
            payload TEXT,
            payload_hash TEXT NOT NULL,
            expires_at TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_device_time "
        "ON device_events(device_id, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_actor_time "
        "ON device_events(actor_user_id, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_type_time "
        "ON device_events(event_type, received_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS device_events_by_expiry ON device_events(expires_at)"
    )
    # Latest snapshot per device/event type: lets high-volume telemetry be
    # queried without keeping every raw payload (FR-EVT-09).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_latest_state (
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            event_id TEXT NOT NULL,
            occurred_at TIMESTAMP NOT NULL,
            received_at TIMESTAMP NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (device_id, event_type)
        )
        """
    )


# --------------------------------------------------------------------------- #
# 003 - provenance columns on existing tables
# --------------------------------------------------------------------------- #
def _m003_provenance_columns(conn: sqlite3.Connection) -> None:
    _add_column(conn, "messages", "created_by_device_id", "TEXT REFERENCES devices(id) ON DELETE SET NULL")
    _add_column(conn, "incognito_messages", "created_by_device_id", "TEXT")
    _add_column(conn, "memories", "device_id", "TEXT")
    _add_column(conn, "outbox_events", "device_id", "TEXT")
    _add_column(conn, "auth_audit", "actor_type", "TEXT NOT NULL DEFAULT 'user'")
    _add_column(conn, "auth_audit", "target", "TEXT")
    _add_column(conn, "auth_audit", "device_id", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON auth_audit(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_device ON memories(device_id)")


MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "users_public_id_and_status", _m001_users),
    (2, "devices_credentials_access_events", _m002_devices),
    (3, "provenance_columns", _m003_provenance_columns),
]


def apply_migrations(conn: sqlite3.Connection) -> List[int]:
    """Apply pending migrations in order; return the versions applied."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP NOT NULL
        )
        """
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied: List[int] = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, _utc_now()),
        )
        conn.commit()
        applied.append(version)
    return applied
