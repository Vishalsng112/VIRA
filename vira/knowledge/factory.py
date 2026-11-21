"""Config-driven selection of knowledge storage adapters.

``knowledge.backend`` chooses the *record* implementation.  The SQL adapter runs
on SQLite or PostgreSQL because ``vira.auth.database`` routes connections based
on ``VIRA_DATABASE_URL``; it is not SQLite-specific.  ``knowledge.cache`` chooses
the read cache.

Adding a backend later (MongoDB, Qdrant, ...) means implementing the ports in
``vira/knowledge/ports.py`` and registering it here.  No caller changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from .backends.memory import MemoryKnowledgeStore
from .cache import InProcessTtlCache, NullCache
from .ports import KnowledgeCache
from .store import SqliteKnowledgeStore

_SQL_BACKENDS = {"sql", "sqlite", "postgres", "postgresql"}
_MEMORY_BACKENDS = {"memory", "in-memory", "inmemory", "ephemeral"}


def load_settings(path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Read the ``knowledge:`` section of ``config.yaml`` (best effort)."""
    try:
        import yaml
        target = Path(path or "config.yaml")
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        section = data.get("knowledge") or {}
        return dict(section) if isinstance(section, dict) else {}
    except (OSError, ValueError, ImportError):
        return {}


def build_cache(settings: Dict[str, Any]) -> KnowledgeCache:
    kind = str(settings.get("cache", "memory")).lower()
    if kind in ("none", "null", "off", "disabled"):
        return NullCache()
    if kind in ("memory", "in-process", "inprocess"):
        return InProcessTtlCache(
            ttl_seconds=float(settings.get("cache_ttl_seconds", 30)),
            max_items=int(settings.get("cache_max_items", 512)),
        )
    raise ValueError(
        f"unknown knowledge cache '{kind}'; supported: memory, none")


def create_store(settings: Optional[Dict[str, Any]] = None,
                 embedder=None) -> Any:
    """Build the configured ``KnowledgeStore``.

    An unknown backend is a startup error, not a silent fallback, so a
    misconfiguration can never change isolation semantics unnoticed.
    """
    settings = dict(settings if settings is not None else load_settings())
    backend = str(settings.get("backend", "sql")).strip().lower()
    cache = build_cache(settings)

    if backend in _SQL_BACKENDS:
        store = SqliteKnowledgeStore(cache=cache, embedder=embedder)
    elif backend in _MEMORY_BACKENDS:
        store = MemoryKnowledgeStore(cache=cache, embedder=embedder)
    else:
        raise ValueError(
            f"unknown knowledge backend '{backend}'; supported: sql, memory")
    logger.info("knowledge backend={} cache={} capabilities={}",
                backend, type(cache).__name__, store.capabilities.as_dict())
    return store
