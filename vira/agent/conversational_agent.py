"""Shared behaviour for agents that talk through the chat webpage.

Maps ``user.message`` events to tasks, keeps a bounded per-instance history
fallback, guarantees a response even on failure, and selects which chat agent
should answer a request.  `ChatAgent` is the shipped thin subclass.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from vira.agent.base import TaskRequest, TaskResult
from vira.agent.llm_agent import LLMAgent
from vira.agent_orchestration.registry import AgentCapability


class ConversationalAgent(LLMAgent):
    """Chat-facing agent base. Override prompts, tools and capabilities."""

    reentrant = True
    role = "chat"
    response_event = "agent.response"

    #: Subclass defaults (config overrides them).
    default_name = "ConversationalAgent"
    default_description = "Conversational AI agent with tool support"
    default_system_prompt = (
        "You are VIRA, a helpful assistant running on the user's own machine. "
        "Be concise and accurate."
    )
    capability_name = "chat"
    capability_description = "Respond to user messages using tools."
    #: When a request names no agent, only the default chat agent answers.
    is_default_agent = False

    def __init__(self, runtime, config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        merged = dict(config or {})
        merged.update(kwargs)
        merged.setdefault("name", self.default_name)
        merged.setdefault("description", self.default_description)
        merged.setdefault("system_prompt", self.default_system_prompt)
        super().__init__(runtime, **merged)

        self._subscribed_events = list(
            merged.get("subscribed_events") or ["user.message"])
        self._capabilities = [
            AgentCapability(
                name=self.capability_name,
                description=self.capability_description,
                input_schema={"type": "object",
                              "properties": {"message": {"type": "string"}}},
                output_schema={"type": "object",
                               "properties": {"response": {"type": "string"}}},
            )
        ]
        self._history_fallback: Optional[Dict[tuple, List[Dict[str, Any]]]] = (
            {} if merged.get("history_fallback", True) else None)
        self._history_cap = max(2, int(merged.get("history_limit", 20)))
        self._history_max_conversations = max(
            8, int(merged.get("history_max_conversations", 200)))

    # ------------------------------------------------------------ event routing
    async def accepts(self, event: Any) -> bool:
        """Route a chat request to one agent.

        ``event.data.agent_id`` may be an agent id, a name or a role.  Without a
        target only the default chat agent answers, so adding a specialist never
        produces duplicate replies.
        """
        data = event.get("data") if isinstance(event, dict) else getattr(event, "data", {})
        data = data if isinstance(data, dict) else {}
        target = data.get("agent_id") or data.get("agent")
        if target is None or target == "":
            return self.is_default_agent
        target = str(target)
        names = {self.agent_id, self.name, self.role,
                 str(self.config.get("agent_id") or ""),
                 str(self.config.get("slug") or "")}
        return target in names

    # ------------------------------------------------------------- event -> task
    def request_from_event(self, event: Any) -> TaskRequest:
        request = super().request_from_event(event)
        request.conversation_id = request.conversation_id or (
            f"ephemeral-{request.run_id or uuid.uuid4()}")
        if not request.history and self._history_fallback is not None:
            request.history = list(
                self._history_fallback.get(self._history_key(request), []))
        return request

    def _history_key(self, request: TaskRequest) -> tuple:
        return (request.user_id, request.conversation_id)

    def _remember_history(self, request: TaskRequest,
                          result: TaskResult) -> None:
        store = self._history_fallback
        if store is None or not request.message:
            return
        key = self._history_key(request)
        history = list(store.get(key, []))
        history += [
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": result.text},
        ]
        store[key] = history[-self._history_cap:]
        while len(store) > self._history_max_conversations:
            store.pop(next(iter(store)), None)

    # --------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> TaskResult:
        try:
            result = await super().execute(request)
        except Exception as exc:
            result = TaskResult(
                text=("I couldn't complete that request. "
                      f"{type(exc).__name__}: {exc}"),
                error=str(exc),
            )
        result.data.update({
            "conversation_id": request.conversation_id,
            "response": result.text,
            "tool_calls": result.tool_calls,
            "stopped": result.stopped,
        })
        return result

    async def on_error(self, request: TaskRequest, error: BaseException) -> None:
        await super().on_error(request, error)
        # Never leave the API waiting: a failed turn still gets a response.
        try:
            await self.respond(
                conversation_id=request.conversation_id,
                response=("I couldn't complete that request. "
                          f"{type(error).__name__}: {error}"),
                original_message=request.message,
                user_id=request.user_id,
                run_id=request.run_id,
            )
        except Exception:
            pass

    async def after_run(self, request: TaskRequest, result: TaskResult) -> None:
        await super().after_run(request, result)
        self._remember_history(request, result)
        await self.respond(
            conversation_id=request.conversation_id,
            response=result.text,
            original_message=request.message,
            user_id=request.user_id,
            run_id=request.run_id,
            tool_calls=result.tool_calls,
            stopped=result.stopped,
        )
