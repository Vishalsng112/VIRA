"""VIRA's scoped, dynamic knowledge layer.

Public surface::

    from vira.knowledge import service, policy, models

    await service.write("User prefers ISO dates", user_id=1,
                        requested_by_user=True)
    results = await service.search("date format", user_id=1, agent_role="researcher")

Storage is behind ``store.KnowledgeStore``; promotion strategy is behind
``consolidation.PromotionPolicy``.  The future AGI algorithm replaces those,
not the agents.
"""
from . import consolidation, events, factory, models, policy, ranking, service
from .backends.memory import MemoryKnowledgeStore
from .cache import InProcessTtlCache, NullCache
from .ports import (
    Capabilities,
    KnowledgeCache,
    KnowledgeQuery,
    KnowledgeRepository,
    KnowledgeStore,
    VectorIndex,
)
from .store import SqliteKnowledgeStore, get_store, set_store

__all__ = [
    "Capabilities",
    "InProcessTtlCache",
    "KnowledgeCache",
    "KnowledgeQuery",
    "KnowledgeRepository",
    "KnowledgeStore",
    "MemoryKnowledgeStore",
    "NullCache",
    "SqliteKnowledgeStore",
    "VectorIndex",
    "consolidation",
    "events",
    "factory",
    "get_store",
    "models",
    "policy",
    "ranking",
    "service",
    "set_store",
]
