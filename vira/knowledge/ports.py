"""Storage ports for the knowledge layer.

Nothing above this module may depend on a concrete database.  The service and
tools speak in ``KnowledgeQuery`` / plain item dicts, and the factory chooses an
adapter from configuration.

Division of responsibility:

* ``KnowledgeRepository`` - authoritative record: items, revisions, scopes,
  provenance, status changes.  Must be transactional.
* ``VectorIndex`` - derived, rebuildable embedding index.  May be SQLite,
  pgvector, Qdrant or a test double.
* ``KnowledgeCache`` - disposable read cache.  May be in-process, Redis or a
  no-op.

A NoSQL or vector-native backend can implement any of these ports later without
changing agents, tools or ``service.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .models import KnowledgeItem


@dataclass(frozen=True)
class Capabilities:
    """What an adapter can guarantee; callers degrade instead of guessing."""

    durable: bool = True
    transactions: bool = False
    ann: bool = False           # approximate nearest neighbour search
    fulltext: bool = False      # native BM25/tsvector/FTS search
    graph: bool = False         # relationship traversal
    read_your_writes: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "durable": self.durable,
            "transactions": self.transactions,
            "ann": self.ann,
            "fulltext": self.fulltext,
            "graph": self.graph,
            "read_your_writes": self.read_your_writes,
        }


@dataclass
class KnowledgeQuery:
    """A storage-neutral retrieval request.

    ``scopes`` is the set of scopes the caller may read; it must already have
    passed authorization.  Adapters apply it as a filter, never as an
    optimisation they may skip.
    """

    text: str
    scopes: Sequence[str]
    user_id: Optional[int] = None
    agent_role: Optional[str] = None
    conversation_id: Optional[str] = None
    organization_id: Optional[str] = None
    limit: int = 8
    kinds: Optional[Sequence[str]] = None
    statuses: Optional[Sequence[str]] = None
    max_candidates: int = 2000

    def normalized_limit(self) -> int:
        return max(1, min(int(self.limit), 50))


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Authoritative record store. Implementations may use any database."""

    capabilities: Capabilities

    def insert(self, item: KnowledgeItem) -> Dict[str, Any]:
        ...

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        ...

    def find_by_hash(self, digest: Optional[str]) -> Optional[Dict[str, Any]]:
        ...

    def bump(self, item_id: str, confidence: float, importance: float) -> Dict[str, Any]:
        ...

    def candidates(self, pairs: Sequence[Tuple[str, Optional[str]]],
                   statuses: Sequence[str], kinds: Optional[Sequence[str]],
                   limit: int, *, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Item rows (no vectors) matching the readable scopes."""
        ...

    def list_items(self, *, user_id: Optional[int] = None,
                   organization_id: Optional[str] = None,
                   scope: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        ...

    def set_status(self, item_id: str, status: str, *,
                   superseded_by: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> bool:
        ...

    def delete(self, item_id: str, *, user_id: Optional[int] = None) -> bool:
        ...

    def export_user(self, user_id: int, limit: int = 10000) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class VectorIndex(Protocol):
    """Derived embedding index. Safe to rebuild from the repository."""

    async def upsert(self, item_id: str, chunks: Sequence[str]) -> None:
        ...

    def score(self, query_vector: Sequence[float],
              item_ids: Sequence[str]) -> Dict[str, Tuple[float, str]]:
        """Return ``{item_id: (cosine, best_excerpt)}``."""
        ...

    def delete(self, item_id: str) -> None:
        ...


@runtime_checkable
class KnowledgeCache(Protocol):
    """Disposable read cache. Never authoritative."""

    def get(self, key: str) -> Any:
        ...

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def bump(self) -> int:
        """Invalidate a namespace and return the new generation."""
        ...

    def version(self) -> int:
        ...


@runtime_checkable
class KnowledgeStore(Protocol):
    """Facade contract consumed by ``service`` and tools."""

    capabilities: Capabilities

    async def write(self, item: KnowledgeItem, *, actor: Optional[str] = None,
                    dedupe: bool = True, allow_global: bool = False) -> Dict[str, Any]:
        ...

    async def search(self, query: KnowledgeQuery) -> List[Dict[str, Any]]:
        ...

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        ...

    def list_items(self, *, user_id: Optional[int] = None,
                   organization_id: Optional[str] = None,
                   scope: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        ...

    async def supersede(self, item_id: str, replacement: KnowledgeItem, *,
                        actor: Optional[str] = None) -> Dict[str, Any]:
        ...

    def deprecate(self, item_id: str, *, reason: Optional[str] = None,
                  actor: Optional[str] = None) -> bool:
        ...

    async def promote(self, item_id: str, *, target_scope: str = "global",
                      actor: Optional[str] = None,
                      organization_id: Optional[str] = None) -> Dict[str, Any]:
        ...

    def revisions(self, item_id: str) -> List[Dict[str, Any]]:
        ...

    def delete(self, item_id: str, *, user_id: Optional[int] = None) -> bool:
        ...

    def export_user(self, user_id: int, limit: int = 10000) -> List[Dict[str, Any]]:
        ...
