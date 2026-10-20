# vira/agents/chat_agent.py
import uuid
import json
from typing import Dict, List, Any, Optional
from loguru import logger

from vira.agent.base import BaseAgent
from vira.agent_runtime.runtime import AgentContext
from vira.agent_orchestration.registry import AgentCapability
from vira.kernel.event_bus import Event


class ChatAgent(BaseAgent):
    _conversation_histories: Dict[str, List[Dict]] = {}

    def __init__(
        self,
        runtime,
        config: Optional[Dict] = None,
        **kwargs
    ):
        # Merge config and direct kwargs; direct kwargs take precedence
        merged = config or {}
        merged.update(kwargs)   # kwargs overrides config

        # Extract values
        name = merged.get("name", "ChatAgent")
        description = merged.get("description", "Conversational AI agent with tool support")
        agent_id = merged.get("agent_id")
        system_prompt = merged.get("system_prompt")
        model = merged.get("model")
        temperature = merged.get("temperature", 0.7)
        max_tokens = merged.get("max_tokens", 1024)

        # Call base class – do NOT pass config
        super().__init__(
            name=name,
            description=description,
            runtime=runtime,
            agent_id=agent_id
        )

        # Store all settings
        self.config = merged   # <-- now a dict, so .get() will work
        self.system_prompt = system_prompt or (
            "You are a helpful Agent (VIRA-AGENT) that can use tools when appropriate.\n"
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Load tools (same as before)
        self.available_tools = (
            self.runtime.tool_executor.list_tools() 
            if self.runtime.tool_executor 
            else []
        )
        tool_names = [t.get('name') for t in self.available_tools]
        logger.info(f"[{self.name}] Loaded tools: {tool_names}")
        print(f"[{self.name}] Available tools: {tool_names}")
        print(self.runtime.tool_executor.list_tools())

        self._subscribed_events = ["user.message"]
        self._capabilities = [
            AgentCapability(
                name="chat",
                description="Respond to user messages, optionally using tools.",
                input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"response": {"type": "string"}}}
            )
        ]

    def _load_tools(self) -> List[Dict]:
        """Fetch tool metadata from the ToolExecutor."""
        try:
            tools = self.runtime.tool_executor.list_tools()
            return tools
        except AttributeError:
            logger.warning("ToolExecutor does not support listing tools. No tools loaded.")
            return []

    async def think(self, context: AgentContext, **kwargs) -> Dict:
        logger.debug(f"[{self.name}] Thinking...")
        event = kwargs.get("event")
        if not event:
            raise ValueError("ChatAgent requires an event")

        message = event.data.get("message")
        if not message:
            raise ValueError("Event data missing 'message'")

        conversation_id = event.data.get("conversation_id", str(uuid.uuid4()))

        # Retrieve history
        history = self._conversation_histories.get(conversation_id, [])
        logger.debug(f"[{self.name}] Retrieved {len(history)} messages for {conversation_id}")

        # Store for later
        self._current_conversation_id = conversation_id
        self._current_user_message = message
        self._current_history = history

        return {
            "conversation_id": conversation_id,
            "user_message": message,
            "history": history,
        }

    async def plan(self, thought: Dict, **kwargs) -> List[Dict]:
        logger.debug(f"[{self.name}] Planning...")
        return [{
            "step": "llm_generate",
            "prompt": self._build_prompt(thought, []),
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }]

    async def act(self, plan: List[Dict], **kwargs) -> Any:
        logger.debug(f"[{self.name}] Acting...")

        # Find the LLM step (there should be only one)
        llm_step = next((s for s in plan if s.get("step") == "llm_generate"), None)
        if not llm_step:
            raise ValueError("No LLM generation step in plan")

        # First LLM call: may request a tool
        initial_response = await self.runtime.call_llm(
            agent_id=self.agent_id,
            prompt=llm_step["prompt"],
            model=llm_step["model"],
            temperature=llm_step["temperature"],
            max_tokens=llm_step["max_tokens"],
        )

        # Extract the text from the response
        if hasattr(initial_response, 'text'):
            response_text = initial_response.text
        elif isinstance(initial_response, dict) and 'text' in initial_response:
            response_text = initial_response['text']
        else:
            response_text = str(initial_response)

        # Try to parse as JSON to detect a tool call
        tool_call = None
        try:
            data = json.loads(response_text.strip())
            if isinstance(data, dict) and "tool" in data and "params" in data:
                tool_call = data
        except json.JSONDecodeError:
            pass

        final_response = response_text

        if tool_call:
            tool_name = tool_call["tool"]
            params = tool_call.get("params", {})

            print(f"\n[TOOL SELECTED] {tool_name} with params: {params}")

            # Execute the tool
            try:
                tool_result = await self.runtime.use_tool(self.agent_id, tool_name, **params)
                print(f"[TOOL RESULT] {tool_result}")
                logger.info(f"[{self.name}] Tool {tool_name} executed successfully.")
            except Exception as e:
                error_msg = str(e)
                print(f"[TOOL ERROR] {error_msg}")
                logger.error(f"[{self.name}] Tool {tool_name} failed: {e}")
                tool_result = {"error": error_msg}

            # Follow‑up prompt with tool result
            follow_up_prompt = (
                f"{llm_step['prompt']}\n\n"
                f"System: The tool '{tool_name}' was called and returned:\n{tool_result}\n\n"
                "Now, based on that information, provide your final answer to the user. "
                "Include a brief note that you used the tool and what the result was."
            )

            final_llm_response = await self.runtime.call_llm(
                agent_id=self.agent_id,
                prompt=follow_up_prompt,
                model=llm_step["model"],
                temperature=llm_step["temperature"],
                max_tokens=llm_step["max_tokens"],
            )

            if hasattr(final_llm_response, 'text'):
                final_response = final_llm_response.text
            elif isinstance(final_llm_response, dict) and 'text' in final_llm_response:
                final_response = final_llm_response['text']
            else:
                final_response = str(final_llm_response)
        else:
            print("\n[NO TOOL CALLED] Responding with plain text.")

        return final_response

    async def reflect(self, result: Any, **kwargs) -> Dict:
        logger.debug(f"[{self.name}] Reflecting...")
        conversation_id = self._current_conversation_id
        user_message = self._current_user_message
        history = self._current_history

        response_text = result if isinstance(result, str) else str(result)

        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        self._conversation_histories[conversation_id] = history

        await self.send_event(
            event_type="agent.response",
            data={
                "conversation_id": conversation_id,
                "response": response_text,
                "original_message": user_message,
            },
            target_agent_ids=None
        )

        return {
            "response": response_text,
            "conversation_id": conversation_id,
            "history_length": len(history)
        }

    def _build_prompt(self, thought: Dict, plans: List[Dict]) -> str:
        """Build the prompt with system message, history, user message, and tool definitions."""
        lines = [f"System: {self.system_prompt}"]

        # Append tool definitions if any
        if self.available_tools:
            lines.append("\nAvailable tools (you may use them if appropriate):")
            for tool in self.available_tools:
                name = tool.get("name", "unknown")
                desc = tool.get("description", "No description")
                params = tool.get("parameters", {})
                lines.append(f"- {name}: {desc}")
                lines.append(f"  Parameters: {params}")
            lines.append(
                "\nIf you need to use a tool, respond with a JSON object like:\n"
                '{"tool": "<tool_name>", "params": {"param1": "value1", ...}}\n'
                "If you do not need a tool, respond with a plain text answer."
            )
        else:
            lines.append("\nNo tools are available. Respond with plain text only.")

        for entry in thought["history"]:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            lines.append(f"{role.capitalize()}: {content}")
        lines.append(f"User: {thought['user_message']}")
        lines.append("Assistant:")
        return "\n".join(lines)