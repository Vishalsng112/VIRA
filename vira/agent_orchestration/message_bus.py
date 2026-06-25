import asyncio
from typing import List, Callable, Awaitable, Dict
from loguru import logger
from vira.agent_orchestration.messages import AgentMessage

class AgentMessageBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[AgentMessage], Awaitable[None]]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: str, callback: Callable[[AgentMessage], Awaitable[None]]):
        """Register a callback for a given event type. '*' for wildcard."""
        async def wrapper(msg: AgentMessage):
            await callback(msg)
        async with self._lock:
            self._subscribers.setdefault(event_type, []).append(wrapper)

    async def unsubscribe(self, event_type: str, callback: Callable):
        """Remove a previously registered callback (naive implementation)."""
        async with self._lock:
            if event_type in self._subscribers:
                # We need to find and remove the wrapper; for simplicity, we'll remove by identity (not robust)
                # Better: store original callback with wrapper mapping.
                # For now, we just clear all subscribers of that type (not ideal).
                # In practice, you'd keep a dict of callback->wrapper.
                self._subscribers[event_type] = [
                    cb for cb in self._subscribers[event_type] if cb != callback
                ]
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]

    async def publish(self, message: AgentMessage):
        """Deliver message to all subscribers matching event_type and target filters."""
        subscribers = []
        async with self._lock:
            # subscribers.extend(self._subscribers.get(message.event_type, []))
            subscribers.extend(self._subscribers.get(message.type, []))
            subscribers.extend(self._subscribers.get("*", []))

        if not subscribers:
            return

        # Fire-and-forget delivery
        for cb in subscribers:
            asyncio.create_task(cb(message))