# vira/agent/Agents/chat_agent.py
"""Chat agent: a Claude-style tool loop designed for local models.

Per message: recall lessons -> multi-step tool loop (AgentLoop) -> optional
delegation to markdown-defined sub-agents -> learn from mistakes -> answer.
"""
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.base import BaseAgent
from vira.agent.definitions import AgentDefinition, load_definitions
from vira.agent.lessons import LessonStore
from vira.agent.loop import AgentLoop, LoopConfig, LoopResult
from vira.agent.toolcalls import clip
from vira.agent_orchestration.registry import AgentCapability
from vira.agent_runtime.runtime import AgentContext

DELEGATE = "delegate"


class ChatAgent(BaseAgent):
    # Keeps no per-request instance state, so chats of different users/devices
    # run concurrently without leaking identity between requests.
    reentrant = True
    _conversation_histories: Dict[str, List[Dict]] = {}

    def __init__(self, runtime, config: Optional[Dict] = None, **kwargs):
        merged = dict(config or {})
        merged.update(kwargs)  # direct kwargs override config

        super().__init__(
            name=merged.get("name", "ChatAgent"),
            description=merged.get("description", "Conversational AI agent with tool support"),
            runtime=runtime,
            agent_id=merged.get("agent_id"),
        )
        self.config = merged
        self.system_prompt = merged.get("system_prompt") or (
            "You are VIRA, a helpful assistant running on the user's own machine. "
            "Be concise and accurate. Use tools when they help; otherwise answer directly."
        )
        self.model = merged.get("model")
        self.temperature = merged.get("temperature", 0.7)
        self.max_tokens = merged.get("max_tokens", 1024)
        self.history_limit = int(merged.get("history_limit", 20))
        self.loop_config = LoopConfig(
            max_steps=int(merged.get("max_steps", 6)),
            max_tool_chars=int(merged.get("max_tool_chars", 3000)),
            max_prompt_chars=int(merged.get("max_prompt_chars", 12000)),
            tool_timeout=float(merged.get("tool_timeout", 90)),
        )
        self.lessons = LessonStore(
            runtime, self.agent_id,
            enabled=bool(merged.get("learn_lessons", True)),
            recall_limit=int(merged.get("lesson_recall_limit", 3)),
        )
        self.definitions: Dict[str, AgentDefinition] = (
            load_definitions([merged["definitions_dir"]] if merged.get("definitions_dir") else [])
            if merged.get("delegation", True) else {}
        )
        self.available_tools = self._load_tools()
        logger.info(f"[{self.name}] tools={[t['name'] for t in self.available_tools]} "
                    f"sub-agents={list(self.definitions)}")

        self._subscribed_events = ["user.message"]
        self._capabilities = [
            AgentCapability(
                name="chat",
                description="Respond to user messages, using tools and sub-agents over several steps.",
                input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"response": {"type": "string"}}},
            )
        ]

    def _load_tools(self) -> List[Dict]:
        """Fetch tool metadata from the ToolExecutor."""
        try:
            executor = self.runtime.tool_executor
            if not executor:
                return []
            registry = getattr(executor, "_registry", None)
            tools = []
            for name in executor.list_tools():
                tool = registry.get(name) if registry else None
                tools.append({
                    "name": name,
                    "description": getattr(tool, "description", "No description"),
                    "parameters": tool.get_schema() if tool and hasattr(tool, "get_schema") else {},
                })
            return tools
        except AttributeError:
            logger.warning("ToolExecutor does not support listing tools. No tools loaded.")
            return []

    # ---- think: gather what the loop needs --------------------------------
    async def think(self, context: AgentContext, **kwargs) -> Dict:
        event = kwargs.get("event")
        if not event:
            raise ValueError("ChatAgent requires an event")
        message = event.data.get("message")
        if not message:
            raise ValueError("Event data missing 'message'")

        conversation_id = event.data.get("conversation_id") or str(uuid.uuid4())
        history = event.data.get("history")
        if history is None:
            history = self._conversation_histories.get(conversation_id, [])
        user_id = event.data.get("user_id")
        return {
            "conversation_id": conversation_id,
            "user_message": message,
            "history": history,
            "user_id": user_id,
            "lessons": await self.lessons.recall(user_id, message),
        }

    # ---- plan: pick the strategy ------------------------------------------
    async def plan(self, thought: Dict, **kwargs) -> List[Dict]:
        return [{"step": "agent_loop", "thought": thought}]

    # ---- act: run the loop -------------------------------------------------
    def _delegate_spec(self) -> List[Dict]:
        if not self.definitions:
            return []
        roster = "; ".join(f"{d.name}: {d.description}" for d in self.definitions.values())
        return [{
            "name": DELEGATE,
            "description": f"Hand a self-contained task to a specialist sub-agent. Available: {roster}",
            "parameters": {"properties": {"agent": {"type": "string"}, "task": {"type": "string"}},
                           "required": ["agent", "task"]},
        }]

    async def _delegate(self, params: Dict[str, Any], user_id) -> str:
        definition = self.definitions.get(str(params.get("agent", "")))
        task = str(params.get("task", "")).strip()
        if not definition:
            return f"ERROR: unknown agent. Available: {', '.join(self.definitions)}"
        if not task:
            return "ERROR: 'task' is required"
        allowed = definition.tools
        tools = [t for t in self.available_tools if allowed is None or t["name"] in allowed]
        sub = AgentLoop(  # fresh context, no delegate tool -> no recursion
            self.runtime, self.agent_id, definition.prompt, tools,
            LoopConfig(max_steps=definition.max_steps, max_tool_chars=self.loop_config.max_tool_chars,
                       max_prompt_chars=self.loop_config.max_prompt_chars, tool_timeout=self.loop_config.tool_timeout),
            model=definition.model or self.model,
            temperature=definition.temperature if definition.temperature is not None else self.temperature,
            max_tokens=self.max_tokens,
        )
        result = await sub.run(task, user_id=user_id)
        return clip(result.text, 2500)

    async def act(self, plan: List[Dict], **kwargs) -> LoopResult:
        thought = next(s["thought"] for s in plan if s.get("step") == "agent_loop")
        user_id = thought["user_id"]

        async def delegate(params):
            return await self._delegate(params, user_id)

        loop = AgentLoop(
            self.runtime, self.agent_id, self.system_prompt, self.available_tools, self.loop_config,
            model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
            extra_tools={DELEGATE: delegate} if self.definitions else None,
            extra_specs=self._delegate_spec(),
        )
        result = await loop.run(thought["user_message"], thought["history"], thought["lessons"], user_id)
        logger.info(f"[{self.name}] done: stopped={result.stopped} tool_calls={result.tool_calls}")
        return result

    # ---- reflect: remember and learn --------------------------------------
    async def reflect(self, result: LoopResult, **kwargs) -> Dict:
        event = kwargs.get("event")
        data = event.data
        conversation_id = data.get("conversation_id") or str(uuid.uuid4())
        user_message = data.get("message")
        user_id = data.get("user_id")
        response_text = result.text

        history = list(data.get("history") or self._conversation_histories.get(conversation_id, []))
        history += [{"role": "user", "content": user_message}, {"role": "assistant", "content": response_text}]
        history = history[-self.history_limit:]
        self._conversation_histories[conversation_id] = history

        learned = await self.lessons.learn(user_id, conversation_id, user_message, result)

        await self.send_event(
            event_type="agent.response",
            data={
                "conversation_id": conversation_id,
                "response": response_text,
                "original_message": user_message,
                # Routing only: lets the stream deliver this to the requester alone.
                "user_id": user_id,
                "run_id": data.get("run_id"),
            },
            target_agent_ids=None,
        )
        return {"response": response_text, "conversation_id": conversation_id,
                "history_length": len(history), "tool_calls": result.tool_calls,
                "stopped": result.stopped, "lessons_learned": learned}
