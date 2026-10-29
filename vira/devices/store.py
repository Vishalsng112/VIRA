"""Persistence adapter for devices, credentials, user-device access and events.

All SQL for the device domain lives here (NFR-MAINT-01).  Functions take an
optional open ``conn`` so services can compose several statements into one
transaction (``database.transaction()``).  Raw credentials are never stored:
only the SHA-256 of a 256-bit random token, which is why an unsalted fast hash
is appropriate (the token is not a human-chosen secret).
"""
import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence

from vira.auth import database

CREDENTIAL_PREFIX = "vdc_"
ACCESS_ROLES = ("owner", "operator", "viewer")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
def new_credential_token() -> str:
    return CREDENTIAL_PREFIX + secrets.token_urlsafe(32)


def hash_credential(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@contextmanager
def _conn(conn: Optional[sqlite3.Connection]) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
    else:
        with database.get_connection() as own:
            yield own


def _device_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    item = dict(row)
    for key in ("capabilities", "capability_status"):
        try:
            item[key] = json.loads(item.get(key) or ("[]" if key == "capabilities" else "{}"))
        except json.JSONDecodeError:
            item[key] = [] if key == "capabilities" else {}
    item["is_server_local"] = bool(item.get("is_server_local"))
    return item


# --------------------------------------------------------------------------- #
# devices
# --------------------------------------------------------------------------- #
def insert_device(
    conn: sqlite3.Connection,
    display_name: str,
    platform: str,
    device_type: str,
    os_version: Optional[str],
    client_version: Optional[str],
    capabilities: Sequence[str],
    status: str = "pending",
    created_by_user_id: Optional[int] = None,
    is_server_local: bool = False,
    device_id: Optional[str] = None,
) -> str:
    device_id = device_id or str(uuid.uuid4())
    now = utc_now()
    conn.execute(
        """
        INSERT INTO devices
            (id, display_name, platform, device_type, os_version, client_version,
             capabilities, status, is_server_local, created_by_user_id,
             created_at, updated_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device_id, display_name, platform, device_type, os_version, client_version,
            json.dumps(list(capabilities)), status, int(is_server_local),
            created_by_user_id, now, now, now if status == "active" else None,
        ),
    )
    return device_id


def get_device(device_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    with _conn(conn) as c:
        return _device_row(c.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone())


def get_server_local_device(conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    with _conn(conn) as c:
        return _device_row(
            c.execute("SELECT * FROM devices WHERE is_server_local = 1").fetchone()
        )


def list_devices_for_user(
    user_id: int, limit: int = 50, after_rowid: int = 0, include_retired: bool = False
) -> List[Dict[str, Any]]:
    """Only devices the user holds an *active* grant on (FR-DEV-03)."""
    clauses = ["a.user_id = ?", "a.status = 'active'", "d.rowid > ?"]
    values: List[Any] = [user_id, after_rowid]
    if not include_retired:
        clauses.append("d.status != 'retired'")
    values.append(min(max(limit, 1), 200))
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT d.*, d.rowid AS _cursor, a.access_role AS access_role "
            "FROM devices d JOIN user_device_access a ON a.device_id = d.id "
            f"WHERE {' AND '.join(clauses)} ORDER BY d.rowid LIMIT ?",
            values,
        ).fetchall()
        result = []
        for row in rows:
            item = _device_row(row)
            result.append(item)
        return result


def list_all_devices(limit: int = 50, after_rowid: int = 0) -> List[Dict[str, Any]]:
    """Fleet listing for administrators (metadata only)."""
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT d.*, d.rowid AS _cursor FROM devices d WHERE d.rowid > ? "
            "ORDER BY d.rowid LIMIT ?",
            (after_rowid, min(max(limit, 1), 200)),
        ).fetchall()
        return [_device_row(r) for r in rows]


def update_device_fields(conn: sqlite3.Connection, device_id: str, **fields: Any) -> None:
    allowed = {
        "display_name", "os_version", "client_version", "capabilities",
        "capability_status", "status", "last_seen_at", "last_event_at",
        "revoked_at", "queue_backlog", "last_accepted_sequence",
    }
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Field not updatable: {key}")
        if key in ("capabilities", "capability_status"):
            value = json.dumps(value)
        sets.append(f"{key} = ?")
        values.append(value)
    sets.append("updated_at = ?")
    values.extend([utc_now(), device_id])
    conn.execute(f"UPDATE devices SET {', '.join(sets)} WHERE id = ?", values)


def bump_ingest_stats(
    conn: sqlite3.Connection,
    device_id: str,
    accepted_any: bool,
    errors: int,
    last_sequence: Optional[int],
) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE devices SET
            last_seen_at = ?,
            last_event_at = CASE WHEN ? THEN ? ELSE last_event_at END,
            ingest_error_count = ingest_error_count + ?,
            last_accepted_sequence = CASE
                WHEN ? IS NOT NULL AND (last_accepted_sequence IS NULL OR ? > last_accepted_sequence)
                THEN ? ELSE last_accepted_sequence END,
            updated_at = ?
        WHERE id = ?
        """,
        (now, int(accepted_any), now, errors, last_sequence, last_sequence, last_sequence, now, device_id),
    )


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
def insert_credential(
    conn: sqlite3.Connection,
    device_id: str,
    token: str,
    scopes: Sequence[str],
    expires_at: Optional[str] = None,
    rotated_from: Optional[str] = None,
) -> str:
    credential_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO device_credentials
            (id, device_id, credential_hash, scopes, created_at, expires_at, rotated_from)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (credential_id, device_id, hash_credential(token), json.dumps(list(scopes)),
         utc_now(), expires_at, rotated_from),
    )
    return credential_id


