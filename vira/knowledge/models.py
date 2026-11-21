"""Canonical knowledge model for VIRA's shared, scope-aware knowledge base.

The types in this module are the stable contract between agents, tools and
future consolidation algorithms.  Storage is deliberately not part of the
contract: ``store.KnowledgeStore`` can be backed by SQLite today and by a
dedicated vector database later.

Scoping rules (see ``policy``):

* ``conversation`` - working knowledge for one conversation/run (TTL-bound).
* ``personal``     - a user's private knowledge, visible to all their agents.
* ``agent``        - learnings of a stable agent *role* for one user.
* ``org``          - organization knowledge shared by its members.
* ``global``       - the curated AGI knowledge base. Only promotion writes here.

Nothing is ever hard-updated.  A correction creates a new revision that
``supersedes`` the previous item, so the knowledge base can be rolled back and
queried "as of" a point in time.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Scope(str, Enum):
    CONVERSATION = "conversation"
    PERSONAL = "personal"
    AGENT = "agent"
    ORG = "org"
    GLOBAL = "global"


class KnowledgeStatus(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"


class KnowledgeKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROCEDURE = "procedure"
    OBSERVATION = "observation"
    DOCUMENT = "document"


READABLE_STATUSES = (
    KnowledgeStatus.DRAFT.value,
    KnowledgeStatus.CANDIDATE.value,
    KnowledgeStatus.VERIFIED.value,
    KnowledgeStatus.PROMOTED.value,
)

_NORMALIZE = re.compile(r"\s+")


def content_hash(content: str, scope: str, scope_id: Optional[str],
                 agent_role: Optional[str]) -> str:
    """Stable deduplication key for an item within its scope."""
    normalized = _NORMALIZE.sub(" ", (content or "").strip().lower())
    seed = "\x1f".join([normalized, scope, scope_id or "", agent_role or ""])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class KnowledgeSource(BaseModel):
    """Where an item came from. Never trusted for authorization."""

    agent_id: Optional[str] = None
    agent_role: Optional[str] = None
    run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[int] = None
    tool: Optional[str] = None
    uri: Optional[str] = None
    requested_by_user: bool = False


class KnowledgeItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = KnowledgeKind.FACT.value
    content: str
    summary: Optional[str] = None
    scope: str = Scope.PERSONAL.value
    scope_id: Optional[str] = None
    user_id: Optional[int] = None
    organization_id: Optional[str] = None
    agent_role: Optional[str] = None
    source: KnowledgeSource = Field(default_factory=KnowledgeSource)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    confidence: float = 0.5
    importance: float = 0.0
    status: str = KnowledgeStatus.DRAFT.value
    revision: int = 1
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    expires_at: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    def model_post_init(self, __context: Any) -> None:  # pydantic v2 hook
        self.confidence = min(1.0, max(0.0, float(self.confidence)))
        self.importance = min(1.0, max(0.0, float(self.importance)))
        if not self.content_hash:
            self.content_hash = content_hash(
                self.content, self.scope, self.scope_id, self.agent_role)

    def to_row(self) -> Dict[str, Any]:
        import json
        row = self.model_dump()
        row["source"] = json.dumps(row.get("source") or {}, default=str)
        row["metadata"] = json.dumps(row.get("metadata") or {}, default=str)
        row["tags"] = json.dumps(row.get("tags") or [], default=str)
        return row


def from_row(row: Any) -> Dict[str, Any]:
    """Convert a sqlite3.Row/dict into a plain, JSON-safe item dict."""
    import json
    item = dict(row)
    for key in ("source", "metadata"):
        value = item.get(key)
        if isinstance(value, str):
            try:
                item[key] = json.loads(value or "{}")
            except ValueError:
                item[key] = {}
    tags = item.get("tags")
    if isinstance(tags, str):
        try:
            item["tags"] = json.loads(tags or "[]")
        except ValueError:
            item["tags"] = []
    return item
