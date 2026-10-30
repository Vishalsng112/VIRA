"""Self-improvement: turn mistakes the loop made into lessons the next run sees.

No extra LLM call is needed (cheap for local models): lessons are derived
from the run trace.  Most valuable is the "recovery" lesson - a tool call that
failed and was later fixed - because it records exactly which params work.
Lessons are stored per user through the normal memory API (memory_type="lesson").
"""
from typing import Any, Dict, List, Optional

from vira.agent.loop import LoopResult
from vira.agent.toolcalls import clip

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

LESSON_TYPE = "lesson"


def _brief(params: Dict[str, Any]) -> str:
    return "{" + ", ".join(f"{k}={clip(str(v), 80)!r}" for k, v in list(params.items())[:4]) + "}"


def derive_lessons(user_message: str, result: LoopResult, max_lessons: int = 3) -> List[str]:
    lessons: List[str] = []
    steps = result.steps
    for i, s in enumerate(steps):
        if s.kind == "tool" and not s.ok:
            err = clip(s.observation.removeprefix("ERROR: "), 140)
            fix = next((t for t in steps[i + 1:] if t.kind == "tool" and t.ok and t.tool == s.tool), None)
            if fix:
                lessons.append(f"Tool '{s.tool}' failed with \"{err}\" for {_brief(s.params)}; "
                               f"it worked with {_brief(fix.params)}.")
            else:
                lessons.append(f"Tool '{s.tool}' failed with \"{err}\" for {_brief(s.params)}; "
                               "adjust the params or use another approach.")
        elif s.kind == "unknown_tool":
            lessons.append(f"'{s.tool}' is not a tool; only call tools from the Tools list.")
    if result.stopped == "max_steps":
        lessons.append(f"Ran out of steps on a task like \"{clip(user_message, 80)}\"; "
                       "use fewer, more targeted tool calls and answer sooner.")
    unique = list(dict.fromkeys(lessons))
    return unique[:max_lessons]


class LessonStore:
    def __init__(self, runtime, agent_id: str, enabled: bool = True, recall_limit: int = 3):
        self.runtime, self.agent_id = runtime, agent_id
        self.enabled, self.recall_limit = enabled, recall_limit

    async def recall(self, user_id: Optional[int], query: str) -> List[str]:
        if not self.enabled or user_id is None:
            return []
        try:
            items = await self.runtime.memory_operation(
                self.agent_id, "retrieve", query=query, user_id=user_id,
                memory_type=LESSON_TYPE, limit=self.recall_limit,
            )
            return [getattr(i, "content", str(i)) for i in (items or [])][: self.recall_limit]
        except Exception as exc:  # memory must never break a chat turn
            logger.debug(f"lesson recall skipped: {exc}")
            return []

    async def learn(self, user_id: Optional[int], conversation_id: Optional[str],
                    user_message: str, result: LoopResult, known: Optional[List[str]] = None) -> int:
        if not self.enabled or user_id is None:
            return 0
        known = known or []
        stored = 0
        for lesson in derive_lessons(user_message, result):
            if any(lesson[:60] == k[:60] for k in known):
                continue  # already learned
            try:
                await self.runtime.memory_operation(
                    self.agent_id, "store", content=lesson, user_id=user_id,
                    conversation_id=conversation_id, memory_type=LESSON_TYPE,
                    metadata={"type": "agent_lesson", "stopped": result.stopped}, importance=0.6,
                )
                stored += 1
            except Exception as exc:
                logger.debug(f"lesson store skipped: {exc}")
        return stored
