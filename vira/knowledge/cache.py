"""Disposable caches for knowledge reads.

The cache is never authoritative.  Every write bumps a generation counter; a
cached entry from an older generation is ignored.  That makes invalidation
correct even when several events race, and keeps the port small enough for a
Redis adapter later.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Dict, Optional, Tuple


class NullCache:
    """No-op cache used when caching is disabled or unsupported."""

    def get(self, key: str) -> Any:
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        return None

    def delete(self, key: str) -> None:
        return None

    def bump(self) -> int:
        return 0

    def version(self) -> int:
        return 0


class InProcessTtlCache:
    """Thread-safe-enough TTL cache for a single VIRA process.

    Entries store a generation stamp.  ``bump()`` increments the generation
    instead of walking the cache, so invalidation is O(1) and race-free.
    """

    def __init__(self, ttl_seconds: float = 30.0, max_items: int = 512):
        self._ttl = max(1.0, float(ttl_seconds))
        self._max_items = max(8, int(max_items))
        self._items: Dict[str, Tuple[int, float, Any]] = {}
        self._generation = 0

    def get(self, key: str) -> Any:
        entry = self._items.get(key)
        if entry is None:
            return None
        generation, expires_at, value = entry
        if generation != self._generation or expires_at < time.monotonic():
            self._items.pop(key, None)
            return None
        return copy.deepcopy(value)

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        if len(self._items) >= self._max_items:
            now = time.monotonic()
            for stale in [name for name, (gen, exp, _) in self._items.items()
                          if gen != self._generation or exp < now]:
                self._items.pop(stale, None)
            if len(self._items) >= self._max_items:
                self._items.pop(next(iter(self._items)), None)
        ttl = self._ttl if ttl_seconds is None else max(1.0, float(ttl_seconds))
        self._items[key] = (self._generation, time.monotonic() + ttl,
                            copy.deepcopy(value))

    def delete(self, key: str) -> None:
        self._items.pop(key, None)

    def bump(self) -> int:
        self._generation += 1
        self._items.clear()
        return self._generation

    def version(self) -> int:
        return self._generation
