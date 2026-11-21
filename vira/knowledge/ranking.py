"""Shared, backend-neutral ranking for knowledge retrieval.

Adapters provide candidate item rows plus semantic scores; the blend of semantic
similarity, lexical overlap, confidence and scope weight lives here so every
backend ranks identically.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from vira.memory.embeddings import tokens

from .policy import READ_SCOPE_WEIGHT, SCOPE_PRECEDENCE


def blend(semantic: float, lexical: float, confidence: float, scope: str) -> float:
    base = 0.7 * max(0.0, semantic) + 0.3 * max(0.0, lexical)
    if base <= 0:
        return 0.0
    trust = 0.6 + 0.4 * max(0.0, min(1.0, confidence))
    score = base * trust * READ_SCOPE_WEIGHT.get(scope, 0.9)
    return score * (SCOPE_PRECEDENCE.get(scope, 0.9) ** 0.05)


def lexical_overlap(query: str, text: str) -> float:
    query_tokens = set(tokens(query))
    if not query_tokens:
        return 0.0
    content_tokens = set(tokens(text))
    return len(query_tokens & content_tokens) / len(query_tokens)


def rank(query: str,
         candidates: Iterable[Mapping[str, Any]],
         semantic_hits: Mapping[str, Tuple[float, str]],
         limit: int) -> List[Dict[str, Any]]:
    """Merge candidate rows with semantic hits and sort by blended score."""
    ranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        hit = semantic_hits.get(item["id"])
        if not hit:
            continue
        semantic, excerpt = hit
        excerpt = excerpt or item.get("content", "")
        score = blend(semantic, lexical_overlap(query, excerpt),
                      float(item.get("confidence") or 0.0), item["scope"])
        if score <= 0:
            continue
        item["score"] = round(score, 6)
        item["excerpt"] = excerpt
        item["_origin"] = "knowledge"
        ranked.append(item)
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[: max(1, min(int(limit), 50))]
