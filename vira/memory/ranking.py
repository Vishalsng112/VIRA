"""Memory ranking with recency, importance and explicit user feedback.

Inspired by long-term-memory evaluations (LongMemEval) where retrieval quality
depends on temporal reasoning, knowledge updates and abstention rather than
lexical overlap alone. The weights are intentionally simple and inspectable.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .embeddings import hybrid_score

HALF_LIFE_DAYS = 30.0


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recency(value: Any, now: Optional[datetime] = None) -> float:
    moment = _parse(value)
    if moment is None:
        return 0.3
    now = now or datetime.now(timezone.utc)
    age_days = max(0.0, (now - moment).total_seconds() / 86400)
    return math.exp(-age_days / HALF_LIFE_DAYS)


def feedback_bonus(value: Optional[str]) -> float:
    return {"useful": 0.15, "not_useful": -0.35}.get(str(value or ""), 0.0)


def score_memory(item: Dict[str, Any], query: str, *, relevance: Optional[float] = None,
                 now: Optional[datetime] = None) -> float:
    content = str(item.get("content") or "")
    rel = hybrid_score(query, content) if relevance is None else float(relevance)
    try:
        importance = float(item.get("importance") or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    importance = min(max(importance, 0.0), 1.0)
    freshness = recency(item.get("last_used_at") or item.get("created_at"), now)
    return (
        0.55 * rel
        + 0.20 * importance
        + 0.15 * freshness
        + 0.10 * max(0.0, min(1.0, (rel + freshness) / 2))
        + feedback_bonus(item.get("feedback"))
    )


def rank_memories(query: str, items: Iterable[Dict[str, Any]], limit: int = 10,
                  now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    scored = []
    for item in items:
        if str(item.get("feedback") or "") == "muted":
            continue
        lexical = hybrid_score(query, str(item.get("content") or ""))
        relevance = item.get("_score")
        relevance = max(float(relevance or 0.0), lexical)
        # Abstain when there is no lexical or semantic overlap at all.
        if query and float(relevance) <= 0:
            continue
        scored.append((score_memory(item, query, relevance=relevance, now=now), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:max(1, limit)]]
