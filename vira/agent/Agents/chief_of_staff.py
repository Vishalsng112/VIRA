"""Chief of Staff: inbox, calendar and task triage with approval-safe drafts.

The agent is a centralized coordinator: it collects configured email/calendar/
task sources, runs one extraction worker per source in parallel, validates the
structured results, and renders a triage brief. It never calls a send tool, so
drafts are always output for a human to approve and send elsewhere.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.architectures import Architecture, ARCHITECTURE_PROFILES, CentralizedAgentSystem
from vira.agent.base import TaskRequest, TaskResult
from vira.agent.tool_output import tool_error, tool_text

DEFAULT_SYSTEM_PROMPT = (
    "You are VIRA's chief of staff. You triage email, calendar and tasks, "
    "extract only what is supported by the source, and draft replies for human "
    "approval. You never claim to have sent anything."
)

EXTRACT_PROMPT = (
    "You are the {role} extraction worker in a centralized chief-of-staff "
    "system. Read the SOURCE below and return ONLY JSON:\n"
    "{{\"summary\": \"one sentence\", \"action_items\": "
    "[{{\"text\": \"...\", \"due\": \"... or empty\", \"link\": \"... or empty\"}}], "
    "\"drafts\": [{{\"to\": \"...\", \"subject\": \"...\", \"body\": \"...\"}}]}}\n"
    "Rules:\n"
    "- Use only facts present in the source; never invent senders, dates or tasks.\n"
    "- Only add a draft when a reply is clearly needed. Keep drafts short.\n"
    "- Use PREFERENCES only for tone and style; never extract items from them.\n"
    "- Every action item must be actionable and attributable to this source.\n"
    "- SOURCE NAME: {source}\n\nPREFERENCES:\n{preferences}\n\nSOURCE:\n{text}"
)

MODE_INSTRUCTIONS = {
    "morning": "Focus on what needs the user today: urgent threads, conflicts, and the first actions.",
    "evening": "Focus on follow-ups that still need a reply and what should be ready tomorrow morning.",
}


class ChiefOfStaffAgent(CentralizedAgentSystem):
    """Parallel inbox/calendar/task triage with a validation bottleneck."""

    name = "ChiefOfStaffAgent"
    role = "chief-of-staff"
    description = (
        "Triage email, calendar and tasks in parallel, extract source-linked "
        "action items and draft replies without sending anything."
    )
    architecture = Architecture.CENTRALIZED.value

    def __init__(self, runtime, **config: Any):
        merged = dict(config or {})
        merged.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
        merged.setdefault("max_tokens", 900)
        merged.setdefault("temperature", 0.2)
        merged.setdefault("delegation", False)
        super().__init__(runtime, **merged)
        self.default_mode = str(merged.get("mode") or "morning")
        self.max_sources = max(1, min(int(merged.get("max_sources", 6)), 10))
        self.max_source_chars = max(1000, int(merged.get("max_source_chars", 7000)))
        self.sources = self._normalize_sources(merged.get("context_tools"))

    @staticmethod
    def _normalize_sources(value: Any) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            return []
        sources = []
        for entry in value:
            if isinstance(entry, str):
                sources.append({"name": entry, "role": entry})
            elif isinstance(entry, dict) and entry.get("name"):
                sources.append({
                    "name": str(entry["name"]),
                    "role": str(entry.get("role") or entry["name"]),
                })
        return sources

    def _mode(self, request: TaskRequest) -> str:
        raw = ""
        if isinstance(request.input, dict):
            raw = str(request.input.get("mode") or "")
        raw = raw or self.default_mode
        if raw in MODE_INSTRUCTIONS:
            return raw
        return "evening" if "evening" in request.message.lower() else "morning"

    # ------------------------------------------------------------ collection
    async def _collect_one(self, source: Dict[str, str]) -> Dict[str, Any]:
        name, role = source["name"], source["role"]
        if not self.tool_policy.allows(name):
            return {"source": role, "tool": name, "error": "not allowed for this agent"}
        if self._toolbox.get(name) is None:
            return {"source": role, "tool": name, "error": "not installed"}
        try:
            result = await self.call_tool(name)
            text = tool_text(result).strip()
            if tool_error(result):
                return {"source": role, "tool": name,
                        "error": text[:300] or "tool returned an error"}
            if not text:
                return {"source": role, "tool": name, "error": "empty result"}
            return {"source": role, "tool": name,
                    "text": text[:self.max_source_chars], "error": None}
        except Exception as exc:
            logger.warning("[{}] source {} failed: {}", self.name, name, exc)
            return {"source": role, "tool": name,
                    "error": f"{type(exc).__name__}: {exc}"[:300]}

    async def _preferences(self) -> str:
        try:
            memories = await self.recall("email tone preferences people", limit=5)
        except Exception as exc:
            logger.debug("[{}] preference recall failed: {}", self.name, exc)
            return ""
        return "\n".join(
            str(getattr(item, "content", "") or "").strip()
            for item in memories or []
            if str(getattr(item, "content", "") or "").strip()
        )[:2000]

    # -------------------------------------------------------------- workers
    async def _extract(self, source: Dict[str, Any], mode: str,
                       preferences: str = "") -> Dict[str, Any]:
        if source.get("error"):
            return {"source": source["source"], "error": source["error"],
                    "summary": "", "action_items": [], "drafts": []}
        prompt = EXTRACT_PROMPT.format(
            role=source["source"], source=source["source"],
            text=source["text"], preferences=preferences or "(none)")
        raw = await self._llm(prompt, role=f"extract-{source['source']}",
                              max_tokens=min(700, self.max_tokens))
        from vira.agent.toolcalls import extract_json
        data = extract_json(raw) or {}
        items = []
        for item in data.get("action_items") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            items.append({
                "text": text[:500],
                "due": str(item.get("due") or "").strip()[:120],
                "link": str(item.get("link") or "").strip()[:500],
                "source": source["source"],
            })
        drafts = []
        for draft in data.get("drafts") or []:
            if not isinstance(draft, dict):
                continue
            body = str(draft.get("body") or "").strip()
            if not body:
                continue
            drafts.append({
                "to": str(draft.get("to") or "").strip()[:200],
                "subject": str(draft.get("subject") or "").strip()[:300],
                "body": body[:3000],
                "source": source["source"],
            })
        return {
            "source": source["source"],
            "error": None,
            "summary": str(data.get("summary") or "").strip()[:500],
            "action_items": items,
            "drafts": drafts,
        }

    @staticmethod
    def _render(mode: str, collected: List[Dict[str, Any]],
                workers: List[Dict[str, Any]]) -> str:
        available = [item["source"] for item in collected if not item.get("error")]
        unavailable = [item for item in collected if item.get("error")]
        items = [item for worker in workers for item in worker["action_items"]]
        drafts = [draft for worker in workers for draft in worker["drafts"]]
        lines = [f"Chief of staff — {'morning' if mode == 'morning' else 'evening'} triage"]
        lines.append("Sources: " + (", ".join(available) or "none available"))
        if unavailable:
            lines.append("Unavailable: " + ", ".join(
                f"{item['source']} ({item['error']})" for item in unavailable))
        summaries = [worker["summary"] for worker in workers if worker.get("summary")]
        if summaries:
            lines.append("Summary: " + " ".join(summaries)[:800])
        lines.append("")
        lines.append("Priority actions")
        if items:
            for index, item in enumerate(items[:10], start=1):
                due = f" — due {item['due']}" if item["due"] else ""
                link = f" — {item['link']}" if item["link"] else ""
                lines.append(
                    f"{index}. {item['text']} (source: {item['source']}{due}){link}")
        else:
            lines.append("- No source-linked action items were found.")
        lines.append("")
        lines.append("Drafts (not sent — approval required)")
        if drafts:
            for draft in drafts[:5]:
                lines.append(f"- To: {draft['to'] or '(unspecified)'} | "
                             f"Subject: {draft['subject'] or '(no subject)'}")
                lines.append("  " + draft["body"].replace("\n", "\n  "))
        else:
            lines.append("- No drafts suggested.")
        lines.append("")
        lines.append("Nothing was sent automatically. Review drafts before sending.")
        return "\n".join(lines)

    async def execute(self, request: TaskRequest) -> TaskResult:
        self._refresh_capabilities()
        mode = self._mode(request)
        self._reset_calls()
        self.emit_progress("chief_of_staff.start", mode=mode,
                           sources=len(self.sources))
        if not self.sources:
            text = ("No email, calendar or task connector is configured. "
                    "Add MCP tool names to the chief-of-staff `context_tools` config.")
            return TaskResult(
                text=text,
                data={"architecture": self.architecture,
                      "chief_of_staff": {"mode": mode, "sources": [],
                                         "unavailable": [], "action_items": [],
                                         "drafts": []}},
                stopped="final",
            )
        collected = await asyncio.gather(
            *(self._collect_one(source) for source in self.sources[:self.max_sources]))
        collected = list(collected)
        preferences = await self._preferences()
        workers = await asyncio.gather(
            *(self._extract(source, mode, preferences) for source in collected))
        workers = list(workers)
        # Validation bottleneck: drop anything without a source-linked text.
        valid_items = {worker["source"] for worker in workers}
        for worker in workers:
            worker["action_items"] = [
                item for item in worker.get("action_items", [])
                if item.get("source") in valid_items and item.get("text")]
        text = self._render(mode, collected, workers)
        items = [item for worker in workers for item in worker["action_items"]]
        drafts = [draft for worker in workers for draft in worker["drafts"]]
        self.emit_progress("chief_of_staff.ready", mode=mode,
                           actions=len(items), drafts=len(drafts))
        return TaskResult(
            text=text,
            data={
                "architecture": self.architecture,
                "response": text,
                "coordination": {
                    "architecture": self.architecture,
                    "workers": len(collected),
                    "rounds": 1,
                    "llm_calls": self._call_total(),
                    "profile": ARCHITECTURE_PROFILES[Architecture.CENTRALIZED],
                },
                "chief_of_staff": {
                    "mode": mode,
                    "sources": [item["source"] for item in collected
                                if not item.get("error")],
                    "unavailable": [
                        {"source": item["source"], "reason": item["error"]}
                        for item in collected if item.get("error")
                    ],
                    "action_items": items,
                    "drafts": drafts,
                    "sent": 0,
                    "preferences_used": bool(preferences),
                },
            },
            steps=workers,
            stopped="final",
        )
