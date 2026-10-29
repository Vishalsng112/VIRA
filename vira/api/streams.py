"""Per-user filtered Server-Sent-Events fan-out (FR-EVT-08).

The previous implementation broadcast every event to every authenticated
connection.  Each subscriber now carries its user identity and an access cache;
an event is delivered only if ``visibility.authorize_event`` allows it.
"""
import asyncio
import json
from typing import Callable, List, Optional

from loguru import logger

from vira.devices.visibility import AccessCache, authorize_event
from vira.kernel import Event

QUEUE_SIZE = 1000


class Subscriber:
    def __init__(self, user_id: int, is_admin: bool, session_id: Optional[str] = None):
        self.user_id = user_id
        self.is_admin = is_admin
        self.session_id = session_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.cache = AccessCache(user_id)
        self.dropped = 0


class EventStreamManager:
    def __init__(self):
        self._subs: List[Subscriber] = []

    def connect(self, user_id: int, is_admin: bool, session_id: Optional[str] = None) -> Subscriber:
        sub = Subscriber(user_id, is_admin, session_id)
        self._subs.append(sub)
        return sub

    def disconnect(self, sub: Subscriber) -> None:
        if sub in self._subs:
            self._subs.remove(sub)

    def invalidate_access(self) -> None:
        """Force subscribers to re-read device grants (after grant/revoke)."""
        for sub in self._subs:
            sub.cache.invalidate()

    def disconnect_user(self, user_id: int) -> None:
        self._subs = [s for s in self._subs if s.user_id != user_id]

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def broadcast(self, event: Event) -> None:
        if not self._subs:
            return
        base = event.dict()
        base["timestamp"] = event.timestamp
        for sub in list(self._subs):
            try:
                visible = authorize_event(base, sub.user_id, sub.is_admin, sub.cache)
            except Exception as exc:  # never let one subscriber break fan-out
                logger.error("Stream ACL check failed: {}", exc)
                continue
            if visible is None:
                continue
            message = f"data: {json.dumps(visible, default=str)}\n\n"
            try:
                sub.queue.put_nowait(message)
            except asyncio.QueueFull:
                sub.dropped += 1  # slow consumer: shed load rather than grow memory
