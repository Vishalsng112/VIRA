import asyncio
from typing import List, Callable, Awaitable, Dict, Tuple
from loguru import logger
from vira.agent_orchestration.messages import AgentMessage


def _same_callback(registered: Callable, candidate: Callable) -> bool:
    """Compare callbacks, including bound methods that are new objects each access."""
    if registered is candidate:
        return True
    try:
        return registered == candidate
    except Exception:  # exotic callables must never break unsubscribe
        return False


class AgentMessageBus:
    def __init__(self):
        # event type -> [(original callback, delivery wrapper)]
        self._subscribers: Dict[str, List[Tuple[Callable[[AgentMessage], Awaitable[None]],
                                                  Callable[[AgentMessage], Awaitable[None]]]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: str, callback: Callable[[AgentMessage], Awaitable[None]]):
        """Register a callback for a given event type. '*' for wildcard."""
        async def wrapper(msg: AgentMessage):
            await callback(msg)
        async with self._lock:
            self._subscribers.setdefault(event_type, []).append((callback, wrapper))

    async def unsubscribe(self, event_type: str, callback: Callable):
        """Remove a previously registered callback."""
        async with self._lock:
            entries = self._subscribers.get(event_type)
            if not entries:
                return
            remaining = [
                (registered, wrapper)
                for registered, wrapper in entries
                if not _same_callback(registered, callback)
            ]
            if remaining:
                self._subscribers[event_type] = remaining
            else:
                del self._subscribers[event_type]

    async def publish(self, message: AgentMessage):
        """Deliver message to all subscribers matching event_type and target filters."""
        async with self._lock:
            subscribers = [
                wrapper
                for _, wrapper in self._subscribers.get(message.type, [])
            ]
            subscribers.extend(
                wrapper for _, wrapper in self._subscribers.get("*", [])
            )

        if not subscribers:
            return

        # Fire-and-forget delivery
        for cb in subscribers:
            asyncio.create_task(cb(message))
