"""In-memory knowledge backend.

It exists for two reasons:

1. Conformance tests run the exact same contract against two very different
   implementations, proving that ``service``/tools do not depend on SQL.
2. It is a usable ephemeral backend for evaluations and local experiments.

It is not durable and not transactional.  Scope isolation is implemented in
Python but follows the same rules as the SQL adapter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from vira.memory.embeddings import cosine_any, get_embedding_provider
from vira.rag.service import chunk_text

from .. import ranking
from ..cache import InProcessTtlCache
from ..models import READABLE_STATUSES, KnowledgeItem, KnowledgeStatus
from ..policy import scope_pairs, validate_scopes
from ..ports import Capabilities, KnowledgeCache, KnowledgeQuery
from ..store import BaseKnowledgeStore, _now
from .. import events


class MemoryKnowledgeStore(BaseKnowledgeStore):
    capabilities = Capabilities(durable=False, transactions=False, ann=False,
                                read_your_writes=True)

    def __init__(self, embedder=None, cache: Optional[KnowledgeCache] = None):
        self._embedder = embedder
        self._items: Dict[str, Dict[str, Any]] = {}
        self._vectors: Dict[str, List[Tuple[str, List[float]]]] = {}
        self._event_log: List[Dict[str, Any]] = []
        self._cache = cache or InProcessTtlCache()

    def _provider(self):
        return self._embedder or get_embedding_provider()

    def _emit(self, event: str, item_id: Optional[str] = None, *,
              actor: Optional[str] = None, agent_role: Optional[str] = None,
              data: Optional[dict] = None) -> None:
        self._event_log.append({"event": event, "item_id": item_id,
                                "actor": actor, "agent_role": agent_role,
                                "data": data or {}})

    # ------------------------------------------------------------------ write
    async def write(self, item: KnowledgeItem, *, actor: Optional[str] = None,
                    dedupe: bool = True, allow_global: bool = False) -> Dict[str, Any]:
        validate_scopes([item.scope])
        if item.scope == "global" and not allow_global:
            raise PermissionError(
                "global knowledge can only be created through promotion")
        item.updated_at = item.created_at = _now()
        if dedupe:
            existing = self._find_duplicate(item.content_hash)
            if existing:
                existing["confidence"] = max(
                    float(existing.get("confidence") or 0), item.confidence)
                existing["importance"] = max(
                    float(existing.get("importance") or 0), item.importance)
                existing["revision"] = int(existing.get("revision") or 1) + 1
                existing["updated_at"] = item.updated_at
                existing["duplicate"] = True
                self._cache.bump()
                self._emit(events.KNOWLEDGE_WRITTEN, existing["id"], actor=actor,
                           agent_role=item.agent_role,
                           data={"duplicate": True, "scope": existing["scope"]})
                return existing

        self._items[item.id] = item.model_dump()
        self._vectors[item.id] = []
        await self._index(item.id, item.content)
        self._cache.bump()
        self._emit(events.KNOWLEDGE_WRITTEN, item.id, actor=actor,
                   agent_role=item.agent_role,
                   data={"scope": item.scope, "scope_id": item.scope_id,
                         "status": item.status})
        return self._items[item.id]

    def _find_duplicate(self, digest: Optional[str]) -> Optional[Dict[str, Any]]:
        if not digest:
            return None
        for item in self._items.values():
            if item.get("content_hash") == digest and item.get("status") != "deprecated":
                return item
        return None

    async def _index(self, item_id: str, content: str) -> None:
        provider = self._provider()
        self._vectors[item_id] = [
            (chunk, await provider.embed(chunk)) for chunk in chunk_text(content)
        ]

    # ----------------------------------------------------------------- search
    async def search(self, query: KnowledgeQuery) -> List[Dict[str, Any]]:
        validate_scopes(query.scopes)
        if not (query.text or "").strip():
            return []
        pairs = scope_pairs(query.scopes, query.user_id, query.agent_role,
                            query.conversation_id, query.organization_id)
        if not pairs:
            return []
        key = f"memory-search:{id(self)}:{self._cache.version()}:{query.text}:{query.limit}:{pairs}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        statuses = list(query.statuses or READABLE_STATUSES)
        kinds = set(query.kinds) if query.kinds else None
        now = _now()
        candidates = [
            item for item in self._items.values()
            if item.get("status") in statuses
            and (item.get("expires_at") is None or item["expires_at"] > now)
            and (kinds is None or item.get("kind") in kinds)
            and self._visible(item, pairs, query.user_id)
        ]
        if not candidates:
            return []
        query_vector = await self._provider().embed(query.text)
        hits: Dict[str, Tuple[float, str]] = {}
        for item in candidates:
            for chunk, vector in self._vectors.get(item["id"], []):
                score = max(0.0, cosine_any(query_vector, vector))
                previous = hits.get(item["id"])
                if previous is None or score > previous[0]:
                    hits[item["id"]] = (score, chunk)
        ranked = ranking.rank(query.text, candidates, hits, query.normalized_limit())
        if ranked:
            self._cache.set(key, ranked)
        return ranked

    @staticmethod
    def _visible(item: Dict[str, Any], pairs, user_id: Optional[int]) -> bool:
        for scope, scope_id in pairs:
            if item.get("scope") != scope:
                continue
            if scope == "global":
                return True
            if scope == "agent":
                if item.get("scope_id") == scope_id and item.get("user_id") in (user_id, None):
                    return True
                continue
            if item.get("scope_id") == scope_id:
                return True
        return False

    # -------------------------------------------------------------- lifecycle
    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        item = self._items.get(item_id)
        return dict(item) if item else None

    def list_items(self, *, user_id: Optional[int] = None,
                   organization_id: Optional[str] = None,
                   scope: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        items = list(self._items.values())
        if organization_id:
            items = [i for i in items if i.get("organization_id") == organization_id]
        elif user_id is not None:
            items = [i for i in items
                     if i.get("user_id") == user_id or i.get("scope") == "global"]
        if scope:
            items = [i for i in items if i.get("scope") == scope]
        items.sort(key=lambda i: i.get("updated_at") or "", reverse=True)
        return [dict(i) for i in items[: max(1, min(int(limit), 500))]]

    def delete(self, item_id: str, *, user_id: Optional[int] = None) -> bool:
        item = self._items.get(item_id)
        if item is None or (user_id is not None and item.get("user_id") != user_id):
            return False
        self._items.pop(item_id, None)
        self._vectors.pop(item_id, None)
        self._cache.bump()
        return True

    def export_user(self, user_id: int, limit: int = 10000) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._items.values()
                if item.get("user_id") == user_id][:limit]

    def delete_for_user(self, user_id: int) -> int:
        ids = [i for i, item in self._items.items() if item.get("user_id") == user_id]
        for item_id in ids:
            self.delete(item_id)
        return len(ids)

    def _mark_superseded(self, item_id: str, new_id: str) -> bool:
        item = self._items.get(item_id)
        if not item or item.get("status") == "deprecated":
            return False
        item["status"] = "deprecated"
        item["superseded_by"] = new_id
        item["updated_at"] = _now()
        self._cache.bump()
        return True

    def _mark_deprecated(self, item_id: str, *, reason: Optional[str] = None) -> bool:
        item = self._items.get(item_id)
        if not item or item.get("status") == "deprecated":
            return False
        item["status"] = "deprecated"
        item["metadata"] = {**(item.get("metadata") or {}),
                            "deprecation_reason": reason or ""}
        item["updated_at"] = _now()
        self._cache.bump()
        return True
