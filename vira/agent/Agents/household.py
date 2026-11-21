"""Household and life admin agent over the shared family store.

Morning and evening modes use one reasoning loop. The weekly review fans out
meals, budget and chores to parallel workers and then merges them, recording a
centralized coordination profile. All household reads go through the
membership-checked family store.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.architectures import (
    Architecture,
    ARCHITECTURE_PROFILES,
)
from vira.agent.base import TaskRequest, TaskResult
from vira.agent.conversational_agent import ConversationalAgent
from vira.family import store as family_store

DEFAULT_SYSTEM_PROMPT = (
    "You are VIRA's household operations assistant. You help a household plan "
    "meals, chores, bills and reminders from the shared notes below. Be concise, "
    "practical and never invent due dates or tasks."
)

MODE_INSTRUCTIONS = {
    "morning": (
        "Write today's household plan: the most important reminders, open chores, "
        "and one meal suggestion. Keep it short."
    ),
    "evening": (
        "Write a short evening check: what is still open, what is due tomorrow, "
        "and one thing to prepare tonight."
    ),
    "weekly": (
        "Write the weekly household review: meals, budget/bills and chores. "
        "Highlight what is overdue and suggest three small actions for next week."
    ),
}

WEEKLY_WORKERS = {
    "meals": "Focus only on meals, groceries and food notes. Suggest a simple plan.",
    "budget": "Focus only on bills, subscriptions, budget notes and due payments.",
    "chores": "Focus only on chores, checklists and household reminders.",
}


class HouseholdAgent(ConversationalAgent):
    """Morning/evening household plan and weekly review over shared data."""

    name = "HouseholdAgent"
    role = "household"
    description = (
        "Plan household meals, chores, bills and reminders from the shared "
        "family store. Weekly reviews fan out to parallel workers."
    )
    architecture = Architecture.SINGLE.value
    default_name = "HouseholdAgent"
    default_description = (
        "Shared household planning, chores, bills and weekly reviews.")
    default_system_prompt = DEFAULT_SYSTEM_PROMPT
    capability_name = "household"
    capability_description = (
        "Plan household meals, chores, bills and reminders.")
    is_default_agent = False

    def __init__(self, runtime, **config: Any):
        merged = dict(config or {})
        merged.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
        merged.setdefault("max_tokens", 800)
        merged.setdefault("temperature", 0.2)
        merged.setdefault("delegation", False)
        super().__init__(runtime, **merged)
        self.default_mode = str(merged.get("mode") or "morning")
        self.household_id = str(merged.get("household_id") or "")
        self.max_words = max(80, min(int(merged.get("max_words", 240)), 600))

    # ------------------------------------------------------------------ mode
    def _mode(self, request: TaskRequest) -> str:
        raw = ""
        if isinstance(request.input, dict):
            raw = str(request.input.get("mode") or "")
        raw = raw or str(request.metadata.get("mode") or "") or self.default_mode
        if raw in MODE_INSTRUCTIONS:
            return raw
        text = request.message.lower()
        if "week" in text:
            return "weekly"
        if "evening" in text or "tonight" in text:
            return "evening"
        return "morning"

    def _household_id(self, request: TaskRequest) -> str:
        if self.household_id:
            return self.household_id
        if isinstance(request.input, dict) and request.input.get("household_id"):
            return str(request.input["household_id"])
        return ""

    # ------------------------------------------------------------ collection
    def _snapshot(self, request: TaskRequest) -> Dict[str, Any]:
        household_id = self._household_id(request)
        if not household_id:
            household_id = family_store.default_household(int(request.user_id))["id"]
        return family_store.household_snapshot(int(request.user_id), household_id)

    @staticmethod
    def _due_soon(reminders: List[Dict[str, Any]], days: int = 2) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) + timedelta(days=days)
        result = []
        for reminder in reminders:
            try:
                due = datetime.fromisoformat(
                    str(reminder.get("due_at") or "").replace("Z", "+00:00"))
            except ValueError:
                result.append(reminder)
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due <= cutoff:
                result.append(reminder)
        return result

    def _context_block(self, snapshot: Dict[str, Any], mode: str) -> str:
        reminders = snapshot["reminders"]
        if mode == "evening":
            reminders = self._due_soon(reminders, days=2)
        elif mode == "morning":
            reminders = self._due_soon(reminders, days=1)
        checklist = [item for item in snapshot["checklist"] if not item.get("done")]
        notes = snapshot["notes"][:20]
        blocks = [
            f"[household]\n{snapshot['household']['name']} "
            f"({snapshot['member_count']} member(s))\n[/household]",
            "[reminders]\n" + ("\n".join(
                f"- {item['title']} due {item['due_at']}"
                + (" (urgent)" if item.get("urgent") else "")
                for item in reminders) or "No upcoming reminders.")
            + "\n[/reminders]",
            "[chores]\n" + ("\n".join(
                f"- {item['text']} (list: {item.get('note_title') or 'household'})"
                for item in checklist) or "No open chores.")
            + "\n[/chores]",
            "[notes]\n" + ("\n\n".join(
                f"{item['title']}:\n{str(item.get('body_md') or '')[:1200]}"
                for item in notes) or "No household notes.")
            + "\n[/notes]",
        ]
        return "\n\n".join(blocks)

    def _prompt(self, request: TaskRequest, mode: str,
                snapshot: Dict[str, Any]) -> str:
        instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["morning"])
        return (
            f"System: {self.system_prompt}\n\n"
            f"MODE: {mode}\n{instruction}\n\n"
            "Rules:\n"
            "- Use only the shared household context below.\n"
            "- Never invent reminders, due dates or chores.\n"
            "- If something is unclear, say so briefly.\n"
            f"- Keep the answer under {self.max_words} words. Plain text.\n\n"
            f"USER REQUEST:\n{request.message or 'Plan the household day.'}\n\n"
            f"CONTEXT:\n{self._context_block(snapshot, mode)}"
        )

    def _fallback(self, mode: str, snapshot: Dict[str, Any]) -> str:
        title = {"morning": "Household plan", "evening": "Evening check",
                 "weekly": "Weekly household review"}.get(mode, "Household update")
        reminders = self._due_soon(snapshot["reminders"], days=7)
        open_chores = [item for item in snapshot["checklist"] if not item.get("done")]
        lines = [title,
                 f"- Reminders: {len(reminders)} upcoming",
                 f"- Open chores: {len(open_chores)}",
                 f"- Notes: {len(snapshot['notes'])}"]
        for item in reminders[:5]:
            lines.append(f"- {item['title']} due {item['due_at']}")
        for item in open_chores[:5]:
            lines.append(f"- Chore: {item['text']}")
        if not reminders and not open_chores:
            lines.append("- Nothing urgent in the shared household data.")
        return "\n".join(lines)

    # -------------------------------------------------------------- weekly
    async def _weekly(self, request: TaskRequest,
                      snapshot: Dict[str, Any]) -> TaskResult:
        context = self._context_block(snapshot, "weekly")
        prompts = [
            (name, f"System: {self.system_prompt}\n\n{instruction}\n\n"
                   f"HOUSEHOLD CONTEXT:\n{context}")
            for name, instruction in WEEKLY_WORKERS.items()
        ]
        results = await asyncio.gather(
            *(self.ask_llm(prompt, model=self.model,
                           temperature=self.temperature,
                           max_tokens=min(500, self.max_tokens))
              for _, prompt in prompts),
            return_exceptions=True,
        )
        sections = []
        failed = []
        for (name, _), value in zip(prompts, results):
            if isinstance(value, BaseException):
                failed.append(name)
                continue
            text = str(getattr(value, "text", value) or "").strip()
            if text:
                sections.append(f"{name.title()}\n{text}")
        if not sections:
            text = self._fallback("weekly", snapshot)
            generated_by = "fallback"
        else:
            text = "Weekly household review\n\n" + "\n\n".join(sections)
            generated_by = "workers"
        if failed:
            text += "\n\nUnavailable sections: " + ", ".join(failed)
        self.emit_progress("household.weekly", workers=len(prompts),
                           failed=len(failed))
        return TaskResult(
            text=text,
            data={
                "architecture": Architecture.CENTRALIZED.value,
                "response": text,
                "coordination": {
                    "architecture": Architecture.CENTRALIZED.value,
                    "workers": len(prompts),
                    "rounds": 1,
                    "failed_workers": failed,
                    "profile": ARCHITECTURE_PROFILES[Architecture.CENTRALIZED],
                },
                "household": {
                    "mode": "weekly",
                    "household_id": snapshot["household"]["id"],
                    "generated_by": generated_by,
                    "reminders": len(snapshot["reminders"]),
                    "open_chores": len([item for item in snapshot["checklist"]
                                        if not item.get("done")]),
                },
            },
            stopped="final",
        )

    # ------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> TaskResult:
        self._refresh_capabilities()
        mode = self._mode(request)
        self.emit_progress("household.start", mode=mode)
        try:
            snapshot = self._snapshot(request)
        except PermissionError as exc:
            text = f"Household access denied: {exc}"
            return TaskResult(
                text=text,
                data={"architecture": self.architecture,
                      "household": {"mode": mode, "error": "permission_denied"}},
                error=str(exc),
            )
        except Exception as exc:
            logger.warning("[{}] household read failed: {}", self.name, exc)
            text = f"Household data is unavailable: {type(exc).__name__}: {exc}"
            return TaskResult(
                text=text,
                data={"architecture": self.architecture,
                      "household": {"mode": mode, "error": "unavailable"}},
                error=str(exc),
            )
        if mode == "weekly":
            return await self._weekly(request, snapshot)

        generated_by = "llm"
        text = ""
        try:
            text = str(await self.ask_llm(
                self._prompt(request, mode, snapshot),
                model=self.model, temperature=self.temperature,
                max_tokens=self.max_tokens) or "").strip()
        except Exception as exc:
            logger.warning("[{}] household generation failed: {}", self.name, exc)
        if not text:
            generated_by = "fallback"
            text = self._fallback(mode, snapshot)
        self.emit_progress("household.ready", mode=mode,
                           generated_by=generated_by)
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
                "household": {
                    "mode": mode,
                    "household_id": snapshot["household"]["id"],
                    "generated_by": generated_by,
                    "reminders": len(snapshot["reminders"]),
                    "open_chores": len([item for item in snapshot["checklist"]
                                        if not item.get("done")]),
                },
            },
            stopped="final",
        )
