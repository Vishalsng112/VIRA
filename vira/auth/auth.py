import bcrypt
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from . import database


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    roles: tuple[str, ...]
    session_id: str

    def has_role(self, role: str) -> bool:
        return role in self.roles


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_recovery_code(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_recovery_code(code: str) -> str:
    return hash_password(code)


def verify_recovery_code(code: str, code_hash: str) -> bool:
    return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))


def admin_exists() -> bool:
    return database.count_users() > 0


def create_admin(username: str, password: str) -> str:
    if admin_exists():
        raise RuntimeError("Admin already exists")
    recovery_code = generate_recovery_code()
    database.create_user(username.strip(), hash_password(password), hash_recovery_code(recovery_code))
    return recovery_code


def authenticate_user_record(username: str, password: str) -> Optional[dict]:
    user = database.get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user


def authenticate_user(username: str, password: str) -> bool:
    return authenticate_user_record(username, password) is not None


def create_authenticated_session(user: dict, max_age: int) -> str:
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age)
    database.create_session(session_id, int(user["id"]), expires_at.isoformat())
    return session_id


def resolve_principal(session_id: Optional[str]) -> Optional[Principal]:
    if not session_id:
        return None
    session = database.get_session(session_id)
    if not session or session["revoked_at"]:
        return None
    try:
        expires_at = datetime.fromisoformat(session["expires_at"])
    except (TypeError, ValueError):
        database.revoke_session(session_id)
        database.record_auth_audit(
            "session_invalid",
            "authenticate",
            False,
            user_id=session["user_id"],
            session_id=session_id,
            details="Invalid session expiry timestamp",
        )
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        database.revoke_session(session_id)
        database.record_auth_audit(
            "session_expired",
            "authenticate",
            False,
            user_id=session["user_id"],
            session_id=session_id,
        )
        return None
    database.touch_session(session_id)
    return Principal(
        user_id=int(session["user_id"]),
        username=session["username"],
        roles=(session["role"],),
        session_id=session_id,
    )


def revoke_session(session_id: str, user_id: Optional[int] = None) -> None:
    database.revoke_session(session_id)
    database.record_auth_audit(
        "logout",
        "session.revoke",
        True,
        user_id=user_id,
        session_id=session_id,
    )


def reset_password(username: str, recovery_code: str, new_password: str) -> bool:
    user = database.get_user_by_username(username)
    if not user or not verify_recovery_code(recovery_code, user["recovery_code_hash"]):
        if user:
            database.record_auth_audit(
                "password_reset",
                "password.reset",
                False,
                user_id=int(user["id"]),
            )
        return False
    database.update_password(username, hash_password(new_password))
    database.revoke_user_sessions(int(user["id"]))
    database.record_auth_audit(
        "password_reset",
        "password.reset",
        True,
        user_id=int(user["id"]),
    )
    return True


def get_admin_username() -> Optional[str]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT username FROM users ORDER BY id LIMIT 1").fetchone()
        return row["username"] if row else None


def update_recovery_code(username: str, new_hash: str) -> None:
    with database.get_connection() as conn:
        conn.execute("UPDATE users SET recovery_code_hash = ? WHERE username = ?", (new_hash, username))
        conn.commit()
