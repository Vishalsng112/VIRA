import unittest

from vira.agent.examples.AGENT_MONITOR import LoadMonitorAgent
from vira.agent_orchestration.registry import AgentRegistry, AgentState
from vira.kernel import Event
from vira.kernel.context_manager import ContextManager
from vira.agent_runtime.runtime import AgentContext


class _Memory:
    def __init__(self):
        self.entries = []

    async def store(self, **kwargs):
        self.entries.append(kwargs)
        return kwargs


class _Runtime:
    def __init__(self):
        self._memory = _Memory()
        self.tool_executor = None
        self.context_manager = ContextManager()

    async def get_context(self, agent_id):
        return AgentContext({}, {}, agent_id)

    async def memory_operation(self, agent_id, operation, **kwargs):
        return await getattr(self._memory, operation)(**kwargs)

    async def call_llm(self, agent_id, prompt, **kwargs):
        return type("Response", (), {"text": "test summary"})()


class LoadMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_monitor_uses_agent_contract_and_registry(self):
        runtime = _Runtime()
        agent = LoadMonitorAgent(runtime, cpu_threshold=70.0, memory_threshold=70.0)
        registry = AgentRegistry()

        await registry.register(agent)
        await agent.initialize()
        await agent.start()
        await agent.handle(Event(
            type="sensor.hardware.state",
            data={"cpu_percent": 85.0, "memory_percent": 65.0},
            source="test",
        ))

        metadata = await registry.get_metadata(agent.agent_id)
        self.assertEqual(metadata.state, AgentState.INITIALIZED)
        self.assertEqual(agent.state, AgentState.READY)
        self.assertGreaterEqual(len(runtime._memory.entries), 2)
        entry_types = {entry["metadata"]["type"] for entry in runtime._memory.entries}
        self.assertIn("load_alert", entry_types)
        self.assertIn("llm_suggestion", entry_types)

        await agent.stop()
