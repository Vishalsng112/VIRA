"""Agent message bus subscription lifecycle."""
import asyncio
import unittest

from vira.agent_orchestration.message_bus import AgentMessageBus
from vira.agent_orchestration.messages import AgentMessage


class AgentMessageBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsubscribe_stops_delivery(self):
        bus = AgentMessageBus()
        received = []

        async def handler(message):
            received.append(message.data)

        await bus.subscribe("demo.event", handler)
        await bus.publish(AgentMessage(type="demo.event", data="first"))
        await asyncio.sleep(0)
        await bus.unsubscribe("demo.event", handler)
        await bus.publish(AgentMessage(type="demo.event", data="second"))
        await asyncio.sleep(0)
        self.assertEqual(received, ["first"])

    async def test_unsubscribe_bound_method(self):
        bus = AgentMessageBus()
        received = []

        class Listener:
            async def handle(self, message):
                received.append(message.data)

        listener = Listener()
        await bus.subscribe("demo.event", listener.handle)
        # Bound methods are new objects on each access; unsubscribe must still work.
        await bus.unsubscribe("demo.event", listener.handle)
        await bus.publish(AgentMessage(type="demo.event", data="ignored"))
        await asyncio.sleep(0)
        self.assertEqual(received, [])

    async def test_wildcard_and_specific_are_independent(self):
        bus = AgentMessageBus()
        specific, wildcard = [], []

        async def on_specific(message):
            specific.append(message.data)

        async def on_all(message):
            wildcard.append(message.data)

        await bus.subscribe("demo.event", on_specific)
        await bus.subscribe("*", on_all)
        await bus.publish(AgentMessage(type="demo.event", data=1))
        await asyncio.sleep(0)
        await bus.unsubscribe("demo.event", on_specific)
        await bus.publish(AgentMessage(type="demo.event", data=2))
        await asyncio.sleep(0)
        self.assertEqual(specific, [1])
        self.assertEqual(wildcard, [1, 2])


if __name__ == "__main__":
    unittest.main()
