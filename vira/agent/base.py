"""Canonical base class for every VIRA agent.

Agents are written by subclassing :class:`BaseAgent` and implementing
:meth:`execute`.  The framework owns everything else: identity, lifecycle,
state, errors, tools (local and MCP), memory, knowledge, progress and events.

A minimal agent::

    class Greeter(BaseAgent):
        name = "greeter"
        async def execute(self, request):
            return f"Hello {request.input}"

    agent = Greeter(runtime)
    await agent.initialize()
    await agent.start()
    result = await agent.run("world")   # -> "Hello world"

What the base class provides to every agent:

* lifecycle hooks (``setup``, ``on_start``, ``on_stop``, ``on_error``)
* per-task identity in context variables (user, device, organisation, run)
* a filtered :class:`~vira.agent.toolbox.Toolbox` for local **and** MCP tools
* helpers for LLM calls, tools, memory, knowledge, progress and responses
* safe concurrency for re-entrant agents (chat) and serialised execution for
  stateful agents (sensors)
* a typed :class:`TaskRequest` / :class:`TaskResult` contract usable by events,
  workflows and HTTP APIs
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent import runtime_context
from vira.agent.toolbox import Toolbox, ToolPolicy
from vira.agent_orchestration.registry import AgentCapability, AgentState


def _event_type(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("type", ""))
    return str(getattr(event, "type", ""))


def _event_data(event: Any) -> Dict[str, Any]:
    data = event.get("data") if isinstance(event, dict) else getattr(event, "data", None)
    return data if isinstance(data, dict) else {}


def _event_attr(event: Any, name: str, default=None):
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


@dataclass
class TaskRequest:
    """Everything an agent needs for one unit of work."""

    input: Any = None
    event: Any = None
    user_id: Optional[int] = None
    organization_id: Optional[str] = None
    conversation_id: Optional[str] = None
    device_id: Optional[str] = None
    run_id: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None
    context: Any = None

    @classmethod
    def from_event(cls, event: Any, **overrides) -> "TaskRequest":
        data = _event_data(event)
        request = cls(
            input=data or None,
            event=event,
            user_id=data.get("user_id") or _event_attr(event, "actor_user_id"),
            organization_id=data.get("organization_id") or data.get("org_id"),
            conversation_id=data.get("conversation_id"),
            device_id=data.get("device_id") or _event_attr(event, "device_id"),
            run_id=data.get("run_id"),
            history=list(data.get("history") or []),
            metadata={k: v for k, v in data.items()
                      if k not in {"message", "history", "user_id", "device_id",
                                   "organization_id", "org_id", "conversation_id",
                                   "run_id"}},
        )
        for key, value in overrides.items():
            setattr(request, key, value)
        return request

    @property
    def message(self) -> str:
        if isinstance(self.input, dict):
            value = self.input.get("message") or self.input.get("text")
            if value is not None:
                return str(value)
        return "" if self.input is None else str(self.input)


@dataclass
class TaskResult:
    """Normalised outcome of one task, independent of the agent style."""

    text: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    steps: List[Any] = field(default_factory=list)
    tool_calls: int = 0
    stopped: str = "final"
    error: Optional[str] = None
    duration_ms: float = 0.0
    raw: Any = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_event_data(self) -> Dict[str, Any]:
        return {**self.data, "response": self.text}

    def __str__(self) -> str:
        return self.text


class BaseAgent:
    """Framework base for all agents (see module docstring)."""

    #: Re-entrant agents may serve several users concurrently.  Chat is
    #: re-entrant; sensor/stateful agents are serialised by the scheduler.
    reentrant: bool = False
    #: Event emitted by :meth:`respond`.
    response_event: str = "agent.response"
    #: Stable role name used for knowledge scoping (overridable per instance).
    role: Optional[str] = None
    #: Coordination architecture exposed to the catalog and API.
    architecture: str = "single"

    def __init__(
        self,
        name: str,
        description: str = "",
        runtime: Optional[Any] = None,
        agent_id: Optional[str] = None,
        version: str = "1.0.0",
        **config: Any,
    ):
        self.agent_id = agent_id or str(uuid.uuid4())
        self.name = name
        self.description = description
        self.version = version
        self.runtime = runtime
        self.config: Dict[str, Any] = dict(config)
        self.role = self.config.get("role") or self.role
        self.state = AgentState.INITIALIZED

        self._capabilities: List[AgentCapability] = []
        self._subscribed_events: List[str] = list(
            self.config.get("subscribed_events") or [])
        self._interval_seconds: Optional[float] = self.config.get("interval_seconds")
        self._active = 0
        self._initialised = False
        self._toolbox: Optional[Toolbox] = None

    # ------------------------------------------------------------- properties
    @property
    def capabilities(self) -> List[AgentCapability]:
        return self._capabilities

    @property
    def subscribed_events(self) -> List[str]:
        return self._subscribed_events

    @property
    def interval_seconds(self) -> Optional[float]:
        return self._interval_seconds

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {"type": "object"}

    @property
    def tools(self) -> Toolbox:
        if self._toolbox is None:
            self._toolbox = Toolbox(self.runtime, ToolPolicy.from_config(self.config))
        return self._toolbox

    def describe(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role or self.name,
            "description": self.description,
            "version": self.version,
            "state": getattr(self.state, "value", str(self.state)),
            "architecture": self.architecture,
            "reentrant": self.reentrant,
            "capabilities": [cap.model_dump() if hasattr(cap, "model_dump") else cap.name
                             for cap in self._capabilities],
            "subscribed_events": list(self._subscribed_events),
            "tools": self.tools.describe() if self.runtime is not None else None,
        }

    # --------------------------------------------------------------- lifecycle
    async def initialize(self) -> None:
        """Called once after registration. Idempotent."""
        if self._initialised:
            return
        if type(self).execute is BaseAgent.execute:
            raise NotImplementedError(
                f"{type(self).__name__} must implement async execute(request)")
        await self.setup()
        self._initialised = True
        self.state = AgentState.INITIALIZED

    async def start(self) -> None:
        await self.on_start()
        self.state = AgentState.READY

    async def stop(self) -> None:
        try:
            await self.on_stop()
        finally:
            self.state = AgentState.TERMINATED

    # Lifecycle hooks -------------------------------------------------------
    async def setup(self) -> None:
        """Create resources. Runs once before ``start``."""

    async def on_start(self) -> None:
        """Runs when the agent becomes READY."""

    async def on_stop(self) -> None:
        """Release resources. Runs once when the agent terminates."""

    async def on_error(self, request: TaskRequest, error: BaseException) -> None:
        """Observe a failed task; the default logs and leaves policy to callers."""
        logger.error("[{}] task failed: {}", self.name, error)

    async def before_run(self, request: TaskRequest) -> None:
        """Hook before :meth:`execute`."""

    async def after_run(self, request: TaskRequest, result: TaskResult) -> None:
        """Hook after a successful :meth:`execute`."""

    # ---------------------------------------------------------------- handling
    async def can_handle(self, event: Any) -> bool:
        """Default: subscribed event types (``*`` supported) plus a custom filter."""
        event_type = _event_type(event)
        if not (event_type in self._subscribed_events or "*" in self._subscribed_events):
            return False
        return await self.accepts(event)

    async def accepts(self, event: Any) -> bool:
        """Optional custom filter; return False to decline a subscribed event."""
        return True

    def request_from_event(self, event: Any) -> TaskRequest:
        """Map a kernel ``Event`` / ``AgentMessage`` to a task request."""
        return TaskRequest.from_event(event)

    async def handle(self, event: Any) -> TaskResult:
        """Event-driven entry point used by the router/scheduler."""
        return await self.run_task(self.request_from_event(event))

    async def run(self, input_data: Any = None) -> Any:
        """Task entry point used by workflows; returns the raw execute value."""
        result = await self.run_task(TaskRequest(input=input_data))
        return result.raw if result.raw is not None else (result.data or result.text)

    async def run_task(self, request: TaskRequest) -> TaskResult:
        """Execute one task with lifecycle, identity and error handling."""
        started = time.perf_counter()
        if not self.reentrant:
            self.state = AgentState.RUNNING
        self._active += 1
        token = runtime_context.current_request.set(request)
        try:
            if self.runtime is not None and hasattr(self.runtime, "get_context"):
                try:
                    request.context = await self.runtime.get_context(self.agent_id)
                except Exception as exc:  # context is best effort
                    logger.debug("[{}] context refresh failed: {}", self.name, exc)
            await self.before_run(request)
            raw = await self.execute(request)
            result = self.normalize(raw, started)
            await self.after_run(request, result)
            return result
        except Exception as exc:
            # A single failed conversation must not take a re-entrant agent
            # (chat) out of service for everyone else.
            if not self.reentrant:
                self.state = AgentState.FAILED
            await self.on_error(request, exc)
            return TaskResult(
                text="", error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        finally:
            runtime_context.current_request.reset(token)
            self._active = max(0, self._active - 1)
            if self.state != AgentState.TERMINATED:
                if self.reentrant:
                    self.state = (AgentState.READY if self._active == 0
                                  else AgentState.RUNNING)
                elif self.state != AgentState.FAILED:
                    self.state = AgentState.READY

    # ------------------------------------------------------------- execution
    async def execute(self, request: TaskRequest) -> Any:
        """Execute one task. Every agent must implement this method.

        Return a string, a dict (``{"response": ...}`` is recognised), or a
        :class:`TaskResult`.  Raising is safe: ``run_task`` records the error and
        calls :meth:`on_error`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement async execute(request)")

    # Legacy pipeline (override as needed; not required for task-style agents)
    async def think(self, context: Optional[AgentContext], **kwargs) -> Dict[str, Any]:
        return {"input": kwargs.get("input") or kwargs.get("event")}

    async def plan(self, thought: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
        return []

    async def act(self, plan: List[Dict[str, Any]], **kwargs) -> Any:
        return plan

    async def reflect(self, result: Any, **kwargs) -> Dict[str, Any]:
        return {"result": result}

    def normalize(self, raw: Any, started: float) -> TaskResult:
        """Convert any execute/act return value into a TaskResult."""
        duration = (time.perf_counter() - started) * 1000
        if isinstance(raw, TaskResult):
            raw.duration_ms = raw.duration_ms or duration
            raw.raw = raw.raw if raw.raw is not None else raw.data
            return raw
        # Duck-type LoopResult without importing the loop here.
        if hasattr(raw, "steps") and hasattr(raw, "text"):
            return TaskResult(
                text=str(getattr(raw, "text", "") or ""),
                data={"stopped": getattr(raw, "stopped", "final")},
                steps=list(getattr(raw, "steps", []) or []),
                tool_calls=int(getattr(raw, "tool_calls", 0) or 0),
                stopped=str(getattr(raw, "stopped", "final")),
                duration_ms=duration, raw=raw,
            )
        if isinstance(raw, str):
            return TaskResult(text=raw, duration_ms=duration, raw=raw)
        if isinstance(raw, dict):
            text = raw.get("response") or raw.get("text") or ""
            return TaskResult(text=str(text or ""), data=raw,
                              duration_ms=duration, raw=raw)
        if raw is None:
            return TaskResult(duration_ms=duration, raw=None)
        return TaskResult(text=str(raw), duration_ms=duration, raw=raw)

    # ----------------------------------------------------------------- helpers
    def current_request(self) -> Optional[TaskRequest]:
        return runtime_context.current()

    async def call_llm(self, prompt: str, **kwargs: Any) -> Any:
        """Call the runtime LLM with the current task identity."""
        if self.runtime is None:
            raise RuntimeError(f"{self.name} has no runtime")
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("organization_id", request.organization_id)
        return await self.runtime.call_llm(self.agent_id, prompt, **kwargs)

    async def ask_llm(self, prompt: str, **kwargs: Any) -> str:
        response = await self.call_llm(prompt, **kwargs)
        if hasattr(response, "text"):
            return response.text or ""
        if isinstance(response, dict):
            return str(response.get("text", ""))
        return str(response)

    async def call_tool(self, name: str, **params: Any) -> Any:
        """Call a tool with identity injection for local tools.

        MCP tools receive only declared arguments; local tools receive the
        authenticated caller so they cannot be used without identity.
        """
        request = self.current_request()
        if request is not None and "." not in name:
            params.setdefault("user_id", request.user_id)
            if request.device_id:
                params.setdefault("device_id", request.device_id)
            if request.metadata.get("workspace"):
                params.setdefault("workspace", request.metadata["workspace"])
        return await self.tools.call(self.agent_id, name, **params)

    def emit_progress(self, event_type: str, **fields: Any) -> None:
        """Record a run event for the UI and the durable timeline."""
        request = self.current_request()
        run_id = request.run_id if request else None
        if not run_id:
            return
        event = {"type": event_type, "ts": time.time(), **fields}
        try:
            from vira.agent.progress import hub
            from vira.agent_runtime import run_store
            hub.emit(run_id, event)
            run_store.append(run_id, event_type, event)
        except Exception as exc:  # progress must never break a task
            logger.debug("[{}] progress event failed: {}", self.name, exc)

    async def respond(self, **data: Any) -> None:
        """Emit this agent's response event to the requesting caller."""
        request = self.current_request()
        payload = dict(data)
        if request is not None:
            payload.setdefault("user_id", request.user_id)
            payload.setdefault("run_id", request.run_id)
            payload.setdefault("conversation_id", request.conversation_id)
        await self.send_event(self.response_event, payload)

    async def remember(self, content: str, **kwargs: Any) -> Any:
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("conversation_id", request.conversation_id)
        return await self.runtime.memory_operation(
            self.agent_id, "store", content=content, **kwargs)

    async def recall(self, query: str, **kwargs: Any) -> List[Any]:
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("conversation_id", request.conversation_id)
        items = await self.runtime.memory_operation(
            self.agent_id, "retrieve", query=query, **kwargs)
        return list(items or [])

    async def knowledge_search(self, query: str, **kwargs: Any):
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("agent_role", self.role or self.name)
            kwargs.setdefault("conversation_id", request.conversation_id)
            kwargs.setdefault("organization_id", request.organization_id)
        return await self.runtime.knowledge_search(self.agent_id, query, **kwargs)

    async def knowledge_write(self, content: str, **kwargs: Any):
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("agent_role", self.role or self.name)
            kwargs.setdefault("conversation_id", request.conversation_id)
            kwargs.setdefault("organization_id", request.organization_id)
        return await self.runtime.knowledge_write(self.agent_id, content, **kwargs)

    async def knowledge_list(self, **kwargs: Any) -> List[Any]:
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("agent_role", self.role or self.name)
            kwargs.setdefault("conversation_id", request.conversation_id)
            kwargs.setdefault("organization_id", request.organization_id)
        return list(await self.runtime.knowledge_list(self.agent_id, **kwargs))

    async def knowledge_correct(self, item_id: str, content: str, **kwargs: Any):
        request = self.current_request()
        if request is not None:
            kwargs.setdefault("user_id", request.user_id)
            kwargs.setdefault("agent_role", self.role or self.name)
            kwargs.setdefault("organization_id", request.organization_id)
        return await self.runtime.knowledge_correct(
            self.agent_id, item_id, content, **kwargs)

    async def send_event(self, event_type: str, data: Any,
                         target_agent_ids: Optional[List[str]] = None) -> None:
        if self.runtime is None:
            raise RuntimeError("Runtime not set")
        await self.runtime.send_agent_message(
            sender_agent_id=self.agent_id,
            event_type=event_type,
            data=data,
            target_agent_ids=target_agent_ids,
        )

    def set_capabilities(self, capabilities: List[AgentCapability]) -> None:
        self._capabilities = list(capabilities)

    def health(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "state": getattr(self.state, "value", str(self.state)),
            "active_tasks": self._active,
            "initialised": self._initialised,
        }
