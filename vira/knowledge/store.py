"""SQLite adapters for the knowledge ports.

The store composes three replaceable pieces:

* ``SqliteKnowledgeRepository`` - authoritative item/revision rows.
* ``SqliteVectorIndex``        - derived chunk embeddings (rebuildable).
* ``KnowledgeCache``           - optional read cache (``cache.NullCache`` by default).

Only this module contains knowledge SQL.  Everything above it works with
``KnowledgeQuery`` and plain dicts, which is what lets a different database take
over through ``factory.create_store``.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from vira.auth import database
from vira.memory.embeddings import cosine_any, get_embedding_provider
from vira.rag.service import chunk_text

from . import events, ranking
from .cache import NullCache
from .models import (
    READABLE_STATUSES,
    KnowledgeItem,
    KnowledgeStatus,
    content_hash as build_content_hash,
    from_row,
)
from .policy import scope_pairs, validate_scopes
from .ports import Capabilities, KnowledgeCache, KnowledgeQuery, KnowledgeRepository, VectorIndex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _placeholders(values: Sequence[Any]) -> str:
    return ", ".join("?" for _ in values)


def _chunks(values: Sequence[Any], size: int = 500) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


class SqliteKnowledgeRepository:
    """Authoritative record store inside the shared VIRA database."""

    capabilities = Capabilities(durable=True, transactions=True)

    def insert(self, item: KnowledgeItem) -> Dict[str, Any]:
        row = item.to_row()
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO knowledge_items (id, user_id, organization_id, scope, scope_id, "
                "agent_role, kind, content, summary, metadata, source, tags, confidence, "
                "importance, status, revision, supersedes, superseded_by, valid_from, "
                "valid_until, expires_at, content_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], row["user_id"], row["organization_id"], row["scope"],
                 row["scope_id"], row["agent_role"], row["kind"], row["content"],
                 row["summary"], row["metadata"], row["source"], row["tags"],
                 row["confidence"], row["importance"], row["status"], row["revision"],
                 row["supersedes"], row["superseded_by"], row["valid_from"],
                 row["valid_until"], row["expires_at"], row["content_hash"],
                 row["created_at"], row["updated_at"]),
            )
        return self.get(item.id) or item.model_dump()

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_items WHERE id = ?", (item_id,)
            ).fetchone()
        return from_row(row) if row else None

    def find_by_hash(self, digest: Optional[str]) -> Optional[Dict[str, Any]]:
        if not digest:
            return None
        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_items WHERE content_hash = ? "
                "AND status != 'deprecated' ORDER BY created_at DESC LIMIT 1",
                (digest,),
            ).fetchone()
        return from_row(row) if row else None

    def bump(self, item_id: str, confidence: float, importance: float) -> Dict[str, Any]:
        existing = self.get(item_id) or {}
        revision = int(existing.get("revision") or 1) + 1
        now = _now()
        with database.transaction() as conn:
            conn.execute(
                "UPDATE knowledge_items SET confidence = ?, importance = ?, "
                "revision = ?, updated_at = ? WHERE id = ?",
                (confidence, importance, revision, now, item_id),
            )
        existing.update({"confidence": confidence, "importance": importance,
                         "revision": revision, "updated_at": now, "duplicate": True})
        return existing

    def candidates(self, pairs: Sequence[Tuple[str, Optional[str]]],
                   statuses: Sequence[str], kinds: Optional[Sequence[str]],
                   limit: int, *, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if not pairs:
            return []
        clauses: List[str] = []
        values: List[Any] = []
        scope_clauses: List[str] = []
        for scope, scope_id in pairs:
            if scope == "global":
                scope_clauses.append("i.scope = 'global'")
            elif scope == "agent":
                scope_clauses.append(
                    "i.scope = 'agent' AND i.scope_id = ? AND "
                    "(i.user_id = ? OR i.user_id IS NULL)")
                values.extend([scope_id, user_id])
            else:
                scope_clauses.append(f"i.scope = '{scope}' AND i.scope_id = ?")
                values.append(scope_id)
        clauses.append("(" + " OR ".join(f"({clause})" for clause in scope_clauses) + ")")
        clauses.append(f"i.status IN ({_placeholders(statuses)})")
        values.extend(statuses)
        clauses.append("(i.expires_at IS NULL OR i.expires_at > ?)")
        values.append(_now())
        if kinds:
            clauses.append(f"i.kind IN ({_placeholders(kinds)})")
            values.extend(kinds)
        values.append(max(1, min(int(limit), 5000)))
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT i.* FROM knowledge_items i "
                f"WHERE {' AND '.join(f'({clause})' for clause in clauses)} "
                "ORDER BY i.updated_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [from_row(row) for row in rows]

    def list_items(self, *, user_id: Optional[int] = None,
                   organization_id: Optional[str] = None,
                   scope: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        clauses, values = [], []
        if organization_id:
            clauses.append("organization_id = ?")
            values.append(organization_id)
        elif user_id is not None:
            clauses.append("(user_id = ? OR scope = 'global')")
            values.append(user_id)
        if scope:
            clauses.append("scope = ?")
            values.append(scope)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        values.append(min(max(int(limit), 1), 500))
        with database.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM knowledge_items {where}"
                "ORDER BY updated_at DESC LIMIT ?", values
            ).fetchall()
        return [from_row(row) for row in rows]

    def set_status(self, item_id: str, status: str, *,
                   superseded_by: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> bool:
        clauses = ["status = ?", "updated_at = ?"]
        values: List[Any] = [status, _now()]
        if superseded_by is not None:
            clauses.append("superseded_by = ?")
            values.append(superseded_by)
        if metadata is not None:
            clauses.append("metadata = ?")
            values.append(json.dumps(metadata, default=str))
        values.append(item_id)
        with database.transaction() as conn:
            cur = conn.execute(
                f"UPDATE knowledge_items SET {', '.join(clauses)} WHERE id = ? "
                "AND status != 'deprecated'", values)
            return bool(cur.rowcount)

    def delete(self, item_id: str, *, user_id: Optional[int] = None) -> bool:
        with database.transaction() as conn:
            if user_id is None:
                cur = conn.execute("DELETE FROM knowledge_items WHERE id = ?", (item_id,))
            else:
                cur = conn.execute(
                    "DELETE FROM knowledge_items WHERE id = ? AND user_id = ?",
                    (item_id, user_id))
            return bool(cur.rowcount)

    def export_user(self, user_id: int, limit: int = 10000) -> List[Dict[str, Any]]:
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_items WHERE user_id = ? "
                "ORDER BY created_at LIMIT ?",
                (user_id, max(1, min(int(limit), 50000))),
            ).fetchall()
        return [from_row(row) for row in rows]

    def delete_for_user(self, user_id: int) -> int:
        with database.transaction() as conn:
            conn.execute(
                "DELETE FROM knowledge_events WHERE item_id IN "
                "(SELECT id FROM knowledge_items WHERE user_id = ?)", (user_id,))
            cur = conn.execute("DELETE FROM knowledge_items WHERE user_id = ?", (user_id,))
            return cur.rowcount


class SqliteVectorIndex:
    """Derived embeddings stored next to the record; rebuildable at any time."""

    capabilities = Capabilities(durable=True, transactions=True)

    def __init__(self, embedder=None):
        self._embedder = embedder

    def _provider(self):
        return self._embedder or get_embedding_provider()

    async def upsert(self, item_id: str, chunks: Sequence[str]) -> None:
        self.delete(item_id)
        provider = self._provider()
        now = _now()
        for index, chunk in enumerate(chunks):
            vector = await provider.embed(chunk)
            with database.transaction() as conn:
                conn.execute(
                    "INSERT INTO knowledge_chunks (id, item_id, chunk_index, content, "
                    "model, dims, vector, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), item_id, index, chunk, provider.model,
                     len(vector), json.dumps(vector), now),
                )

    def score(self, query_vector: Sequence[float],
              item_ids: Sequence[str]) -> Dict[str, Tuple[float, str]]:
        result: Dict[str, Tuple[float, str]] = {}
        for batch in _chunks(list(item_ids)):
            marks = _placeholders(batch)
            with database.get_connection() as conn:
                rows = conn.execute(
                    f"SELECT item_id, content, vector FROM knowledge_chunks "
                    f"WHERE item_id IN ({marks})", list(batch)).fetchall()
            for row in rows:
                try:
                    vector = json.loads(row["vector"])
                except (TypeError, ValueError):
                    continue
                score = max(0.0, cosine_any(query_vector, vector))
                previous = result.get(row["item_id"])
                if previous is None or score > previous[0]:
                    result[row["item_id"]] = (score, row["content"])
        return result

    def delete(self, item_id: str) -> None:
        with database.transaction() as conn:
            conn.execute("DELETE FROM knowledge_chunks WHERE item_id = ?", (item_id,))


class BaseKnowledgeStore:
    """Lifecycle shared by every backend; adapters implement record + search."""

    capabilities = Capabilities()
    _cache: KnowledgeCache

    def _emit(self, event: str, item_id: Optional[str] = None, *, actor: Optional[str] = None,
              agent_role: Optional[str] = None, data: Optional[dict] = None) -> None:
        events.record(event, item_id, actor=actor, agent_role=agent_role, data=data)

    # --------------------------------------------------------------- lifecycle
    async def supersede(self, item_id: str, replacement: KnowledgeItem, *,
                        actor: Optional[str] = None) -> Dict[str, Any]:
        previous = self.get(item_id)
        if previous is None:
            raise ValueError("knowledge item not found")
        replacement.id = str(uuid.uuid4())
        replacement.supersedes = item_id
        replacement.revision = int(previous.get("revision") or 1) + 1
        replacement.scope = previous["scope"]
        replacement.scope_id = previous.get("scope_id")
        replacement.user_id = previous.get("user_id")
        replacement.organization_id = previous.get("organization_id")
        replacement.agent_role = previous.get("agent_role")
        replacement.created_at = replacement.updated_at = _now()
        replacement.content_hash = build_content_hash(
            replacement.content, replacement.scope, replacement.scope_id,
            replacement.agent_role)
        new_item = await self.write(replacement, actor=actor, dedupe=False)
        self._mark_superseded(item_id, new_item["id"])
        self._emit(events.KNOWLEDGE_SUPERSEDED, item_id, actor=actor,
                   agent_role=previous.get("agent_role"),
                   data={"superseded_by": new_item["id"]})
        new_item["supersedes"] = item_id
        return new_item

    def deprecate(self, item_id: str, *, reason: Optional[str] = None,
                  actor: Optional[str] = None) -> bool:
        changed = self._mark_deprecated(item_id, reason=reason)
        if changed:
            self._emit(events.KNOWLEDGE_DEPRECATED, item_id, actor=actor,
                       data={"reason": reason})
        return changed

    async def promote(self, item_id: str, *, target_scope: str = "global",
                      actor: Optional[str] = None,
                      organization_id: Optional[str] = None) -> Dict[str, Any]:
        validate_scopes([target_scope])
        source = self.get(item_id)
        if source is None:
            raise ValueError("knowledge item not found")
        promoted = KnowledgeItem(
            kind=source["kind"],
            content=source["content"],
            summary=source.get("summary"),
            scope=target_scope,
            scope_id=(organization_id if target_scope == "org" else None),
            user_id=(source.get("user_id") if target_scope == "org" else None),
            organization_id=(organization_id if target_scope == "org" else None),
            agent_role=source.get("agent_role"),
            source=source.get("source") or {},
            metadata={**(source.get("metadata") or {}), "promoted_from": item_id},
            tags=source.get("tags") or [],
            confidence=float(source.get("confidence") or 0.5),
            importance=float(source.get("importance") or 0.0),
            status=KnowledgeStatus.PROMOTED.value,
        )
        created = await self.write(promoted, actor=actor, dedupe=True, allow_global=True)
        self._emit(events.KNOWLEDGE_PROMOTED, created["id"], actor=actor,
                   agent_role=created.get("agent_role"),
                   data={"from": item_id, "to_scope": target_scope})
        return created

    def revisions(self, item_id: str) -> List[Dict[str, Any]]:
        chain: List[Dict[str, Any]] = []
        seen = set()
        current = self.get(item_id)
        while current and current["id"] not in seen:
            chain.append(current)
            seen.add(current["id"])
            parent = current.get("supersedes")
            current = self.get(parent) if parent else None
        chain.reverse()
        forward = self.get(item_id)
        while forward and forward.get("superseded_by"):
            nxt = self.get(forward["superseded_by"])
            if not nxt or nxt["id"] in seen:
                break
            seen.add(nxt["id"])
            chain.append(nxt)
            forward = nxt
        return chain

    # Adapter hooks ---------------------------------------------------------
    def _mark_superseded(self, item_id: str, new_id: str) -> bool:
        raise NotImplementedError

    def _mark_deprecated(self, item_id: str, *, reason: Optional[str] = None) -> bool:
        raise NotImplementedError


class SqliteKnowledgeStore(BaseKnowledgeStore):
    """SQLite composition of the record, vector index and cache ports."""

    capabilities = Capabilities(durable=True, transactions=True)

    def __init__(self, repository: Optional[KnowledgeRepository] = None,
                 vector_index: Optional[VectorIndex] = None,
                 cache: Optional[KnowledgeCache] = None,
                 embedder=None):
        self._repository = repository or SqliteKnowledgeRepository()
        self._vectors = vector_index or SqliteVectorIndex(embedder)
        self._cache = cache or NullCache()
        self._embedder = embedder

    def _provider(self):
        return self._embedder or get_embedding_provider()

    # ------------------------------------------------------------------ write
    async def write(self, item: KnowledgeItem, *, actor: Optional[str] = None,
                    dedupe: bool = True, allow_global: bool = False) -> Dict[str, Any]:
        validate_scopes([item.scope])
        if item.scope == "global" and not allow_global:
            raise PermissionError(
                "global knowledge can only be created through promotion")
        item.updated_at = item.created_at = _now()
        if dedupe:
            existing = self._repository.find_by_hash(item.content_hash)
            if existing:
                merged = self._repository.bump(
                    existing["id"],
                    max(float(existing.get("confidence") or 0), item.confidence),
                    max(float(existing.get("importance") or 0), item.importance))
                self._cache.bump()
                self._emit(events.KNOWLEDGE_WRITTEN, merged["id"], actor=actor,
                           agent_role=item.agent_role,
                           data={"duplicate": True, "scope": merged["scope"]})
                return merged

        stored = self._repository.insert(item)
        await self._vectors.upsert(item.id, chunk_text(item.content))
        self._cache.bump()
        self._emit(events.KNOWLEDGE_WRITTEN, item.id, actor=actor,
                   agent_role=item.agent_role,
                   data={"scope": item.scope, "scope_id": item.scope_id,
                         "status": item.status})
        return stored

    # ----------------------------------------------------------------- search
    async def search(self, query: KnowledgeQuery) -> List[Dict[str, Any]]:
        validate_scopes(query.scopes)
        if not (query.text or "").strip():
            return []
        pairs = scope_pairs(query.scopes, query.user_id, query.agent_role,
                            query.conversation_id, query.organization_id)
        if not pairs:
            return []
        cache_key = self._search_key(query, pairs)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        statuses = list(query.statuses or READABLE_STATUSES)
        kinds = list(query.kinds) if query.kinds else None
        candidates = self._repository.candidates(
            pairs, statuses, kinds, query.max_candidates,
            user_id=query.user_id)
        if not candidates:
            return []
        query_vector = await self._provider().embed(query.text)
        hits = self._vectors.score(query_vector, [item["id"] for item in candidates])
        ranked = ranking.rank(query.text, candidates, hits, query.normalized_limit())
        if ranked:
            self._cache.set(cache_key, ranked)
        return ranked

    def _search_key(self, query: KnowledgeQuery, pairs) -> str:
        material = "|".join([
            str(self._cache.version()), str(query.text), str(query.user_id),
            str(query.agent_role), str(query.conversation_id),
            str(query.organization_id), ",".join(query.scopes),
            ",".join(query.kinds or ()), str(query.limit),
            ";".join(f"{scope}:{scope_id}" for scope, scope_id in pairs),
        ])
        return "knowledge:search:" + hashlib.sha256(
            material.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------- lifecycle
    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        key = f"knowledge:item:{item_id}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        item = self._repository.get(item_id)
        if item is not None:
            self._cache.set(key, item)
        return item

    def list_items(self, *, user_id: Optional[int] = None,
                   organization_id: Optional[str] = None,
                   scope: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self._repository.list_items(
            user_id=user_id, organization_id=organization_id,
            scope=scope, limit=limit)

    def delete(self, item_id: str, *, user_id: Optional[int] = None) -> bool:
        deleted = self._repository.delete(item_id, user_id=user_id)
        if deleted:
            self._vectors.delete(item_id)
            self._cache.bump()
        return deleted

    def export_user(self, user_id: int, limit: int = 10000) -> List[Dict[str, Any]]:
        return self._repository.export_user(user_id, limit)

    def delete_for_user(self, user_id: int) -> int:
        count = self._repository.delete_for_user(user_id)
        self._cache.bump()
        return count

    def _mark_superseded(self, item_id: str, new_id: str) -> bool:
        changed = self._repository.set_status(
            item_id, "deprecated", superseded_by=new_id)
        self._cache.bump()
        return changed

    def _mark_deprecated(self, item_id: str, *, reason: Optional[str] = None) -> bool:
        existing = self._repository.get(item_id) or {}
        metadata = {**(existing.get("metadata") or {}),
                    "deprecation_reason": reason or ""}
        changed = self._repository.set_status(
            item_id, "deprecated", metadata=metadata)
        if changed:
            self._cache.bump()
        return changed


# --------------------------------------------------------------------------- #
# Module-level default backend.
# --------------------------------------------------------------------------- #
_default_store: Optional[Any] = None


def get_store() -> Any:
    global _default_store
    if _default_store is None:
        from .factory import create_store
        _default_store = create_store()
    return _default_store


def set_store(store) -> None:
    global _default_store
    _default_store = store
