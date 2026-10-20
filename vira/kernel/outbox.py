"""Durable outbox publication for events that represent committed state."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from vira.auth import database
from .event_bus import Event, EventKind, EventPriority


class OutboxPublisher:
    """Publishes durable events and retries transient delivery failures."""

    def __init__(
        self,
        event_bus,
        poll_interval: float = 1.0,
        batch_size: int = 100,
        max_attempts: int = 5,
    ):
        self._event_bus = event_bus
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("OutboxPublisher started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("OutboxPublisher stopped")

    async def _run(self) -> None:
        while self._running:
            await self.publish_pending()
            await asyncio.sleep(self._poll_interval)

    async def publish_pending(self) -> int:
        rows = database.claim_outbox_events(self._batch_size)
        published = 0
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                event = Event(
                    type=payload["type"],
                    data=payload.get("data"),
                    source=payload.get("source", "outbox"),
                    kind=EventKind(payload.get("kind", EventKind.DOMAIN.value)),
                    priority=EventPriority[payload.get("priority", EventPriority.NORMAL.name)],
                    event_id=payload["event_id"],
                    correlation_id=payload["correlation_id"],
                    causation_id=payload.get("causation_id"),
                    timestamp=payload.get("timestamp"),
                    schema_version=payload.get("schema_version", 1),
                    verified=payload.get("verified", False),
                    durable=True,
                )
                await self._event_bus.publish(event)
                database.mark_outbox_published(row["id"])
                published += 1
            except Exception as exc:
                attempts = int(row["attempts"])
                dead_letter = attempts >= self._max_attempts
                delay = min(60, 2 ** max(0, attempts - 1))
                retry_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=delay)
                ).isoformat()
                database.mark_outbox_retry(
                    row["id"], str(exc), retry_at, dead_letter=dead_letter
                )
                logger.error("Outbox publication failed for {}: {}", row["id"], exc)
        return published
