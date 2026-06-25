# tests/test_load_monitor.py
import asyncio
from loguru import logger
from vira.kernel.kernel import Kernel
from vira.agent.examples.AGENT_MONITOR import LoadMonitorAgent
from vira.agent_orchestration.registry import AgentState
from vira.kernel.event_bus import Event

# logging.basicConfig(level=logging.INFO)

async def test_load_monitor():
    # 1. Boot the kernel (loads config, sensors, etc.)
    kernel = Kernel(config_path="config.yaml")
    await kernel.boot()

    # 2. Get the AgentManager from the kernel (assuming it's available via module manager)
    # In your kernel.py, you instantiated agent_manager as self.agent_manager
    # We'll need to access it.
    agent_manager = kernel.agent_manager  # This is the AgentManager instance

    # 3. Create the agent with its runtime dependencies
    # The runtime is created inside the agent_manager? Actually, AgentManager doesn't own runtime.
    # We need to create a runtime that uses kernel services.
    # For integration, we can get services from kernel's service_registry.
    runtime = AgentRuntime(
        memory_manager=kernel.memory_manager,  # if you have one
        llm_manager=kernel.llm_manager,
        tool_executor=kernel.tool_executor,
        security_manager=kernel.security_manager,
        context_manager=kernel.context_manager
    )

    # 4. Instantiate and register the agent
    agent = LoadMonitorAgent(runtime, cpu_threshold=70.0, memory_threshold=70.0)
    await agent.initialize()
    await agent.start()
    await agent_manager.register(agent)  # assumes AgentManager has register method

    # 5. Simulate a hardware sensor event by publishing directly
    # The hardware sensor would normally publish this; we'll do it manually.
    event_data = {
        "cpu_percent": 85.0,
        "memory_percent": 65.0,
        "timestamp": 1234567890
    }
    event = Event(
        type="sensor.hardware.state",
        data=event_data,
        source="test"
    )
    await kernel.dispatcher.publish(event)

    # 6. Wait a moment for the agent to process asynchronously
    await asyncio.sleep(2)

    # 7. Check that the agent did something – for example, we can query memory
    # or check logs.
    # In a real test, you would verify the agent's memory or state.
    # Here we just print to confirm.
    state = await agent_manager.get_metadata(agent.agent_id)
    print(f"Agent state: {state.state}")  # Should be READY after processing
    # You could also check if a memory item was stored (if you have memory).
    # ...

    # 8. Shutdown
    await kernel.shutdown()

if __name__ == "__main__":
    asyncio.run(test_load_monitor())