"""Event/job broker abstraction for multi-process deployments.

The default ``DatabaseBroker`` works across API and worker processes on SQLite
or PostgreSQL.  Redis and NATS adapters are optional: install the client
library and set ``VIRA_BROKER=redis`` or ``VIRA_BROKER=nats``.

API processes are stateless apart from the shared database; run one or more
``python -m vira.worker`` processes for durable jobs.  A deployment that needs
cross-process event fan-out should enable an external broker.
"""
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from loguru import logger


class Broker(ABC):
    name = "base"

    @abstractmethod
    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        ...


class DatabaseBroker(Broker):
    """Durable broker backed by the existing jobs table."""

    name = "database"

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        from vira.jobs import queue
        queue.enqueue("broker.event", {"topic": topic, "payload": payload}, max_attempts=5)


class RedisBroker(Broker):
    name = "redis"

    def __init__(self, url: Optional[str] = None):
        import redis.asyncio as redis  # optional dependency
        self._client = redis.from_url(url or os.environ.get("VIRA_REDIS_URL", "redis://127.0.0.1:6379"))

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._client.publish(topic, json.dumps(payload, default=str))


class NatsBroker(Broker):
    name = "nats"

    def __init__(self, url: Optional[str] = None):
        import nats  # optional dependency
        self._url = url or os.environ.get("VIRA_NATS_URL", "nats://127.0.0.1:4222")
        self._client = None

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        if self._client is None:
            import nats
            self._client = await nats.connect(self._url)
        await self._client.publish(topic, json.dumps(payload, default=str).encode("utf-8"))


_broker: Optional[Broker] = None


def get_broker() -> Broker:
    global _broker
    if _broker is not None:
        return _broker
    kind = os.environ.get("VIRA_BROKER", "database").lower()
    try:
        if kind == "redis":
            _broker = RedisBroker()
        elif kind == "nats":
            _broker = NatsBroker()
        else:
            _broker = DatabaseBroker()
    except Exception as exc:
        logger.warning("Broker {} unavailable ({}); using database broker", kind, exc)
        _broker = DatabaseBroker()
    return _broker
