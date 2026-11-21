"""Scope and permission policy for the knowledge base.

Retrieval is scope-aware, not store-per-agent.  The helpers here are the single
source of truth for which scopes a caller may read or write, and for the
permission strings the security manager uses.

Permission convention (mirrors ``memory.{operation}.{agent_id}``)::

    knowledge.read.{scope}
    knowledge.write.{scope}
    knowledge.promote.{scope}
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from .models import Scope

ALL_SCOPES: Tuple[str, ...] = tuple(scope.value for scope in Scope)

# Scopes a normal agent may create directly.  ``global`` is only reachable
# through the promotion pipeline (promote/consolidation), never a direct write.
WRITABLE_SCOPES: Tuple[str, ...] = (
    Scope.CONVERSATION.value,
    Scope.PERSONAL.value,
    Scope.AGENT.value,
    Scope.ORG.value,
)

# More specific scopes win when merging equally relevant results.
SCOPE_PRECEDENCE = {
    Scope.CONVERSATION.value: 1.00,
    Scope.PERSONAL.value: 0.97,
    Scope.AGENT.value: 0.94,
    Scope.ORG.value: 0.91,
    Scope.GLOBAL.value: 0.88,
}

READ_SCOPE_WEIGHT = {
    Scope.GLOBAL.value: 1.00,
    Scope.ORG.value: 0.98,
    Scope.AGENT.value: 0.96,
    Scope.PERSONAL.value: 0.94,
    Scope.CONVERSATION.value: 0.92,
}


def read_action(scope: str) -> str:
    return f"knowledge.read.{scope}"


def write_action(scope: str) -> str:
    return f"knowledge.write.{scope}"


def promote_action(scope: str) -> str:
    return f"knowledge.promote.{scope}"


def default_read_scopes(user_id: Optional[int], agent_role: Optional[str],
                        conversation_id: Optional[str],
                        organization_id: Optional[str]) -> List[Tuple[str, Optional[str]]]:
    """Return ``(scope, scope_id)`` pairs a caller may read by default.

    ``global`` is always readable.  Even without an agent role or
    organization the caller still gets personal/global knowledge.
    """
    pairs: List[Tuple[str, Optional[str]]] = []
    if conversation_id:
        pairs.append((Scope.CONVERSATION.value, conversation_id))
    if user_id is not None:
        pairs.append((Scope.PERSONAL.value, str(user_id)))
    if agent_role and user_id is not None:
        pairs.append((Scope.AGENT.value, agent_role))
    if organization_id:
        pairs.append((Scope.ORG.value, organization_id))
    pairs.append((Scope.GLOBAL.value, None))
    return pairs


def resolve_write_scope(requested: Optional[str], *, requested_by_user: bool,
                        agent_role: Optional[str],
                        conversation_id: Optional[str]) -> str:
    """Pick the default scope for an agent write.

    A user asking the agent to remember something lands in ``personal``.
    An agent learning something on its own lands in ``agent`` (or
    ``conversation`` when there is no stable role).  Explicit requests are
    validated by the caller against :data:`WRITABLE_SCOPES`.
    """
    if requested:
        if requested not in WRITABLE_SCOPES:
            raise PermissionError(
                f"scope '{requested}' cannot be written directly; "
                "use the promotion pipeline for global knowledge")
        return requested
    if requested_by_user:
        return Scope.PERSONAL.value
    if agent_role:
        return Scope.AGENT.value
    if conversation_id:
        return Scope.CONVERSATION.value
    return Scope.PERSONAL.value


def validate_scopes(scopes: Iterable[str]) -> List[str]:
    unknown = [scope for scope in scopes if scope not in ALL_SCOPES]
    if unknown:
        raise ValueError(f"unknown knowledge scope(s): {', '.join(unknown)}")
    return list(scopes)


def scope_pairs(scopes: Iterable[str], user_id: Optional[int],
                agent_role: Optional[str], conversation_id: Optional[str],
                organization_id: Optional[str]) -> List[Tuple[str, Optional[str]]]:
    """Resolve scope names into ``(scope, scope_id)`` filters.

    Missing identifiers drop the scope instead of widening access.
    """
    pairs: List[Tuple[str, Optional[str]]] = []
    for scope in scopes:
        if scope == Scope.CONVERSATION.value and conversation_id:
            pairs.append((scope, conversation_id))
        elif scope == Scope.PERSONAL.value and user_id is not None:
            pairs.append((scope, str(user_id)))
        elif scope == Scope.AGENT.value and agent_role:
            pairs.append((scope, agent_role))
        elif scope == Scope.ORG.value and organization_id:
            pairs.append((scope, organization_id))
        elif scope == Scope.GLOBAL.value:
            pairs.append((scope, None))
    return pairs


def filter_authorized(scopes: Sequence[str], authorize) -> List[str]:
    """Keep scopes accepted by ``authorize(action)``; ``None`` allows all."""
    if authorize is None:
        return list(scopes)
    return [scope for scope in scopes if authorize(read_action(scope))]
