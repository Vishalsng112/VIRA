"""Reusable LLM + tool-loop agent.

Subclass this instead of reimplementing discovery, prompting, the tool loop,
delegation and lesson learning.  ``ChatAgent`` is a thin subclass that only maps
chat events to responses; a developer can build a research, coding or support
agent the same way by setting a prompt and a tool policy.

Authoring::

    class Researcher(LLMAgent):
        name = "researcher"
        async def execute(self, request):
            result = await super().execute(request)
            result.data["citations"] = ...
            return result
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.base import BaseAgent, TaskRequest, TaskResult
from vira.agent.definitions import (
    AgentDefinition,
    definitions_version,
    load_definitions,
)
from vira.agent.lessons import LessonStore
from vira.agent.loop import AgentLoop, LoopConfig, LoopResult
from vira.agent.toolcalls import clip
from vira.agent.toolbox import ToolPolicy, Toolbox
from vira.tooling.catalog import ToolCatalog

DELEGATE = "delegate"

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "that", "this", "what", "how", "can", "you",
         "are", "was", "from", "have", "has", "not", "use", "tool", "tools", "get"}
_HEDGES = ("i don't know", "i do not know", "not sure", "i'm unable", "i am unable",
           "i cannot", "i can't", "no access", "don't have access", "as an ai",
           "i don't have information", "i do not have information")

TOOL_POLICY = (
    "TOOL POLICY (follow strictly):\n"
    "1. You have the tools listed below. Check them BEFORE answering.\n"
    "2. If a tool can fetch, compute, search or verify the answer, CALL IT. "
    "Never answer such questions from memory.\n"
    "3. If you are not fully sure your own knowledge is correct or current, call a relevant tool.\n"
    "4. Never say you cannot do something or lack access if a listed tool could do it.\n"
    "5. Answer directly only for greetings, chit-chat, or facts that are timeless and certain.\n"
    "6. After a tool returns, answer using its result. If it fails, try another tool or say what failed."
)


class LLMAgent(BaseAgent):
    """Prompt + tool loop + optional specialist delegation."""

    def __init__(self, runtime, **config: Any):
        merged = dict(config or {})
        super().__init__(
            name=merged.get("name") or getattr(self, "name", "LLMAgent"),
            description=merged.get("description") or (
                "LLM agent with a multi-step tool loop"),
            runtime=runtime,
            agent_id=merged.get("agent_id"),
            version=merged.get("version", "1.0.0"),
            **{key: value for key, value in merged.items()
               if key not in {"name", "description", "agent_id", "version"}},
        )
        self.config = merged
        self.system_prompt = merged.get("system_prompt") or (
            "You are VIRA, a helpful assistant running on the user's own machine. "
            "Be concise and accurate."
        )
        self.model = merged.get("model")
        self.temperature = float(merged.get("temperature", 0.7))
        self.max_tokens = int(merged.get("max_tokens", 1024))
        self.history_limit = int(merged.get("history_limit", 20))
        self.retry_on_miss = bool(merged.get("retry_on_miss", True))

        self.tool_policy = ToolPolicy.from_config(merged)
        self._toolbox = Toolbox(runtime, self.tool_policy)
        self.pinned_tools = self._toolbox.pinned
        self.allowed_tools = list(self.tool_policy.allow) if self.tool_policy.allow else None
        self.denied_tools = list(self.tool_policy.deny)

        tool_timeouts = merged.get("tool_timeouts")
        self.tool_timeouts = {
            str(name): float(value) for name, value in tool_timeouts.items()
        } if isinstance(tool_timeouts, dict) else {}
        self.loop_config = LoopConfig(
            max_steps=int(merged.get("max_steps", 6)),
            max_tool_chars=int(merged.get("max_tool_chars", 3000)),
            max_prompt_chars=int(merged.get("max_prompt_chars", 12000)),
            tool_timeout=float(merged.get("tool_timeout", 90)),
            tool_timeouts=self.tool_timeouts,
            max_total_tool_chars=int(merged.get("max_total_tool_chars", 30000)),
            max_seconds=float(merged.get("max_seconds", 240)),
            llm_timeout=float(merged.get("llm_timeout", 300)),
        )
        self.lessons = LessonStore(
            self,
            enabled=bool(merged.get("learn_lessons", True)),
            recall_limit=int(merged.get("lesson_recall_limit", 3)),
        )
        self._delegation = bool(merged.get("delegation", True))
        self._definitions_dir = merged.get("definitions_dir")
        self.definitions: Dict[str, AgentDefinition] = self._load_definitions()
        self._tools_version = self._registry_version()
        self._definitions_version = definitions_version()
        logger.info("[{}] tools={} sub-agents={}", self.name,
                    self._toolbox.names, list(self.definitions))

    # ------------------------------------------------------------ compatibility
    @property
    def available_tools(self) -> List[Dict[str, Any]]:
        return self._toolbox.specs

    @property
    def tool_catalog(self) -> ToolCatalog:
        return self._toolbox.catalog

    def _load_tools(self) -> List[Dict[str, Any]]:
        self._toolbox.refresh(force=True)
        return self._toolbox.specs

    def _tool_allowed(self, name: str) -> bool:
        return self.tool_policy.allows(name)

    def _registry_version(self) -> int:
        try:
            return self._toolbox.registry_version()
        except Exception:
            return 0

    def _refresh_capabilities(self) -> None:
        self._toolbox.refresh()
        version = definitions_version()
        if self._delegation and version != self._definitions_version:
            self.definitions = self._load_definitions()
            self._definitions_version = version
        self.pinned_tools = self._toolbox.pinned

    def _load_definitions(self) -> Dict[str, AgentDefinition]:
        if not self._delegation:
            return {}
        return load_definitions([self._definitions_dir] if self._definitions_dir else [])

    # ------------------------------------------------------------------ prompt
    @staticmethod
    def _tokens(text: str) -> set:
        return {word for word in _WORD.findall((text or "").lower())
                if word not in _STOP}

    def _suggest_tools(self, message: str, k: int = 3) -> List[tuple]:
        message_tokens = self._tokens(message)
        scored = []
        for tool in self._toolbox.specs:
            name_tokens = self._tokens(
                tool["name"].replace("_", " ").replace(".", " "))
            desc_tokens = self._tokens(tool.get("description", ""))
            score = 2 * len(message_tokens & name_tokens) + len(message_tokens & desc_tokens)
            if score:
                scored.append((score, tool["name"]))
        scored.sort(reverse=True)
        return [(name, score) for score, name in scored[:k]]

    def _tool_catalog(self, tools: Optional[List[Dict[str, Any]]] = None) -> str:
        lines = []
        for tool in (tools if tools is not None else self._toolbox.specs):
            params = tool.get("parameters") or {}
            properties = params.get("properties", params) if isinstance(params, dict) else {}
            args = ", ".join(properties.keys()) if isinstance(properties, dict) else ""
            lines.append(f"- {tool['name']}({args}): {tool.get('description', '')}")
        if self.definitions:
            roster = "; ".join(f"{d.name} ({d.description})"
                               for d in self.definitions.values())
            lines.append(f"- {DELEGATE}(agent, task): hand a task to a specialist: {roster}")
        return "\n".join(lines)

    def build_system_prompt(self, message: str,
                            tools: Optional[List[Dict[str, Any]]] = None) -> str:
        tools = tools if tools is not None else self._toolbox.specs
        if not tools and not self.definitions:
            return self.system_prompt
        parts = [self.system_prompt, TOOL_POLICY,
                 "AVAILABLE TOOLS:\n" + self._tool_catalog(tools)]
        hints = self._suggest_tools(message)
        if hints:
            parts.append("For this request, likely relevant tools: "
                         + ", ".join(name for name, _ in hints)
                         + ". Prefer calling one of them over answering from memory.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ tools
    def _progress(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("type", "event"))
        fields = {key: value for key, value in event.items() if key != "type"}
        self.emit_progress(event_type, **fields)

    def _delegate_spec(self) -> List[Dict[str, Any]]:
        if not self.definitions:
            return []
        roster = "; ".join(f"{d.name}: {d.description}"
                           for d in self.definitions.values())
        return [{
            "name": DELEGATE,
            "description": f"Hand a self-contained task to a specialist sub-agent. Available: {roster}",
            "parameters": {
                "properties": {
                    "agent": {"type": "string"},
                    "task": {"type": "string"},
                },
                "required": ["agent", "task"],
            },
        }]

    async def delegate(self, params: Dict[str, Any], request: TaskRequest) -> str:
        """Run a markdown-defined specialist with a fresh, small context."""
        definition = self.definitions.get(str(params.get("agent", "")))
        task = str(params.get("task", "")).strip()
        if definition is None:
            return f"ERROR: unknown agent. Available: {', '.join(self.definitions)}"
        if not task:
            return "ERROR: 'task' is required"
        allowed = definition.tools
        tools = [tool for tool in self._toolbox.specs
                 if allowed is None or tool["name"] in allowed]
        catalog = ToolCatalog(tools)
        selected = catalog.select(task, limit=8)
        loop = AgentLoop(
            self.runtime, self.agent_id, definition.prompt, selected,
            LoopConfig(
                max_steps=definition.max_steps,
                max_tool_chars=self.loop_config.max_tool_chars,
                max_prompt_chars=self.loop_config.max_prompt_chars,
                tool_timeout=self.loop_config.tool_timeout,
            ),
            model=definition.model or self.model,
            temperature=(definition.temperature
                         if definition.temperature is not None else self.temperature),
            max_tokens=self.max_tokens,
            on_event=self._progress, source=definition.name, catalog=catalog,
            resolve_specs=tools,
        )
        result = await loop.run(
            task, user_id=request.user_id, device_id=request.device_id,
            organization_id=request.organization_id, run_id=request.run_id)
        return clip(result.text, 2500)

    def _make_loop(self, message: str, request: TaskRequest,
                   history: List[Dict[str, Any]], lessons: List[str]) -> AgentLoop:
        hints = [name for name, _ in self._suggest_tools(message, 3)]
        available = set(self._toolbox.names)
        required = hints + [name for name in self.pinned_tools
                            if name in available and name not in hints]
        selected = self._toolbox.select(
            message, limit=max(8, len(required)), required=required)

        async def delegate(params: Dict[str, Any]) -> str:
            return await self.delegate(params, request)

        return AgentLoop(
            self.runtime, self.agent_id,
            self.build_system_prompt(message, selected), selected,
            self.loop_config,
            model=self.model, temperature=self.temperature,
            max_tokens=self.max_tokens,
            extra_tools={DELEGATE: delegate} if self.definitions else None,
            extra_specs=self._delegate_spec(),
            on_event=self._progress, catalog=self._toolbox.catalog,
            resolve_specs=self._toolbox.specs,
        )

    @staticmethod
    def _n_calls(result: LoopResult) -> int:
        calls = getattr(result, "tool_calls", 0)
        return calls if isinstance(calls, int) else len(calls or [])

    @staticmethod
    def _unanswered(text: Optional[str]) -> bool:
        value = (text or "").strip().lower()
        return len(value) < 2 or any(hedge in value for hedge in _HEDGES)

    async def execute(self, request: TaskRequest) -> TaskResult:
        message = request.message
        if not message.strip():
            raise ValueError(f"{self.name} received an empty message")
        self._refresh_capabilities()
        history = request.history or []
        lessons = await self.lessons.recall(request.user_id, message)

        result = await self._make_loop(message, request, history, lessons).run(
            message, history, lessons, request.user_id, request.device_id,
            request.organization_id, run_id=request.run_id,
            workspace=request.metadata.get("workspace"))

        # One retry when the model answered from memory despite an obvious tool.
        hints = self._suggest_tools(message)
        strong_hint = bool(hints) and hints[0][1] >= 3
        if (self.retry_on_miss and self._toolbox.names and self._n_calls(result) == 0
                and (self._unanswered(result.text) or strong_hint)):
            names = ", ".join(name for name, _ in hints) or ", ".join(self._toolbox.names[:5])
            logger.info("[{}] no tool used; retrying with nudge ({})", self.name, names)
            nudged = (
                f"{message}\n\n[System note: do not answer from memory. Call one of "
                f"these tools ({names}) to get or verify the answer, then reply "
                "using its result.]"
            )
            retry = await self._make_loop(
                nudged, request, history, lessons).run(
                    nudged, history, lessons, request.user_id, request.device_id,
                    request.organization_id, run_id=request.run_id,
                    workspace=request.metadata.get("workspace"))
            if self._n_calls(retry) > 0 or not self._unanswered(retry.text):
                result = retry

        text = (result.text or "").strip()
        if not text:
            text = ("I couldn't produce an answer for that. Please rephrase, "
                    "or tell me which tool/source to use.")
        logger.info("[{}] done: stopped={} tool_calls={}",
                    self.name, result.stopped, result.tool_calls)
        return TaskResult(
            text=text,
            data={"conversation_id": request.conversation_id},
            steps=result.steps,
            tool_calls=self._n_calls(result),
            stopped=result.stopped,
            raw=result,
        )

    async def after_run(self, request: TaskRequest, result: TaskResult) -> None:
        raw = result.raw
        if isinstance(raw, LoopResult) and request.user_id is not None:
            await self.lessons.learn(
                request.user_id, request.conversation_id,
                request.message, raw)
