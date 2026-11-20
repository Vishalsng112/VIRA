"""Short-lived pairing codes for enrolling a new device without a session."""
import hashlib
import secrets as py_secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from vira.auth import auth, database
from vira.auth.principals import UserPrincipal

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def create_code(user_id: int, ttl_minutes: int = 10) -> Dict[str, Any]:
    code = "".join(py_secrets.choice(_ALPHABET) for _ in range(8))
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=max(1, ttl_minutes))).isoformat()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO device_pairing_codes (code_hash, created_by_user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_hash(code), user_id, now, expires),
        )
    return {"code": code, "expires_at": expires, "ttl_minutes": ttl_minutes}


def redeem(code: str, display_name: str, platform: str, device_type: str,
           os_version: Optional[str] = None, client_version: Optional[str] = None,
           capabilities: Optional[list] = None) -> Dict[str, Any]:
    from vira.devices.service import DeviceService  # avoid import cycle
    now = _now()
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM device_pairing_codes WHERE code_hash = ?",
            (_hash(code),),
        ).fetchone()
        if not row:
            raise ValueError("invalid pairing code")
        if row["used_at"]:
            raise ValueError("pairing code already used")
        if row["expires_at"] <= now:
            raise ValueError("pairing code expired")
        conn.execute(
            "UPDATE device_pairing_codes SET used_at = ? WHERE code_hash = ?",
            (now, row["code_hash"]),
        )
    user = database.get_user_by_id(int(row["created_by_user_id"]))
    if not user or user.get("status") != "active":
        raise ValueError("pairing account is not active")
    principal = UserPrincipal(
        user_id=int(user["id"]), username=user["username"], roles=(user["role"],),
        session_id="pairing", public_id=user["public_id"],
    )
    service = DeviceService()
    created = service.register_device(
        principal, display_name, platform, device_type, os_version,
        client_version, capabilities or [],
    )
    with database.transaction() as conn:
        conn.execute(
            "UPDATE device_pairing_codes SET device_id = ? WHERE code_hash = ?",
            (created["device_id"], row["code_hash"]),
        )
    return created


def purge_expired() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with database.transaction() as conn:
        cur = conn.execute(
            "DELETE FROM device_pairing_codes WHERE expires_at < ? "
            "AND (used_at IS NOT NULL OR expires_at < ?)",
            (cutoff, cutoff),
        )
        return cur.rowcount
