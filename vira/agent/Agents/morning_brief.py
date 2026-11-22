"""Morning Brief agent: one short, evidence-grounded brief per day.

The agent pre-collects context from tools the user has granted, then asks the
LLM to synthesize it. Every section is either backed by a collected source or
explicitly labelled unavailable, so the model cannot silently invent calendar
events or device numbers. A deterministic fallback keeps the daily habit working
when the model is down.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.architectures import Architecture, ARCHITECTURE_PROFILES, SingleAgent
from vira.agent.base import TaskRequest, TaskResult
from vira.agent.tool_output import tool_error, tool_text


DEFAULT_SYSTEM_PROMPT = (
    "You write a short, calm morning brief for a user of a private, self-hosted "
    "assistant. You are accurate, concrete and brief. You never invent events, "
    "tasks, numbers or device names."
)

DEFAULT_CONTEXT_TOOLS = [
    {"name": "vira.context"},
    {"name": "vira.insights", "params": {"days": 1}},
]


class MorningBriefAgent(SingleAgent):
    """Daily brief over calendar, tasks, device/focus and memory context."""

    name = "MorningBriefAgent"
    role = "morning-brief"
    description = (
        "Generate a short daily brief from device, focus, memory and optional "
        "calendar/task sources. Labels missing sources instead of guessing."
    )
    architecture = Architecture.SINGLE.value

    def __init__(self, runtime, **config: Any):
        merged = dict(config or {})
        merged.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
        merged.setdefault("max_tokens", 700)
        merged.setdefault("temperature", 0.2)
        merged.setdefault("delegation", False)
        super().__init__(runtime, **merged)
        self.context_tools = self._normalize_tools(
            merged.get("context_tools") or DEFAULT_CONTEXT_TOOLS)
        self.lookback_days = max(1, min(int(merged.get("lookback_days", 1)), 30))
        self.max_words = max(80, min(int(merged.get("max_words", 220)), 600))
        self.max_actions = max(1, min(int(merged.get("max_actions", 3)), 5))
        self.include_memory = bool(merged.get("include_memory", True))
        self.include_knowledge = bool(merged.get("include_knowledge", False))
        self.max_source_chars = max(500, int(merged.get("max_source_chars", 4000)))

    @staticmethod
    def _normalize_tools(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return list(DEFAULT_CONTEXT_TOOLS)
        items = []
        for entry in value:
            if isinstance(entry, str):
                items.append({"name": entry, "params": {}})
            elif isinstance(entry, dict) and entry.get("name"):
                items.append({
                    "name": str(entry["name"]),
                    "params": dict(entry.get("params") or {}),
                })
        return items or list(DEFAULT_CONTEXT_TOOLS)

    # ------------------------------------------------------------ collection
    async def _collect(self, request: TaskRequest) -> Dict[str, Any]:
        sources: List[Dict[str, Any]] = []
        unavailable: List[Dict[str, str]] = []
        seen = set()
        for item in self.context_tools:
            name = item["name"]
            if name in seen:
                continue
            seen.add(name)
            params = dict(item.get("params") or {})
            if name == "vira.insights":
                params.setdefault("days", self.lookback_days)
            if not self.tool_policy.allows(name):
                unavailable.append({"source": name, "reason": "not allowed for this agent"})
                continue
            if self._toolbox.get(name) is None:
                unavailable.append({"source": name, "reason": "not installed"})
                continue
            try:
                result = await self.call_tool(name, **params)
                text = tool_text(result).strip()
                if tool_error(result):
                    unavailable.append({
                        "source": name,
                        "reason": text[:300] or "tool returned an error",
                    })
                elif not text:
                    unavailable.append({"source": name, "reason": "empty result"})
                else:
                    sources.append({"source": name, "text": text[:self.max_source_chars]})
            except Exception as exc:
                logger.warning("[{}] context tool {} failed: {}", self.name, name, exc)
                unavailable.append({
                    "source": name,
                    "reason": f"{type(exc).__name__}: {exc}"[:300],
                })

        if self.include_memory:
            try:
                memories = await self.recall("morning brief priorities", limit=5)
                texts = [str(getattr(item, "content", "") or "").strip()
                         for item in memories or []]
                texts = [text for text in texts if text]
                if texts:
                    sources.append({"source": "memory", "text": "\n".join(texts)[:2000]})
            except Exception as exc:
                logger.debug("[{}] memory context failed: {}", self.name, exc)

        if self.include_knowledge:
            try:
                items = await self.knowledge_search(
                    request.message or "morning priorities", limit=5)
                texts = [str(getattr(item, "content", "") or item).strip()
                         for item in items or []]
                texts = [text for text in texts if text]
                if texts:
                    sources.append({"source": "knowledge", "text": "\n".join(texts)[:3000]})
            except Exception as exc:
                logger.debug("[{}] knowledge context failed: {}", self.name, exc)

        return {"sources": sources, "unavailable": unavailable}

    def _context_block(self, collected: Dict[str, Any]) -> str:
        blocks = []
        for item in collected["sources"]:
            blocks.append(f"[{item['source']}]\n{item['text']}\n[/{item['source']}]")
        for item in collected["unavailable"]:
            blocks.append(
                f"[{item['source']}]\nUNAVAILABLE: {item['reason']}\n[/{item['source']}]")
        return "\n\n".join(blocks) or "(no context sources were available)"

    # --------------------------------------------------------------- prompts
    def _prompt(self, request: TaskRequest, collected: Dict[str, Any]) -> str:
        user_request = (request.message or "").strip() or "Generate today's brief."
        return (
            f"System: {self.system_prompt}\n\n"
            "Write a morning brief using ONLY the context below. Rules:\n"
            "- Never invent events, tasks, deadlines, numbers, apps or devices.\n"
            "- If a source says UNAVAILABLE, mention it briefly and move on.\n"
            "- The brief has three sections: Today, Device & focus, Do first.\n"
            f"- 'Do first' has at most {self.max_actions} concrete actions that are "
            "supported by the context. Use fewer rather than inventing one.\n"
            f"- Keep the whole brief under {self.max_words} words. Plain text.\n\n"
            "USER REQUEST:\n"
            f"{user_request}\n\n"
            "CONTEXT:\n"
            f"{self._context_block(collected)}"
        )

    def _fallback_brief(self, collected: Dict[str, Any]) -> str:
        lines = ["Morning brief"]
        sources = collected["sources"]
        if sources:
            for item in sources[:4]:
                text = " ".join(item["text"].split())
                lines.append(f"- {item['source'].replace('_', ' ').title()}: {text[:400]}")
        else:
            lines.append("- No context sources were available.")
        if collected["unavailable"]:
            missing = ", ".join(item["source"] for item in collected["unavailable"][:4])
            lines.append(f"- Unavailable: {missing}.")
        lines.append("")
        lines.append("Do first")
        lines.append("1. Review the context above.")
        lines.append("2. Pick the highest-priority item and start it.")
        return "\n".join(lines)

    # ------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> TaskResult:
        self._refresh_capabilities()
        self.emit_progress("morning_brief.collect",
                           tools=[item["name"] for item in self.context_tools])
        collected = await self._collect(request)
        self.emit_progress(
            "morning_brief.context",
            sources=[item["source"] for item in collected["sources"]],
            unavailable=[item["source"] for item in collected["unavailable"]],
        )

        generated_by = "llm"
        text = ""
        try:
            text = str(await self.ask_llm(
                self._prompt(request, collected),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ) or "").strip()
        except Exception as exc:
            logger.warning("[{}] brief generation failed: {}", self.name, exc)
        if not text:
            generated_by = "fallback"
            text = self._fallback_brief(collected)

        self.emit_progress("morning_brief.ready", generated_by=generated_by,
                           chars=len(text))
        return TaskResult(
            text=text,
            data={
                "architecture": Architecture.SINGLE.value,
                "response": text,
                "coordination": {
                    "architecture": Architecture.SINGLE.value,
                    "workers": 1,
                    "rounds": 0,
                    "profile": ARCHITECTURE_PROFILES[Architecture.SINGLE],
                },
                "morning_brief": {
                    "generated_by": generated_by,
                    "sources": [item["source"] for item in collected["sources"]],
                    "unavailable": collected["unavailable"],
                },
            },
            stopped="final",
        )
