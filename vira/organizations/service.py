"""Organizations, membership and role checks.

Roles: ``owner`` > ``admin`` > ``member``.  A user always sees their personal
resources plus resources in organizations they belong to.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira import errors
from vira.auth import database

ROLES = ("owner", "admin", "member")
_RANK = {"owner": 3, "admin": 2, "member": 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "team"
    return f"{base[:48]}-{uuid.uuid4().hex[:6]}"


def _decode_org(row) -> Dict[str, Any]:
    item = dict(row)
    return item


def create(owner_user_id: int, name: str) -> Dict[str, Any]:
    name = " ".join((name or "").split())
    if not name or len(name) > 120:
        raise errors.ValidationFailed("organization name must be 1-120 characters")
    org_id = str(uuid.uuid4())
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO organizations (id, name, slug, owner_user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (org_id, name, _slug(name), owner_user_id, now, now),
        )
        conn.execute(
            "INSERT INTO organization_members (organization_id, user_id, role, created_at) "
            "VALUES (?, ?, 'owner', ?)",
            (org_id, owner_user_id, now),
        )
    return get(org_id)


def get(org_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if not row:
            return None
        members = conn.execute(
            "SELECT m.user_id, m.role, m.created_at, u.username, u.public_id "
            "FROM organization_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.organization_id = ? ORDER BY m.created_at",
            (org_id,),
        ).fetchall()
    item = _decode_org(row)
    item["members"] = [dict(member) for member in members]
    return item


def list_for_user(user_id: int) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT o.*, m.role AS my_role, "
            "(SELECT COUNT(*) FROM organization_members x WHERE x.organization_id = o.id) AS member_count "
            "FROM organizations o JOIN organization_members m ON m.organization_id = o.id "
            "WHERE m.user_id = ? ORDER BY o.created_at",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def role_of(org_id: str, user_id: int) -> Optional[str]:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT role FROM organization_members WHERE organization_id = ? AND user_id = ?",
            (org_id, user_id),
        ).fetchone()
    return row["role"] if row else None


def is_member(org_id: str, user_id: int) -> bool:
    return role_of(org_id, user_id) is not None


def require_member(org_id: Optional[str], user_id: int) -> Optional[Dict[str, Any]]:
    """Validate an optional organization scope and return the organization."""
    if not org_id:
        return None
    org = get(org_id)
    if org is None or not is_member(org_id, user_id):
        raise errors.NotFound("Organization not found")
    return org


def _require(org_id: str, user_id: int, minimum: str) -> str:
    role = role_of(org_id, user_id)
    if role is None:
        raise errors.NotFound("Organization not found")
    if _RANK.get(role, 0) < _RANK[minimum]:
        raise errors.Forbidden("Insufficient organization role")
    return role


def update(org_id: str, user_id: int, name: str) -> Dict[str, Any]:
    _require(org_id, user_id, "admin")
    name = " ".join((name or "").split())
    if not name:
        raise errors.ValidationFailed("organization name is required")
    with database.transaction() as conn:
        conn.execute(
            "UPDATE organizations SET name = ?, updated_at = ? WHERE id = ?",
            (name, _now(), org_id),
        )
    return get(org_id)


def delete(org_id: str, user_id: int) -> bool:
    _require(org_id, user_id, "owner")
    with database.transaction() as conn:
        cur = conn.execute("DELETE FROM organizations WHERE id = ?", (org_id,))
        return bool(cur.rowcount)


def add_member(org_id: str, actor_id: int, target_user_id: int,
               role: str = "member") -> Dict[str, Any]:
    _require(org_id, actor_id, "admin")
    if role not in ROLES:
        raise errors.ValidationFailed("invalid organization role")
    if role == "owner":
        raise errors.ValidationFailed("ownership transfer is not supported")
    if database.get_user_by_id(target_user_id) is None:
        raise errors.NotFound("User not found")
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO organization_members (organization_id, user_id, role, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(organization_id, user_id) DO UPDATE SET role = excluded.role",
            (org_id, target_user_id, role, _now()),
        )
    return get(org_id)


def remove_member(org_id: str, actor_id: int, target_user_id: int) -> bool:
    actor_role = _require(org_id, actor_id, "admin")
    target_role = role_of(org_id, target_user_id)
    if target_role is None:
        return False
    if target_role == "owner":
        raise errors.ValidationFailed("cannot remove the organization owner")
    if actor_id == target_user_id and actor_role != "owner":
        raise errors.Forbidden("ask an owner or admin to remove you")
    with database.transaction() as conn:
        conn.execute(
            "DELETE FROM organization_members WHERE organization_id = ? AND user_id = ?",
            (org_id, target_user_id),
        )
    return True


def update_member(org_id: str, actor_id: int, target_user_id: int, role: str) -> Dict[str, Any]:
    _require(org_id, actor_id, "admin")
    if role not in ROLES or role == "owner":
        raise errors.ValidationFailed("invalid organization role")
    if role_of(org_id, target_user_id) is None:
        raise errors.NotFound("Member not found")
    with database.transaction() as conn:
        conn.execute(
            "UPDATE organization_members SET role = ? WHERE organization_id = ? AND user_id = ?",
            (role, org_id, target_user_id),
        )
    return get(org_id)
