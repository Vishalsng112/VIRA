"""Reliable consumer helpers for durable event handlers."""
from typing import Awaitable, Callable

from vira.auth import database
from .event_bus import Event


async def handle_idempotently(
    consumer_name: str,
    event: Event,
    handler: Callable[[Event], Awaitable[None]],
) -> bool:
    """Run a handler once per consumer/event pair.

    The consumption marker is written only after the handler succeeds, so a
    failure remains retryable.
    """
    if database.has_event_consumption(consumer_name, event.event_id):
        return False
    await handler(event)
    database.record_event_consumption(consumer_name, event.event_id)
    return True
