"""Focus and Wellbeing Coach: measured, private daily coaching.

Modes are selected by the schedule payload (``input.mode``):
``morning``, ``checkin``, ``evening`` or ``weekly``. Recommendations are
grounded in the ``insights``/``user_context`` tools and memory of the user's
goals. Weekly reports hide app names by default.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.architectures import Architecture, ARCHITECTURE_PROFILES, SingleAgent
from vira.agent.base import TaskRequest, TaskResult
from vira.agent.tool_output import tool_error, tool_text

MODES = ("morning", "checkin", "evening", "weekly")

DEFAULT_SYSTEM_PROMPT = (
    "You are VIRA's focus and wellbeing coach. You are practical, calm and "
    "non-judgemental. You only use measured context and never invent numbers."
)

MODE_INSTRUCTIONS = {
    "morning": (
        "Write a compact focus plan for today. Include: (1) one sentence on the "
        "pattern visible in the context, (2) 2-4 focus blocks with durations, "
        "(3) one break rule. Cite at least one measured number."
    ),
    "checkin": (
        "Write a two-sentence mid-day check-in: one observation from today's "
        "measured context and one concrete nudge. If the data is insufficient, "
        "say so instead of guessing."
    ),
    "evening": (
        "Write an evening review with: what happened (with numbers), one win, "
        "one adjustment for tomorrow, and tomorrow's first focus block."
    ),
    "weekly": (
        "Write a weekly focus report with: totals for the week, category balance, "
        "one pattern, and exactly three recommendations. Do not name specific "
        "apps. Cite measured numbers."
    ),
}


class FocusCoachAgent(SingleAgent):
    """Daily focus plan, check-in, evening review and weekly report."""

    name = "FocusCoachAgent"
    role = "focus-coach"
    description = (
        "Measured focus coaching from device usage, focus sessions, battery and "
        "wellbeing signals. Supports morning/checkin/evening/weekly modes."
    )
    architecture = Architecture.SINGLE.value

    def __init__(self, runtime, **config: Any):
        merged = dict(config or {})
        merged.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
        merged.setdefault("max_tokens", 700)
        merged.setdefault("temperature", 0.2)
        merged.setdefault("delegation", False)
        super().__init__(runtime, **merged)
        self.default_mode = str(merged.get("mode") or "evening")
        self.weekly_include_apps = bool(merged.get("weekly_include_apps", False))
        self.include_apps = bool(merged.get("include_apps", False))
        self.max_words = max(80, min(int(merged.get("max_words", 220)), 600))
        self.include_memory = bool(merged.get("include_memory", True))

    # ------------------------------------------------------------------ mode
    def _mode(self, request: TaskRequest) -> str:
        raw = ""
        if isinstance(request.input, dict):
            raw = str(request.input.get("mode") or "")
        raw = raw or str(request.metadata.get("mode") or "")
        raw = raw or self.default_mode
        if raw in MODES:
            return raw
        text = request.message.lower()
        if any(word in text for word in ("weekly", "week", "report")):
            return "weekly"
        if any(word in text for word in ("check-in", "checkin", "midday", "mid-day")):
            return "checkin"
        if any(word in text for word in ("plan", "morning")):
            return "morning"
        return "evening"

    def _days(self, mode: str) -> int:
        return 7 if mode in ("morning", "weekly") else 1

    def _include_apps(self, mode: str) -> bool:
        if mode == "weekly":
            return self.weekly_include_apps
        return self.include_apps

    # ------------------------------------------------------------ collection
    async def _collect(self, request: TaskRequest, mode: str) -> Dict[str, Any]:
        sources: List[Dict[str, Any]] = []
        unavailable: List[Dict[str, str]] = []

        tools = []
        if mode != "weekly":
            tools.append(("user_context", {}))
        tools.append(("insights", {"days": self._days(mode),
                                   "include_apps": self._include_apps(mode)}))
        for name, params in tools:
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
                    sources.append({"source": name, "text": text[:4000]})
            except Exception as exc:
                logger.warning("[{}] context tool {} failed: {}", self.name, name, exc)
                unavailable.append({
                    "source": name,
                    "reason": f"{type(exc).__name__}: {exc}"[:300],
                })

        if self.include_memory:
            try:
                memories = await self.recall("focus goals screen time limits", limit=5)
                texts = [str(getattr(item, "content", "") or "").strip()
                         for item in memories or []]
                texts = [text for text in texts if text]
                if texts:
                    sources.append({"source": "goals", "text": "\n".join(texts)[:2000]})
            except Exception as exc:
                logger.debug("[{}] goal memory failed: {}", self.name, exc)

        return {"sources": sources, "unavailable": unavailable}

    def _context_block(self, collected: Dict[str, Any]) -> str:
        blocks = []
        for item in collected["sources"]:
            blocks.append(f"[{item['source']}]\n{item['text']}\n[/{item['source']}]")
        for item in collected["unavailable"]:
            blocks.append(
                f"[{item['source']}]\nUNAVAILABLE: {item['reason']}\n[/{item['source']}]")
        return "\n\n".join(blocks) or "(no measured context available)"

    def _prompt(self, request: TaskRequest, mode: str,
                collected: Dict[str, Any]) -> str:
        instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["evening"])
        return (
            f"System: {self.system_prompt}\n\n"
            f"MODE: {mode}\n{instruction}\n\n"
            "Rules:\n"
            "- Use ONLY the context below; never invent events, numbers or apps.\n"
            "- If a source says UNAVAILABLE, do not guess its contents.\n"
            f"- Keep the answer under {self.max_words} words. Plain text.\n"
            "- Recommendations must be specific to the measured context, not generic advice.\n\n"
            f"USER REQUEST:\n{request.message or 'Generate the focus update.'}\n\n"
            f"CONTEXT:\n{self._context_block(collected)}"
        )

    def _fallback(self, mode: str, collected: Dict[str, Any]) -> str:
        titles = {"morning": "Today's focus plan", "checkin": "Check-in",
                  "evening": "Evening review", "weekly": "Weekly focus report"}
        lines = [titles.get(mode, "Focus update")]
        for item in collected["sources"][:3]:
            text = " ".join(item["text"].split())
            lines.append(f"- {item['source'].replace('_', ' ').title()}: {text[:500]}")
        if not collected["sources"]:
            lines.append("- No measured usage data was available.")
        if collected["unavailable"]:
            lines.append("- Unavailable: " + ", ".join(
                item["source"] for item in collected["unavailable"]))
        if mode == "weekly":
            lines.append("- Tip: keep the week's data private; this report hides app names.")
        else:
            lines.append("- Next step: pick one focus block and protect it.")
        return "\n".join(lines)

    # ------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> TaskResult:
        self._refresh_capabilities()
        mode = self._mode(request)
        self.emit_progress("focus_coach.collect", mode=mode,
                           days=self._days(mode))
        collected = await self._collect(request, mode)
        self.emit_progress("focus_coach.context", mode=mode,
                           sources=[item["source"] for item in collected["sources"]],
                           unavailable=[item["source"] for item in collected["unavailable"]])
        generated_by = "llm"
        text = ""
        try:
            text = str(await self.ask_llm(
                self._prompt(request, mode, collected),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ) or "").strip()
        except Exception as exc:
            logger.warning("[{}] coaching generation failed: {}", self.name, exc)
        if not text:
            generated_by = "fallback"
            text = self._fallback(mode, collected)
        self.emit_progress("focus_coach.ready", mode=mode,
                           generated_by=generated_by, chars=len(text))
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
                "focus_coach": {
                    "mode": mode,
                    "generated_by": generated_by,
                    "include_apps": self._include_apps(mode),
                    "sources": [item["source"] for item in collected["sources"]],
                    "unavailable": collected["unavailable"],
                },
            },
            stopped="final",
        )
