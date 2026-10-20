# vira/agent/examples/simple_agent.py
from vira.agent.base import BaseAgent
from vira.agent_orchestration.registry import AgentCapability

class SimpleAgent(BaseAgent):
    def __init__(self, runtime):
        super().__init__("SimpleAgent", runtime=runtime)
        self._capabilities = [AgentCapability(name="greet", description="Says hello")]
        self._subscribed_events = ["user.message"]

    async def think(self, context, **kwargs):
        event = kwargs.get("event")
        if event and event.data.get("text"):
            return {"intent": "greet", "text": event.data["text"]}
        return {"intent": "idle"}

    async def plan(self, thought, **kwargs):
        if thought["intent"] == "greet":
            return [{"action": "say_hello", "params": {"text": thought["text"]}}]
        return []

    async def act(self, plan, **kwargs):
        result = []
        for step in plan:
            if step["action"] == "say_hello":
                # Use runtime to call LLM or tool
                response = await self.runtime.call_llm(
                    self.agent_id, 
                    f"Respond to: {step['params']['text']}"
                )
                result.append(response)
        return result

    async def reflect(self, result, **kwargs):
        # Log or store result
        return {"processed": True}


# test code
if __name__ == "__main__":
    import asyncio
    from vira.agent_runtime.runtime import AgentRuntime
    from vira.llm.manager import LLMManager
    from vira.memory.manager import MemoryManager
    from vira.tools.executor import ToolExecutor
    from vira.kernel.security_manager import SecurityManager
    from vira.kernel.context_manager import ContextManager

    async def main():
        # Setup runtime with mock managers
        memory_manager = MemoryManager()
        llm_manager = LLMManager()
        tool_executor = ToolExecutor()
        security_manager = SecurityManager()
        context_manager = ContextManager()

        runtime = AgentRuntime(
            memory_manager=memory_manager,
            llm_manager=llm_manager,
            tool_executor=tool_executor,
            security_manager=security_manager,
            context_manager=context_manager
        )

        agent = SimpleAgent(runtime)
        await agent.initialize()
        await agent.start()

        # Simulate an event
        event = type("Event", (object,), {"data": {"text": "Hello, agent!"}})
        thought = await agent.think(None, event=event)
        plan = await agent.plan(thought)
        result = await agent.act(plan)
        reflection = await agent.reflect(result)

        print("Thought:", thought)
        print("Plan:", plan)
        print("Result:", result)
        print("Reflection:", reflection)

    asyncio.run(main())