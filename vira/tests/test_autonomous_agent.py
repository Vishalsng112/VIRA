import asyncio
import unittest

from vira.agent.Agents.autonomus_agent import AutonomousAgent
from vira.kernel.event_bus import Event


class _Runtime:
    def __init__(self):
        self.memories = []
        self.events = []

    async def get_context(self, agent_id):
        return type("Context", (), {"agent_id": agent_id})()

    async def memory_operation(self, agent_id, operation, **kwargs):
        self.memories.append((agent_id, operation, kwargs))
        return "memory-id"

    async def send_agent_message(self, sender_agent_id, event_type, data, **kwargs):
        self.events.append((sender_agent_id, event_type, data))


class AutonomousAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_learns_pattern_and_notifies_on_sustained_anomaly(self):
        runtime = _Runtime()
        agent = AutonomousAgent(
            runtime,
            window_size=5,
            anomaly_minimum=80,
            consecutive_anomalies=2,
            learning_interval=5,
            decision_cooldown_seconds=0,
        )
        normal = Event(
            type="sensor.hardware.state",
            data={"cpu": {"usage_percent": 20}, "memory": {"percent": 30}},
        )
        for _ in range(5):
            await agent.handle(normal)

        high = Event(
            type="sensor.hardware.state",
            data={"cpu": {"usage_percent": 95}, "memory": {"percent": 40}},
        )
        await agent.handle(high)
        await agent.handle(high)

        self.assertTrue(any(item[2]["memory_type"] == "behavior_pattern" for item in runtime.memories))
        self.assertTrue(any(event[1] == "autonomous.decision" for event in runtime.events))

    async def test_baselines_and_decisions_are_per_device(self):
        runtime = _Runtime()
        agent = AutonomousAgent(
            runtime, window_size=5, anomaly_minimum=80, consecutive_anomalies=2,
            learning_interval=100, decision_cooldown_seconds=0,
        )

        def state(cpu, device):
            return Event(type="sensor.hardware.state", data={"cpu": {"usage_percent": cpu}},
                         device_id=device)

        for _ in range(5):
            await agent.handle(state(20, "dev-a"))
            await agent.handle(state(20, "dev-b"))
        await agent.handle(state(95, "dev-a"))
        await agent.handle(state(95, "dev-a"))
        decisions = [e[2] for e in runtime.events if e[1] == "autonomous.decision"]
        self.assertEqual([d["device_id"] for d in decisions], ["dev-a"])
        self.assertEqual(agent._anomaly_counts.get("dev-b:cpu.usage_percent", 0), 0)

    async def test_ignores_unrelated_events(self):
        runtime = _Runtime()
        agent = AutonomousAgent(runtime)
        thought = await agent.think(
            None,
            event=Event(type="user.message", data={"message": "hello"}),
        )
        self.assertEqual(thought["decision"], "ignore")


if __name__ == "__main__":
    unittest.main()