def find_credential(token: str) -> Optional[Dict[str, Any]]:
    """Resolve a presented token to its credential + device row (or None)."""
    with database.get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.id AS credential_id, c.device_id, c.scopes, c.expires_at,
                   c.revoked_at AS credential_revoked_at,
                   d.status AS device_status, d.is_server_local
            FROM device_credentials c JOIN devices d ON d.id = c.device_id
            WHERE c.credential_hash = ?
            """,
            (hash_credential(token),),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["scopes"] = tuple(json.loads(item["scopes"]))
        item["is_server_local"] = bool(item["is_server_local"])
        return item


def touch_credential(credential_id: str) -> None:
    with database.get_connection() as conn:
        conn.execute(
            "UPDATE device_credentials SET last_used_at = ? WHERE id = ?",
            (utc_now(), credential_id),
        )
        conn.commit()


def revoke_credentials(conn: sqlite3.Connection, device_id: str) -> List[str]:
    """Revoke every live credential of a device; return their ids."""
    now = utc_now()
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM device_credentials WHERE device_id = ? AND revoked_at IS NULL",
        (device_id,),
    )]
    conn.execute(
        "UPDATE device_credentials SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
        (now, device_id),
    )
    return ids


def credential_summary(device_id: str) -> Dict[str, Any]:
    """Credential status for health views; never returns hashes."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT id, created_at, expires_at, last_used_at FROM device_credentials "
            "WHERE device_id = ? AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (device_id,),
        ).fetchone()
        if not row:
            return {"status": "none"}
        return {"status": "active", "credential_id": row["id"], "created_at": row["created_at"],
                "expires_at": row["expires_at"], "last_used_at": row["last_used_at"]}


# --------------------------------------------------------------------------- #
# user-device access
# --------------------------------------------------------------------------- #
def grant_access(
    conn: sqlite3.Connection,
    user_id: int,
    device_id: str,
    role: str,
    granted_by_user_id: Optional[int],
) -> None:
    if role not in ACCESS_ROLES:
        raise ValueError(f"Invalid access role: {role}")
    now = utc_now()
    conn.execute(
        """
        INSERT INTO user_device_access
            (user_id, device_id, access_role, status, granted_at, granted_by_user_id, revoked_at)
        VALUES (?, ?, ?, 'active', ?, ?, NULL)
        ON CONFLICT(user_id, device_id) DO UPDATE SET
            access_role = excluded.access_role, status = 'active',
            granted_at = excluded.granted_at,
            granted_by_user_id = excluded.granted_by_user_id, revoked_at = NULL
        """,
        (user_id, device_id, role, now, granted_by_user_id),
    )


def revoke_access(conn: sqlite3.Connection, user_id: int, device_id: str) -> bool:
    cur = conn.execute(
        "UPDATE user_device_access SET status = 'revoked', revoked_at = ? "
        "WHERE user_id = ? AND device_id = ? AND status = 'active'",
        (utc_now(), user_id, device_id),
    )
    return cur.rowcount == 1


