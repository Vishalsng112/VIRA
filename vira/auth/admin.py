"""Administrator-managed user lifecycle (FR-ID-02, FR-ID-03, FR-ID-07).

Pure application service: no HTTP types.  Every operation is audited with the
acting administrator, the target user's public id and the correlation id.
Raw passwords and recovery codes are returned once to the caller and are never
written to logs or audit rows.
"""
import re
import secrets
from typing import Any, Dict, Optional

from vira import errors
from . import auth, database
from .principals import VALID_ROLES, UserPrincipal

MIN_PASSWORD_LENGTH = 8
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
VALID_STATUSES = ("active", "disabled")


def _public_view(user: Dict[str, Any]) -> Dict[str, Any]:
    """Account metadata safe to return to an administrator (no secrets)."""
    return {
        "user_id": user["public_id"],
        "username": user["username"],
        "role": user["role"],
        "status": user["status"],
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
        "deleted_at": user.get("deleted_at"),
    }


def _require_admin(actor: UserPrincipal) -> None:
    if not actor.is_admin:
        raise errors.Forbidden("Administrator role required")


def _audit(actor: UserPrincipal, action: str, allowed: bool, target: Optional[str],
           correlation_id: Optional[str], details: Optional[str] = None) -> None:
    database.record_auth_audit(
        "admin", action, allowed, user_id=actor.user_id, session_id=actor.session_id,
        resource=f"user:{target}" if target else None, target=target,
        correlation_id=correlation_id, details=details,
    )


def _load(public_id: str) -> Dict[str, Any]:
    user = database.get_user_by_public_id(public_id)
    if not user:
        raise errors.NotFound("User not found")
    return user


class UserAdminService:
    def create_user(
        self,
        actor: UserPrincipal,
        username: str,
        role: str = "user",
        password: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        _require_admin(actor)
        username = (username or "").strip()
        if not _USERNAME_RE.match(username):
            raise errors.ValidationFailed(
                "Username must be 3-64 characters: letters, digits, '_', '.', '@', '-'"
            )
        if role not in VALID_ROLES:
            raise errors.ValidationFailed(f"Role must be one of {list(VALID_ROLES)}")
        temp_password_issued = password is None
        if password is None:
            password = secrets.token_urlsafe(12)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise errors.ValidationFailed(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        if database.get_user_by_username(username):
            _audit(actor, "user.create", False, None, correlation_id, "username exists")
            raise errors.Conflict("Username already exists", code="username_taken")
        recovery_code = auth.generate_recovery_code()
        try:
            user_id = database.create_user(
                username, auth.hash_password(password), auth.hash_recovery_code(recovery_code),
                role=role, status="active",
            )
        except Exception as exc:  # unique-constraint race
            if "UNIQUE" in str(exc).upper():
                raise errors.Conflict("Username already exists", code="username_taken") from exc
            raise
        user = database.get_user_by_id(user_id)
        _audit(actor, "user.create", True, user["public_id"], correlation_id, f"role={role}")
        result = _public_view(user)
        # Credentials are shown exactly once.
        result["recovery_code"] = recovery_code
        if temp_password_issued:
            result["temporary_password"] = password
        return result

    def list_users(self, actor: UserPrincipal, limit: int = 50, cursor: Optional[str] = None,
                   include_deleted: bool = False) -> Dict[str, Any]:
        _require_admin(actor)
        after_id = 0
        if cursor:
            try:
                after_id = int(cursor)
            except ValueError:
                raise errors.BadRequest("Invalid cursor", code="invalid_cursor")
        limit = min(max(limit, 1), 200)
        rows = database.list_users(limit + 1, after_id, include_deleted)
        page = rows[:limit]
        next_cursor = str(page[-1]["id"]) if len(rows) > limit and page else None
        return {"users": [_public_view(r) for r in page], "next_cursor": next_cursor}

    def get_user(self, actor: UserPrincipal, public_id: str) -> Dict[str, Any]:
        _require_admin(actor)
        return _public_view(_load(public_id))

    def update_user(
        self,
        actor: UserPrincipal,
        public_id: str,
        role: Optional[str] = None,
        status: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        _require_admin(actor)
        if role is None and status is None:
            raise errors.ValidationFailed("Nothing to update")
        if role is not None and role not in VALID_ROLES:
            raise errors.ValidationFailed(f"Role must be one of {list(VALID_ROLES)}")
        if status is not None and status not in VALID_STATUSES:
            raise errors.ValidationFailed(f"Status must be one of {list(VALID_STATUSES)}")
        user = _load(public_id)
        if user["status"] == "deleted":
            raise errors.Conflict("User is deleted", code="user_deleted")
        try:
            updated = database.change_user_state(int(user["id"]), role=role, status=status)
        except database.LastAdminError as exc:
            _audit(actor, "user.update", False, public_id, correlation_id, "last admin")
            raise errors.Conflict(str(exc), code="last_admin") from exc
        _audit(actor, "user.update", True, public_id, correlation_id,
               f"role={role or '-'} status={status or '-'}")
        return _public_view(updated)

    def delete_user(self, actor: UserPrincipal, public_id: str,
                    correlation_id: Optional[str] = None) -> None:
        """Soft-delete (tombstone). Conversations/memories are retained until an
        explicit retention workflow runs; sessions and device grants are revoked."""
        _require_admin(actor)
        user = _load(public_id)
        if user["status"] == "deleted":
            return
        try:
            database.change_user_state(int(user["id"]), status="deleted")
        except database.LastAdminError as exc:
            _audit(actor, "user.delete", False, public_id, correlation_id, "last admin")
            raise errors.Conflict(str(exc), code="last_admin") from exc
        _audit(actor, "user.delete", True, public_id, correlation_id)
