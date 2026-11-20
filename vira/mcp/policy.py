"""Evaluate MCP server allow-list policies for a caller."""
from typing import Any, Dict, Optional, Sequence

from . import store


def _matches(policy: Dict[str, Any], user_id: Optional[int], roles: Sequence[str],
             organization_id: Optional[str]) -> bool:
    subject_type = policy.get("subject_type")
    subject_id = str(policy.get("subject_id") or "")
    if subject_type == "default":
        return subject_id in ("*", "all", "")
    if subject_type == "user":
        return user_id is not None and subject_id == str(user_id)
    if subject_type == "role":
        return subject_id in set(roles)
    if subject_type == "org":
        return organization_id is not None and subject_id == str(organization_id)
    return False


def is_allowed(server: Dict[str, Any], tool_name: str, user_id: Optional[int] = None,
               roles: Sequence[str] = (), organization_id: Optional[str] = None) -> bool:
    """Return whether ``tool_name`` may be called.

    Precedence: explicit user policy > organization > role > default.  If no
    policy applies, the server's own allow/deny lists apply and the default is
    allow (backwards compatible with pre-policy installations).
    """
    server_allowed = set(server.get("allowed_tools") or [])
    server_denied = set(server.get("denied_tools") or [])
    if server_allowed and tool_name not in server_allowed:
        return False
    if tool_name in server_denied:
        return False

    policies = [item for item in store.list_policies(server["id"])
                if _matches(item, user_id, roles, organization_id)]
    if not policies:
        return True
    rank = {"user": 0, "org": 1, "role": 2, "default": 3}
    policies.sort(key=lambda item: rank.get(item.get("subject_type"), 9))
    policy = policies[0]
    if not policy.get("allowed"):
        return False
    allowed = set(policy.get("allowed_tools") or [])
    denied = set(policy.get("denied_tools") or [])
    if tool_name in denied:
        return False
    if allowed and tool_name not in allowed:
        return False
    return True