def get_access(user_id: int, device_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    """Active access role of the user on the device, else None.

    Also requires the user account itself to be active.
    """
    with _conn(conn) as c:
        row = c.execute(
            "SELECT a.access_role FROM user_device_access a JOIN users u ON u.id = a.user_id "
            "WHERE a.user_id = ? AND a.device_id = ? AND a.status = 'active' AND u.status = 'active'",
            (user_id, device_id),
        ).fetchone()
        return row["access_role"] if row else None


def list_access(device_id: str) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT u.public_id AS user_id, u.username, a.access_role, a.status, "
            "a.granted_at, a.revoked_at FROM user_device_access a "
            "JOIN users u ON u.id = a.user_id WHERE a.device_id = ? ORDER BY a.granted_at",
            (device_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_active_owners(conn: sqlite3.Connection, device_id: str, excluding_user: Optional[int] = None) -> int:
    sql = ("SELECT COUNT(*) AS cnt FROM user_device_access a JOIN users u ON u.id = a.user_id "
           "WHERE a.device_id = ? AND a.status = 'active' AND a.access_role = 'owner' "
           "AND u.status = 'active'")
    values: List[Any] = [device_id]
    if excluding_user is not None:
        sql += " AND a.user_id != ?"
        values.append(excluding_user)
    return int(conn.execute(sql, values).fetchone()["cnt"])


def accessible_device_ids(user_id: int) -> Dict[str, str]:
    """{device_id: access_role} for all active grants of an active user."""
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT a.device_id, a.access_role FROM user_device_access a "
            "JOIN users u ON u.id = a.user_id JOIN devices d ON d.id = a.device_id "
            "WHERE a.user_id = ? AND a.status = 'active' AND u.status = 'active' "
            "AND d.status != 'retired'",
            (user_id,),
        ).fetchall()
        return {r["device_id"]: r["access_role"] for r in rows}


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
def get_event(event_id: str, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT event_id, device_id, payload_hash FROM device_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_event(conn: sqlite3.Connection, row: Dict[str, Any]) -> bool:
    """Insert a normalized event; False when the event_id already exists."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO device_events
            (event_id, device_id, actor_user_id, source_component, source_instance_id,
             event_type, event_class, schema_version, device_sequence, occurred_at,
             received_at, correlation_id, causation_id, payload, payload_hash, expires_at)
        VALUES (:event_id, :device_id, :actor_user_id, :source_component, :source_instance_id,
                :event_type, :event_class, :schema_version, :device_sequence, :occurred_at,
                :received_at, :correlation_id, :causation_id, :payload, :payload_hash, :expires_at)
        """,
        row,
    )
    return cur.rowcount == 1


def upsert_latest_state(conn: sqlite3.Connection, device_id: str, event_type: str, event_id: str,
                        occurred_at: str, received_at: str, payload_json: str) -> None:
    conn.execute(
        """
        INSERT INTO device_latest_state
            (device_id, event_type, event_id, occurred_at, received_at, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, event_type) DO UPDATE SET
            event_id = excluded.event_id, occurred_at = excluded.occurred_at,
            received_at = excluded.received_at, payload = excluded.payload
        WHERE excluded.occurred_at >= device_latest_state.occurred_at
        """,
        (device_id, event_type, event_id, occurred_at, received_at, payload_json),
    )


def get_latest_state(device_id: str) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT event_type, event_id, occurred_at, received_at, payload "
            "FROM device_latest_state WHERE device_id = ? ORDER BY event_type",
            (device_id,),
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["payload"] = json.loads(item["payload"])
            result.append(item)
        return result


def list_events(
    device_id: str,
    limit: int = 50,
    before_rowid: Optional[int] = None,
    event_type: Optional[str] = None,
    include_payload: bool = False,
) -> List[Dict[str, Any]]:
    clauses, values = ["device_id = ?"], [device_id]
    if before_rowid:
        clauses.append("rowid < ?")
        values.append(before_rowid)
    if event_type:
        clauses.append("event_type = ?")
        values.append(event_type)
    values.append(min(max(limit, 1), 200))
    columns = (
        "rowid AS _cursor, event_id, device_id, actor_user_id, source_component, "
        "source_instance_id, event_type, event_class, schema_version, device_sequence, "
        "occurred_at, received_at, correlation_id, causation_id, payload_hash"
        + (", payload" if include_payload else "")
    )
    with database.get_connection() as conn:
        rows = conn.execute(
            f"SELECT {columns} FROM device_events WHERE {' AND '.join(clauses)} "
            "ORDER BY rowid DESC LIMIT ?",
            values,
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            if include_payload and item.get("payload") is not None:
                item["payload"] = json.loads(item["payload"])
            result.append(item)
        return result


def purge_expired(now: Optional[str] = None) -> int:
    now = now or utc_now()
    with database.get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM device_events WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
        )
        conn.commit()
        return cur.rowcount


def health_summary() -> Dict[str, Any]:
    """Fleet counts and per-device health; metadata only (FR-EVT-10)."""
    with database.get_connection() as conn:
        by_status = {
            r["status"]: int(r["cnt"])
            for r in conn.execute("SELECT status, COUNT(*) AS cnt FROM devices GROUP BY status")
        }
        rows = conn.execute(
            "SELECT id, display_name, platform, device_type, status, is_server_local, "
            "client_version, last_seen_at, last_event_at, ingest_error_count, "
            "last_accepted_sequence, queue_backlog FROM devices WHERE status != 'retired' "
            "ORDER BY created_at"
        ).fetchall()
        devices = []
        for r in rows:
            item = dict(r)
            item["is_server_local"] = bool(item["is_server_local"])
            devices.append(item)
        return {"by_status": by_status, "devices": devices}


def enqueue_outbox(conn: sqlite3.Connection, envelope: Dict[str, Any]) -> None:
    """Write the outbox row in the caller's transaction (FR-EVT-07).

    ``envelope`` uses the ``Event.dict()`` key names so ``OutboxPublisher`` can
    rebuild the in-process event after a restart.
    """
    now = utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO outbox_events
            (id, event_type, event_kind, payload, source, correlation_id,
             causation_id, available_at, created_at, device_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            envelope["event_id"], envelope["type"], envelope["kind"],
            json.dumps(envelope, default=str), envelope["source"],
            envelope["correlation_id"], envelope.get("causation_id"), now, now,
            envelope.get("device_id"),
        ),
    )
