"""Facade over the knowledge store, uploaded documents and episodic memory.

Agents should call this module (through the ``knowledge_search`` /
``knowledge_write`` tools) instead of reaching into storage.  Retrieval merges
three independently-owned sources and tags every result with its origin, scope
and status so the model can reason about trust and cite its sources:

* ``knowledge`` - durable, scoped learnings written by agents or promoted.
* ``document``  - user-uploaded RAG documents (``rag_documents``).
* ``memory``    - episodic recall (``memories``).

The facade is intentionally thin: it contains policy and ranking, not an AGI
algorithm.  Consolidation/promotion strategy lives in ``consolidation``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from vira.auth import database
from vira.memory.embeddings import hybrid_score
from vira.rag import service as rag_service

from . import policy
from .models import KnowledgeItem, KnowledgeKind, KnowledgeStatus
from .ports import KnowledgeQuery
from .store import get_store

_ORIGIN_WEIGHT = {"knowledge": 1.0, "document": 0.95, "memory": 0.9}


def _enabled(scopes: Sequence[str], *wanted: str) -> bool:
    return any(scope in scopes for scope in wanted)


async def search(
    query: str,
    *,
    user_id: Optional[int] = None,
    agent_role: Optional[str] = None,
    agent_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    scopes: Optional[Sequence[str]] = None,
    limit: int = 8,
    include_documents: bool = True,
    include_memories: bool = True,
    authorize=None,
) -> List[Dict[str, Any]]:
    """Merge knowledge, documents and memories into one ranked result list."""
    if not (query or "").strip():
        return []
    limit = max(1, min(int(limit), 50))
    if scopes is None:
        scopes = policy.default_read_scopes(
            user_id, agent_role, conversation_id, organization_id)
        scopes = [scope for scope, _ in scopes]
    scopes = policy.filter_authorized(policy.validate_scopes(scopes), authorize)
    if not scopes:
        return []

    results: List[Dict[str, Any]] = []
    store = get_store()

    try:
        knowledge = await store.search(KnowledgeQuery(
            text=query,
            scopes=scopes,
            user_id=user_id,
            agent_role=agent_role,
            conversation_id=conversation_id,
            organization_id=organization_id,
            limit=limit,
        ))
        for item in knowledge:
            item["_origin"] = "knowledge"
            results.append(item)
    except Exception:
        logger.exception("knowledge search failed")

    if include_documents and user_id is not None and _enabled(scopes, "personal", "org"):
        try:
            documents = await rag_service.search(
                user_id, query, limit=limit, organization_id=organization_id)
            for doc in documents:
                results.append({
                    "id": doc.get("document_id"),
                    "kind": "document",
                    "content": doc.get("content", ""),
                    "excerpt": doc.get("content", ""),
                    "summary": None,
                    "title": doc.get("title"),
                    "scope": "org" if organization_id else "personal",
                    "status": "verified",
                    "confidence": 0.7,
                    "importance": 0.0,
                    "source": {"uri": doc.get("source"), "user_id": user_id},
                    "metadata": doc.get("metadata") or {},
                    "score": round(float(doc.get("score") or 0.0)
                                   * _ORIGIN_WEIGHT["document"], 6),
                    "_origin": "document",
                })
        except Exception:
            logger.exception("document search failed")

    if include_memories and user_id is not None and _enabled(
            scopes, "personal", "conversation", "agent"):
        try:
            rows = database.search_memories(
                user_id=user_id, query=None, limit=max(limit * 10, 50),
                agent_id=agent_id, conversation_id=conversation_id)
            for row in rows:
                score = hybrid_score(query, row.get("content", ""))
                if score <= 0:
                    continue
                scope = "conversation" if row.get("conversation_id") else (
                    "agent" if row.get("agent_id") else "personal")
                if scope not in scopes:
                    continue
                results.append({
                    "id": row.get("id"),
                    "kind": "memory",
                    "content": row.get("content", ""),
                    "excerpt": row.get("content", ""),
                    "summary": None,
                    "scope": scope,
                    "status": "verified",
                    "confidence": min(1.0, float(row.get("importance") or 0.3)),
                    "importance": float(row.get("importance") or 0.0),
                    "source": {"agent_id": row.get("agent_id"),
                               "conversation_id": row.get("conversation_id"),
                               "user_id": row.get("user_id")},
                    "metadata": row.get("metadata") or {},
                    "score": round(score * _ORIGIN_WEIGHT["memory"], 6),
                    "_origin": "memory",
                })
        except Exception:
            logger.exception("memory search failed")

    results.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
    return results[:limit]


async def list_items(
    *,
    user_id: Optional[int],
    scopes: Optional[Sequence[str]] = None,
    agent_role: Optional[str] = None,
    conversation_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    limit: int = 200,
    authorize=None,
) -> List[Dict[str, Any]]:
    """List knowledge items visible to a caller, filtered by scope authority."""
    scopes = list(scopes or ["personal", "agent", "global"])
    allowed = policy.filter_authorized(policy.validate_scopes(scopes), authorize)
    if not allowed:
        return []
    limit = max(1, min(int(limit), 500))
    items = get_store().list_items(
        user_id=user_id, organization_id=organization_id, limit=limit)
    result = []
    for item in items:
        scope = item.get("scope")
        if scope not in allowed:
            continue
        if scope == "personal" and str(item.get("user_id")) != str(user_id):
            continue
        if scope == "agent" and item.get("agent_role") != agent_role:
            continue
        if scope == "org" and item.get("organization_id") != organization_id:
            continue
        result.append(item)
    return result[:limit]


async def correct(
    item_id: str,
    content: str,
    *,
    user_id: int,
    summary: Optional[str] = None,
    tags: Optional[List[str]] = None,
    kind: Optional[str] = None,
    agent_role: Optional[str] = None,
    organization_id: Optional[str] = None,
    authorize=None,
) -> Dict[str, Any]:
    """Create a superseding revision of an item the user owns or may write."""
    if not (content or "").strip():
        raise ValueError("content is required")
    store = get_store()
    previous = store.get(item_id)
    if previous is None:
        raise ValueError("knowledge item not found")
    scope = previous.get("scope")
    if scope == "global":
        raise PermissionError("global knowledge is corrected through promotion")
    if previous.get("user_id") is not None and int(previous["user_id"]) != int(user_id):
        raise PermissionError("knowledge item belongs to another user")
    if scope == "org":
        if not organization_id or previous.get("organization_id") != organization_id:
            raise PermissionError("organization scope required")
    if authorize is not None and not authorize(policy.write_action(scope)):
        raise PermissionError(f"not allowed to write {scope} knowledge")
    replacement = KnowledgeItem(
        kind=kind or previous.get("kind") or KnowledgeKind.FACT.value,
        content=content.strip(),
        summary=summary or previous.get("summary"),
        tags=list(tags if tags is not None else (previous.get("tags") or [])),
        confidence=previous.get("confidence") or 0.5,
        importance=previous.get("importance") or 0.0,
        status=KnowledgeStatus.VERIFIED.value,
        metadata={**(previous.get("metadata") or {}), "corrected": True},
        source={**(previous.get("source") or {}), "corrected_from": item_id},
    )
    corrected = await store.supersede(item_id, replacement, actor=agent_role or "user")
    corrected["supersedes"] = item_id
    return corrected


async def write(
    content: str,
    *,
    user_id: Optional[int],
    kind: str = KnowledgeKind.FACT.value,
    scope: Optional[str] = None,
    requested_by_user: bool = False,
    agent_role: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    summary: Optional[str] = None,
    confidence: float = 0.5,
    importance: float = 0.0,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
    expires_at: Optional[str] = None,
    authorize=None,
) -> Dict[str, Any]:
    """Persist one knowledge item, choosing a safe default scope.

    ``requested_by_user=True`` (the user explicitly said "remember this") is
    stored as verified personal knowledge.  Autonomous agent learnings are
    drafts in the agent role's scope until consolidation promotes them.
    """
    if not (content or "").strip():
        raise ValueError("content is required")
    resolved = policy.resolve_write_scope(
        scope, requested_by_user=requested_by_user, agent_role=agent_role,
        conversation_id=conversation_id)
    if authorize is not None and not authorize(policy.write_action(resolved)):
        raise PermissionError(f"not allowed to write {resolved} knowledge")

    scope_id = {
        "personal": str(user_id) if user_id is not None else None,
        "agent": agent_role,
        "org": organization_id,
        "conversation": conversation_id,
    }.get(resolved)
    required = {
        "personal": user_id,
        "agent": agent_role,
        "org": organization_id,
        "conversation": conversation_id,
    }.get(resolved)
    if not required:
        raise ValueError(f"scope '{resolved}' requires its scope identifier")

    if status is None:
        status = (KnowledgeStatus.VERIFIED.value if requested_by_user
                  else KnowledgeStatus.DRAFT.value)
    if resolved == "conversation" and not expires_at:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    item = KnowledgeItem(
        kind=kind,
        content=content.strip(),
        summary=summary,
        scope=resolved,
        scope_id=scope_id,
        user_id=user_id,
        organization_id=organization_id,
        agent_role=agent_role,
        source={
            "agent_id": agent_id,
            "agent_role": agent_role,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "tool": "knowledge_write",
            "requested_by_user": requested_by_user,
        },
        metadata=metadata or {},
        tags=tags or [],
        confidence=confidence if not requested_by_user else max(confidence, 0.8),
        importance=importance,
        status=status,
        expires_at=expires_at,
    )
    return await get_store().write(item, actor=agent_role or "agent")


async def promote(item_id: str, *, target_scope: str = "global",
                  actor: Optional[str] = None,
                  organization_id: Optional[str] = None,
                  force: bool = False) -> Dict[str, Any]:
    """Promote an item into a wider scope, gated by the default policy."""
    from .consolidation import default_promotion_policy

    store = get_store()
    item = store.get(item_id)
    if item is None:
        raise ValueError("knowledge item not found")
    decision = default_promotion_policy.evaluate(item)
    if not decision.allowed and not force:
        raise PermissionError(f"promotion rejected: {decision.reason}")
    return await store.promote(item_id, target_scope=target_scope,
                               actor=actor, organization_id=organization_id)


def revisions(item_id: str) -> List[Dict[str, Any]]:
    return get_store().revisions(item_id)


def deprecate(item_id: str, *, reason: Optional[str] = None,
              actor: Optional[str] = None) -> bool:
    return get_store().deprecate(item_id, reason=reason, actor=actor)
