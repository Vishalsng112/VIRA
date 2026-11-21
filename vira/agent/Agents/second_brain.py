"""Second Brain: capture, grounded recall and safe weekly consolidation.

Modes are selected by the schedule payload (``input.mode``) or inferred from the
message: ``capture``, ``ask`` and ``consolidate``. Capture writes personal
knowledge only when the user explicitly asks to remember something. Recall cites
the stored item and date. Consolidation reports duplicates and stale items but
never deletes anything.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.architectures import Architecture, ARCHITECTURE_PROFILES
from vira.agent.base import TaskRequest, TaskResult
from vira.agent.conversational_agent import ConversationalAgent

CAPTURE_PREFIX = re.compile(
    r"^\s*(remember|note|save|store)\s*(that|this|it|:)?\s*", re.IGNORECASE)
VALID_KINDS = {"fact", "preference", "procedure", "observation", "document"}

DEFAULT_SYSTEM_PROMPT = (
    "You are VIRA's second brain. You answer only from the user's stored notes "
    "and memories. If the notes do not contain the answer, say so plainly."
)


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class SecondBrainAgent(ConversationalAgent):
    """Capture, recall and consolidate the user's personal knowledge."""

    name = "SecondBrainAgent"
    role = "second-brain"
    description = (
        "Capture notes and decisions, answer questions with cited stored items, "
        "and report duplicates/stale knowledge without deleting anything."
    )
    architecture = Architecture.SINGLE.value
    default_name = "SecondBrainAgent"
    default_description = (
        "Remember user notes, answer from them with citations, and report stale "
        "or duplicate knowledge.")
    default_system_prompt = DEFAULT_SYSTEM_PROMPT
    capability_name = "second-brain"
    capability_description = (
        "Capture personal knowledge, answer from it with citations, and review it.")
    is_default_agent = False

    def __init__(self, runtime, **config: Any):
        merged = dict(config or {})
        merged.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
        merged.setdefault("max_tokens", 700)
        merged.setdefault("temperature", 0.2)
        merged.setdefault("delegation", False)
        super().__init__(runtime, **merged)
        self.default_mode = str(merged.get("mode") or "ask")
        self.stale_days = max(7, min(int(merged.get("stale_days", 90)), 3650))
        self.low_confidence = max(0.0, min(float(merged.get("low_confidence", 0.35)), 1.0))
        self.max_words = max(60, min(int(merged.get("max_words", 220)), 600))

    # ------------------------------------------------------------------ mode
    def _mode(self, request: TaskRequest) -> str:
        raw = ""
        if isinstance(request.input, dict):
            raw = str(request.input.get("mode") or "")
        raw = raw or str(request.metadata.get("mode") or "")
        if raw in {"capture", "ask", "consolidate", "correct"}:
            return raw
        text = request.message.lower()
        if any(word in text for word in ("correct ", "fix note", "update note", "revise note")):
            return "correct"
        if any(word in text for word in ("consolidat", "duplicate", "stale", "clean up")):
            return "consolidate"
        if any(word in text for word in ("remember", "note that", "save that", "store that")):
            return "capture"
        return self.default_mode if self.default_mode in {"capture", "ask"} else "ask"

    def _capture_content(self, request: TaskRequest) -> str:
        content = ""
        if isinstance(request.input, dict):
            content = str(request.input.get("content") or "")
        content = content or request.message
        return CAPTURE_PREFIX.sub("", content, count=1).strip()

    # --------------------------------------------------------------- correct
    async def _correct(self, request: TaskRequest) -> TaskResult:
        item_id = ""
        content = ""
        if isinstance(request.input, dict):
            item_id = str(request.input.get("item_id") or "")
            content = str(request.input.get("content") or "")
        content = content or CAPTURE_PREFIX.sub("", request.message, count=1).strip()
        if not item_id:
            return TaskResult(
                text="Tell me which item to correct (item_id) and the new content.",
                data={"architecture": "single",
                      "second_brain": {"mode": "correct", "error": "missing item_id"}},
                error="missing item_id",
            )
        if not content:
            return TaskResult(
                text="Tell me the corrected content for that note.",
                data={"architecture": "single",
                      "second_brain": {"mode": "correct", "error": "empty content"}},
                error="empty content",
            )
        try:
            item = await self.knowledge_correct(item_id, content)
        except Exception as exc:
            logger.warning("[{}] correction failed: {}", self.name, exc)
            return TaskResult(
                text=f"I couldn't correct that note. {type(exc).__name__}: {exc}",
                data={"architecture": "single",
                      "second_brain": {"mode": "correct", "error": True}},
                error=str(exc),
            )
        summary = " ".join(content.split())[:140]
        self.emit_progress("second_brain.corrected", item_id=item_id,
                           revision=(item or {}).get("revision"))
        return TaskResult(
            text=f"Corrected note: {summary}",
            data={
                "architecture": "single",
                "response": f"Corrected note: {summary}",
                "coordination": self._coordination(),
                "second_brain": {
                    "mode": "correct",
                    "supersedes": item_id,
                    "item_id": (item or {}).get("id"),
                    "revision": (item or {}).get("revision"),
                },
            },
            stopped="final",
        )

    # --------------------------------------------------------------- capture
    async def _capture(self, request: TaskRequest) -> TaskResult:
        content = self._capture_content(request)
        if not content:
            return TaskResult(
                text="Nothing to save. Send the note or decision you want me to remember.",
                data={"architecture": "single", "second_brain": {"mode": "capture"}},
                error="empty capture",
            )
        kind = "fact"
        tags: List[str] = []
        if isinstance(request.input, dict):
            requested_kind = str(request.input.get("kind") or "fact")
            if requested_kind in VALID_KINDS:
                kind = requested_kind
            raw_tags = request.input.get("tags")
            if isinstance(raw_tags, list):
                tags = [str(tag)[:40] for tag in raw_tags][:12]
        summary = " ".join(content.split())[:140]
        try:
            item = await self.knowledge_write(
                content,
                requested_by_user=True,
                kind=kind,
                summary=summary,
                tags=tags,
                importance=0.6,
                metadata={"source": "second_brain", "capture": True},
            )
        except Exception as exc:
            logger.warning("[{}] capture failed: {}", self.name, exc)
            return TaskResult(
                text=("I couldn't save that note. "
                      f"{type(exc).__name__}: {exc}"),
                data={"architecture": "single",
                      "second_brain": {"mode": "capture", "error": True}},
                error=str(exc),
            )
        item_id = item.get("id") if isinstance(item, dict) else None
        scope = item.get("scope") if isinstance(item, dict) else "personal"
        self.emit_progress("second_brain.captured", item_id=item_id, scope=scope)
        return TaskResult(
            text=f"Saved to your second brain: {summary}",
            data={
                "architecture": "single",
                "response": f"Saved to your second brain: {summary}",
                "coordination": self._coordination(),
                "second_brain": {
                    "mode": "capture",
                    "item_id": item_id,
                    "scope": scope,
                    "kind": kind,
                    "tags": tags,
                },
            },
            stopped="final",
        )

    # ------------------------------------------------------------------- ask
    @staticmethod
    def _normalize_hits(items: List[Any]) -> List[Dict[str, Any]]:
        hits = []
        for item in items or []:
            if isinstance(item, dict):
                content = str(item.get("content") or item.get("text") or "").strip()
                if not content:
                    continue
                hits.append({
                    "content": content,
                    "created_at": item.get("created_at") or item.get("updated_at"),
                    "scope": item.get("scope") or item.get("_origin") or "knowledge",
                    "id": item.get("id"),
                })
            else:
                content = str(getattr(item, "content", "") or item).strip()
                if content:
                    hits.append({"content": content, "created_at": None,
                                 "scope": "knowledge", "id": None})
        return hits[:8]

    def _notes_block(self, hits: List[Dict[str, Any]]) -> str:
        lines = []
        for index, hit in enumerate(hits, start=1):
            lines.append(
                f"[{index}] ({hit['scope']}, {hit.get('created_at') or 'date unknown'})\n"
                f"{hit['content'][:1500]}")
        return "\n\n".join(lines)

    async def _ask(self, request: TaskRequest) -> TaskResult:
        query = ""
        if isinstance(request.input, dict):
            query = str(request.input.get("query") or "")
        query = query or request.message
        try:
            hits = self._normalize_hits(
                await self.knowledge_search(query, limit=8))
        except Exception as exc:
            logger.warning("[{}] recall failed: {}", self.name, exc)
            hits = []
        if not hits:
            text = ("I couldn't find that in your second brain. "
                    "Try rephrasing, or tell me to remember it.")
            return TaskResult(
                text=text,
                data={"architecture": "single",
                      "coordination": self._coordination(),
                      "second_brain": {"mode": "ask", "hits": 0, "query": query}},
                stopped="final",
            )
        prompt = (
            f"System: {self.system_prompt}\n\n"
            "Answer the user's question using ONLY the numbered notes below.\n"
            "Cite notes inline as [1], [2]. Include the stored date when it matters.\n"
            "If the notes are insufficient, say what is missing instead of guessing.\n"
            f"Keep the answer under {self.max_words} words.\n\n"
            f"QUESTION:\n{query or 'What do my notes say?'}\n\n"
            f"NOTES:\n{self._notes_block(hits)}"
        )
        generated_by = "llm"
        text = ""
        try:
            text = str(await self.ask_llm(
                prompt, model=self.model, temperature=self.temperature,
                max_tokens=self.max_tokens) or "").strip()
        except Exception as exc:
            logger.warning("[{}] answer generation failed: {}", self.name, exc)
        if not text:
            generated_by = "fallback"
            text = "Here is what I found:\n\n" + "\n\n".join(
                f"[{index}] {hit['content'][:500]}"
                f" ({hit.get('created_at') or 'date unknown'})"
                for index, hit in enumerate(hits, start=1))
        self.emit_progress("second_brain.recalled", hits=len(hits),
                           generated_by=generated_by)
        return TaskResult(
            text=text,
            data={
                "architecture": "single",
                "response": text,
                "coordination": self._coordination(),
                "second_brain": {
                    "mode": "ask",
                    "generated_by": generated_by,
                    "hits": len(hits),
                    "item_ids": [hit.get("id") for hit in hits if hit.get("id")],
                },
            },
            stopped="final",
        )

    # ----------------------------------------------------------- consolidate
    async def _consolidate(self, request: TaskRequest) -> TaskResult:
        try:
            items = await self.knowledge_list(scopes=["personal"], limit=500)
        except Exception as exc:
            logger.warning("[{}] consolidation read failed: {}", self.name, exc)
            items = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.stale_days)
        groups: Dict[str, List[Dict[str, Any]]] = {}
        stale: List[Dict[str, Any]] = []
        low: List[Dict[str, Any]] = []
        for item in items:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            key = " ".join(content.lower().split())
            groups.setdefault(key, []).append(item)
            stamp = _parse_time(item.get("updated_at") or item.get("created_at"))
            if stamp and stamp < cutoff:
                stale.append(item)
            if float(item.get("confidence") or 0.0) < self.low_confidence:
                low.append(item)
        duplicates = [(content, group) for content, group in groups.items()
                      if len(group) > 1]
        lines = [
            "Second brain review",
            f"- Stored items scanned: {len(items)}",
            f"- Duplicate groups: {len(duplicates)}",
            f"- Stale items ({self.stale_days}+ days): {len(stale)}",
            f"- Low-confidence items: {len(low)}",
        ]
        if duplicates:
            lines.append("")
            lines.append("Duplicates to review")
            for content, group in duplicates[:5]:
                snippet = " ".join(content.split())[:90]
                ids = ", ".join(str(item.get("id"))[:8] for item in group[:4])
                lines.append(f"- \"{snippet}\" ({len(group)} copies; {ids})")
        if stale:
            lines.append("")
            lines.append("Oldest items")
            for item in sorted(
                    stale,
                    key=lambda value: str(value.get("updated_at") or value.get("created_at")))[:5]:
                snippet = " ".join(str(item.get("content") or "").split())[:90]
                lines.append(f"- {snippet} ({item.get('created_at') or 'date unknown'})")
        lines.append("")
        lines.append("Nothing was deleted or changed. Remove anything you no longer need "
                     "from the knowledge API.")
        text = "\n".join(lines)
        self.emit_progress("second_brain.consolidated", items=len(items),
                           duplicates=len(duplicates), stale=len(stale))
        return TaskResult(
            text=text,
            data={
                "architecture": "single",
                "response": text,
                "coordination": self._coordination(),
                "second_brain": {
                    "mode": "consolidate",
                    "total": len(items),
                    "duplicates": len(duplicates),
                    "stale": len(stale),
                    "low_confidence": len(low),
                    "deleted": 0,
                },
            },
            stopped="final",
        )

    @staticmethod
    def _coordination() -> Dict[str, Any]:
        return {
            "architecture": Architecture.SINGLE.value,
            "workers": 1,
            "rounds": 0,
            "profile": ARCHITECTURE_PROFILES[Architecture.SINGLE],
        }

    # ------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> TaskResult:
        self._refresh_capabilities()
        mode = self._mode(request)
        self.emit_progress("second_brain.start", mode=mode)
        if mode == "capture":
            return await self._capture(request)
        if mode == "correct":
            return await self._correct(request)
        if mode == "consolidate":
            return await self._consolidate(request)
        return await self._ask(request)
