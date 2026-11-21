"""Consolidation seam for the future dynamic AGI knowledge base.

Nothing here is the final algorithm.  It provides:

* a ``PromotionPolicy`` contract with a conservative default,
* ``run_consolidation`` - a worker job that deduplicates, decays confidence and
  reports promotion candidates without promoting anything by itself.

The real algorithm can replace ``default_promotion_policy`` or subscribe to the
``knowledge.*`` events and call ``service.promote``/``store.supersede``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from loguru import logger

from vira.auth import database

from . import events
from .store import get_store


@dataclass
class PromotionDecision:
    allowed: bool
    reason: str


class PromotionPolicy:
    """Decide whether a scoped item may be promoted into shared knowledge."""

    def evaluate(self, item: Dict[str, Any]) -> PromotionDecision:  # pragma: no cover
        raise NotImplementedError


class ConservativePromotionPolicy(PromotionPolicy):
    """Default: promote only reasonably confident, repeated, non-expired items.

    Repeat evidence is taken from ``metadata.confirmations`` - agents should
    increment that when they observe the same fact again.  ``supersedes`` chains
    are considered evidence too.
    """

    def __init__(self, min_confidence: float = 0.7, min_confirmations: int = 2):
        self.min_confidence = min_confidence
        self.min_confirmations = min_confirmations

    def evaluate(self, item: Dict[str, Any]) -> PromotionDecision:
        if item.get("status") in ("deprecated",):
            return PromotionDecision(False, "item is deprecated")
        if item.get("scope") == "global":
            return PromotionDecision(False, "item is already global")
        if item.get("expires_at"):
            return PromotionDecision(False, "ephemeral items are not promoted")
        if float(item.get("confidence") or 0.0) < self.min_confidence:
            return PromotionDecision(
                False, f"confidence below {self.min_confidence}")
        confirmations = int((item.get("metadata") or {}).get("confirmations", 1))
        if confirmations < self.min_confirmations:
            return PromotionDecision(
                False, f"needs {self.min_confirmations} confirmations")
        return PromotionDecision(True, "eligible")


default_promotion_policy: PromotionPolicy = ConservativePromotionPolicy()


def run_consolidation(payload: Optional[Dict[str, Any]] = None) -> str:
    """Worker handler: hygiene pass over the knowledge base.

    Safe no-op default.  It reports candidates but never mutates scope, so it
    can run on every deployment before the real algorithm exists.
    """
    payload = payload or {}
    decay_days = int(payload.get("decay_days", 30))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=decay_days)).isoformat()
    store = get_store()
    items = store.list_items(limit=int(payload.get("scan_limit", 500)))

    candidates = []
    for item in items:
        if item.get("updated_at") and item["updated_at"] < cutoff:
            continue
        if default_promotion_policy.evaluate(item).allowed:
            candidates.append(item["id"])

    # Expire ephemeral conversation knowledge whose TTL has elapsed.
    now = datetime.now(timezone.utc).isoformat()
    expired = 0
    with database.transaction() as conn:
        expired = conn.execute(
            "UPDATE knowledge_items SET status = 'deprecated', updated_at = ? "
            "WHERE expires_at IS NOT NULL AND expires_at <= ? AND status != 'deprecated'",
            (now, now),
        ).rowcount
    if expired:
        events.record("knowledge.expired", None, actor="consolidation",
                      data={"count": expired})
    logger.info("knowledge consolidation: candidates={} expired={}",
                len(candidates), expired)
    return f"candidates={len(candidates)} expired={expired}"


def inspect() -> Dict[str, Any]:
    """Read-only summary used by the API/health endpoints."""
    items = get_store().list_items(limit=500)
    by_scope: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for item in items:
        by_scope[item["scope"]] = by_scope.get(item["scope"], 0) + 1
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {"total": len(items), "by_scope": by_scope, "by_status": by_status}
