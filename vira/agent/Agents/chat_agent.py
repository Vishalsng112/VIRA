# vira/agent/Agents/chat_agent.py
"""Chat agent: a Claude-style tool loop designed for local models.

Per message: recall lessons -> multi-step tool loop (AgentLoop) -> optional
delegation to markdown-defined sub-agents -> learn from mistakes -> answer.

Tool awareness:
  * The system prompt always carries a tool policy + a catalog of available tools.
  * The user message is matched against tool names/descriptions to hint likely tools.
  * If the loop answers without any tool call and the answer is empty/hedging
    (or a strongly matching tool was ignored), it retries once with a forced nudge.
"""
import re
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent.base import BaseAgent
from vira.agent.definitions import AgentDefinition, load_definitions
from vira.agent.lessons import LessonStore
from vira.agent.loop import AgentLoop, LoopConfig, LoopResult
from vira.agent.progress import hub
from vira.agent.toolcalls import clip
from vira.agent_orchestration.registry import AgentCapability
from vira.agent_runtime.runtime import AgentContext

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
            "Be concise and accurate."
        )
        self.model = merged.get("model")
        self.temperature = merged.get("temperature", 0.7)
        self.max_tokens = merged.get("max_tokens", 1024)
        self.history_limit = int(merged.get("history_limit", 20))
        self.retry_on_miss = bool(merged.get("retry_on_miss", True))
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

    # ---- tool awareness ----------------------------------------------------
    @staticmethod
    def _tokens(text: str) -> set:
        return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}

    def _tool_catalog(self) -> str:
        lines = []
        for t in self.available_tools:
            params = t.get("parameters") or {}
            props = params.get("properties", params) if isinstance(params, dict) else {}
            args = ", ".join(props.keys()) if isinstance(props, dict) else ""
            lines.append(f"- {t['name']}({args}): {t.get('description', '')}")
        if self.definitions:
            lines.append(f"- {DELEGATE}(agent, task): hand a task to a specialist: "
                         + "; ".join(f"{d.name} ({d.description})" for d in self.definitions.values()))
        return "\n".join(lines)

    def _suggest_tools(self, message: str, k: int = 3) -> List[tuple]:
        """Rank tools by word overlap between the message and tool name/description."""
        msg = self._tokens(message)
        scored = []
        for t in self.available_tools:
            name_words = self._tokens(t["name"].replace("_", " ").replace(".", " "))
            desc_words = self._tokens(t.get("description", ""))
            score = 2 * len(msg & name_words) + len(msg & desc_words)
            if score:
                scored.append((score, t["name"]))
        scored.sort(reverse=True)
        return [(n, s) for s, n in scored[:k]]

    def _build_system_prompt(self, message: str) -> str:
        if not self.available_tools and not self.definitions:
            return self.system_prompt
        parts = [self.system_prompt, TOOL_POLICY, "AVAILABLE TOOLS:\n" + self._tool_catalog()]
        hints = self._suggest_tools(message)
        if hints:
            parts.append("For this request, likely relevant tools: " + ", ".join(n for n, _ in hints)
                         + ". Prefer calling one of them over answering from memory.")
        return "\n\n".join(parts)

    @staticmethod
    def _n_calls(result: LoopResult) -> int:
        c = getattr(result, "tool_calls", 0)
        return c if isinstance(c, int) else len(c or [])

    @staticmethod
    def _unanswered(text: Optional[str]) -> bool:
        t = (text or "").strip().lower()
        return len(t) < 2 or any(h in t for h in _HEDGES)

    # ---- think: gather what the loop needs ---------------------------------
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
            "run_id": event.data.get("run_id"),
            "lessons": await self.lessons.recall(user_id, message),
        }

    # ---- plan: pick the strategy -------------------------------------------
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

    async def _delegate(self, params: Dict[str, Any], user_id, on_event=None) -> str:
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
            max_tokens=self.max_tokens, on_event=on_event, source=definition.name,
        )
        result = await sub.run(task, user_id=user_id)
        return clip(result.text, 2500)

    async def act(self, plan: List[Dict], **kwargs) -> LoopResult:
        thought = next(s["thought"] for s in plan if s.get("step") == "agent_loop")
        user_id = thought["user_id"]
        run_id = thought.get("run_id")
        message = thought["user_message"]

        def on_event(evt: Dict[str, Any]) -> None:
            hub.emit(run_id, evt)

        async def delegate(params):
            return await self._delegate(params, user_id, on_event)

        def make_loop() -> AgentLoop:
            return AgentLoop(
                self.runtime, self.agent_id, self._build_system_prompt(message),
                self.available_tools, self.loop_config,
                model=self.model, temperature=self.temperature, max_tokens=self.max_tokens,
                extra_tools={DELEGATE: delegate} if self.definitions else None,
                extra_specs=self._delegate_spec(), on_event=on_event,
            )

        result = await make_loop().run(message, thought["history"], thought["lessons"], user_id)

        # Safety net: answered without any tool although tools exist and the answer
        # is empty/hedging, or a strongly matching tool was never used -> retry once.
        hints = self._suggest_tools(message)
        strong_hint = bool(hints) and hints[0][1] >= 3
        if (self.retry_on_miss and self.available_tools and self._n_calls(result) == 0
                and (self._unanswered(result.text) or strong_hint)):
            names = ", ".join(n for n, _ in hints) or ", ".join(t["name"] for t in self.available_tools[:5])
            logger.info(f"[{self.name}] no tool used; retrying with forced tool nudge ({names})")
            nudged = (f"{message}\n\n[System note: do not answer from memory. Call one of these tools "
                      f"({names}) to get or verify the answer, then reply using its result.]")
            retry = await make_loop().run(nudged, thought["history"], thought["lessons"], user_id)
            if self._n_calls(retry) > 0 or not self._unanswered(retry.text):
                result = retry

        if not (result.text or "").strip():
            fallback = ("I couldn't produce an answer for that. Please rephrase, "
                        "or tell me which tool/source to use.")
            try:
                result.text = fallback
            except Exception:  # e.g. frozen dataclass
                logger.warning(f"[{self.name}] empty answer and LoopResult.text is read-only")

        logger.info(f"[{self.name}] done: stopped={result.stopped} tool_calls={result.tool_calls}")
        return result

    # ---- reflect: remember and learn ---------------------------------------
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