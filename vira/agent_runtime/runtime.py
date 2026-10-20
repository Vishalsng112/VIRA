# vira/agent_runtime/runtime.py
from typing import List, Optional, Dict, Any
# from vira.agent.messaging import AgentMessage
from vira.agent_orchestration.messages import AgentMessage # will use now generic message format
from vira.kernel.context_manager import ContextManager
from vira.memory.manager import MemoryManager
from vira.llm.manager import LLMManager
from vira.tools.executor import ToolExecutor
from vira.kernel.security_manager import SecurityManager

class AgentContext:
    """
    Immutable context snapshot provided to agent at execution time.
    Contains kernel context, session data, and runtime‑provided resources.
    """
    def __init__(self, kernel_context: Dict, session_metadata: Dict, agent_id: str):
        self.kernel_context = kernel_context  # snapshot of kernel context
        self.session_metadata = session_metadata
        self.agent_id = agent_id

class AgentRuntime:
    """
    The per‑agent runtime container.
    Agents interact with the world through this runtime.
    """

    def __init__(self, 
                 memory_manager: MemoryManager,
                 llm_manager: LLMManager,
                 tool_executor: ToolExecutor,
                 security_manager: SecurityManager,
                 context_manager: ContextManager,
                 agent_message_bus=None):
        self._memory = memory_manager
        self._llm = llm_manager
        self._tools = tool_executor
        self._security = security_manager
        self._context_manager = context_manager
        self._agent_message_bus = agent_message_bus

    @property
    def tool_executor(self):
        """Expose the tool executor to agents."""
        return self._tools
    
    async def get_context(self, agent_id: str) -> AgentContext:
        """Retrieve current kernel context and session metadata."""
        kernel_ctx = await self._context_manager.get_current_context()
        # Possibly add agent‑specific session data
        session = await self._context_manager.get_context_value("_session", {})
        return AgentContext(kernel_context=kernel_ctx, session_metadata=session, agent_id=agent_id)

    async def call_llm(self, agent_id: str, prompt: str, **kwargs) -> str:
        """Invoke LLM with permission checks."""
        if not self._security.authorize(f"llm.call.{agent_id}"):
            raise PermissionError(f"Agent {agent_id} not allowed to call LLM")
        return await self._llm.generate(prompt, **kwargs)

    async def use_tool(self, agent_id: str, tool_name: str, **kwargs) -> Any:
        """Execute a tool with permission checks."""
        if not self._security.authorize(f"tool.use.{tool_name}.{agent_id}"):
            raise PermissionError(f"Agent {agent_id} not allowed to use tool {tool_name}")
        return await self._tools.execute(tool_name, **kwargs)

    async def memory_operation(self, agent_id: str, operation: str, **kwargs) -> Any:
        """Access memory with permission checks."""
        if not self._security.authorize(f"memory.{operation}.{agent_id}"):
            raise PermissionError(f"Agent {agent_id} not allowed to {operation} memory")
        return await getattr(self._memory, operation)(**kwargs)

    async def send_agent_message(
        self,
        sender_agent_id: str,
        event_type: str,
        data: Any,
        target_agent_ids: Optional[List[str]] = None,
        exclude_sender: bool = True
    ):
        if self._agent_message_bus is None:
            raise RuntimeError("Agent message bus not available")
        msg = AgentMessage(
            type=event_type,
            data=data,
            sender_agent_id=sender_agent_id,
            target_agent_ids=target_agent_ids,
            exclude_sender=exclude_sender
        )
        await self._agent_message_bus.publish(msg)