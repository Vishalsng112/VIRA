"""Event-driven communication with priority support"""
import asyncio
import time
import uuid
from enum import Enum
from typing import Dict, List, Any, Callable, Awaitable, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from loguru import logger

# logger = logging.getLogger(__name__)


class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class EventKind(str, Enum):
    """Distinguish facts from requests for an operation."""

    DOMAIN = "domain"
    COMMAND = "command"
    SYSTEM = "system"


@dataclass
class Event:
    """Base event structure"""
    type: str
    data: Any = None
    source: str = "kernel"
    kind: EventKind = EventKind.DOMAIN
    priority: EventPriority = EventPriority.NORMAL
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    causation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    schema_version: int = 1
    verified: bool = False
    durable: bool = False
    # Provenance (VIRA multi-device design 7.5).  ``source`` stays a free-form
    # descriptive label; these fields are resolved by the server from
    # authenticated credentials/sessions and are never trusted from payloads.
    device_id: Optional[str] = None            # producing endpoint device (may be the server itself)
    actor_user_id: Optional[int] = None        # authenticated human actor, if any
    source_component: Optional[str] = None     # sensor/subsystem on the device
    source_instance_id: Optional[str] = None
    device_sequence: Optional[int] = None
    occurred_at: Optional[str] = None          # device clock (ISO-8601 UTC)
    received_at: Optional[str] = None          # server clock (ISO-8601 UTC)

    def dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "source": self.source,
            "kind": self.kind.value,
            "priority": self.priority.name,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
            "verified": self.verified,
            "durable": self.durable,
            "device_id": self.device_id,
            "actor_user_id": self.actor_user_id,
            "source_component": self.source_component,
            "source_instance_id": self.source_instance_id,
            "device_sequence": self.device_sequence,
            "occurred_at": self.occurred_at,
            "received_at": self.received_at,
        }

    @classmethod
    def from_dict(cls, payload: dict, durable: Optional[bool] = None) -> "Event":
        """Rebuild an event from ``dict()`` output (outbox replay, ingestion)."""
        return cls(
            type=payload["type"],
            data=payload.get("data"),
            source=payload.get("source", "outbox"),
            kind=EventKind(payload.get("kind", EventKind.DOMAIN.value)),
            priority=EventPriority[payload.get("priority", EventPriority.NORMAL.name)],
            event_id=payload["event_id"],
            correlation_id=payload["correlation_id"],
            causation_id=payload.get("causation_id"),
            timestamp=payload.get("timestamp") or time.time(),
            schema_version=payload.get("schema_version", 1),
            verified=payload.get("verified", False),
            durable=payload.get("durable", False) if durable is None else durable,
            device_id=payload.get("device_id"),
            actor_user_id=payload.get("actor_user_id"),
            source_component=payload.get("source_component"),
            source_instance_id=payload.get("source_instance_id"),
            device_sequence=payload.get("device_sequence"),
            occurred_at=payload.get("occurred_at"),
            received_at=payload.get("received_at"),
        )


SubscriberCallback = Callable[[Event], Awaitable[None]]


class EventBus:
    """Async event bus with publish/subscribe, routing and prioritization"""

    def __init__(self, max_queue_size: int = 10000):
        self._subscribers: Dict[str, List[SubscriberCallback]] = defaultdict(list)
        self._wildcard_subscribers: List[SubscriberCallback] = []
        self._lock = asyncio.Lock()
        self._running = True
        self._event_queue: Optional[asyncio.Queue] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._max_queue_size = max_queue_size
        # self.metrics_manager = None

    async def start(self):
        """Start the event bus worker"""
        self._running = True
        self._event_queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._worker_task = asyncio.create_task(self._process_events())
        logger.info("EventBus started")

    async def stop(self):
        """Stop the event bus"""
        self._running = False
        if self._event_queue:
            await self._event_queue.put(None)  # Sentinel
        if self._worker_task:
            await self._worker_task
        logger.info("EventBus stopped")

    async def publish(self, event: Event) -> int:
        if not self._running or self._event_queue is None:
            logger.warning(f"EventBus not running, dropping event: {event.type}")
            return 0

        await self._event_queue.put(event)
        return 1

    async def _process_events(self):
        """Background worker that processes queued events"""
        while self._running:
            try:
                event = await self._event_queue.get()
                if event is None:  # Sentinel
                    break
                await self._dispatch_event(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing event: {e}")

    async def _dispatch_event(self, event: Event):
        """Dispatch event to all matching subscribers"""
        tasks = []

        # Direct type subscribers
        for callback in self._subscribers.get(event.type, []):
            tasks.append(self._safe_callback(callback, event))

        # Wildcard subscribers
        for callback in self._wildcard_subscribers:
            tasks.append(self._safe_callback(callback, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_callback(self, callback: SubscriberCallback, event: Event):
        """Execute callback with error handling"""
        try:
            await callback(event)
        except Exception as e:
            logger.error(f"Error in event subscriber: {e}", exc_info=True)

    def subscribe(self, event_type: str, callback: SubscriberCallback) -> str:
        """Subscribe to a specific event type. Returns subscription ID."""
        subscription_id = f"{event_type}:{uuid.uuid4()}"
        self._subscribers[event_type].append(callback)
        return subscription_id

    def subscribe_all(self, callback: SubscriberCallback) -> str:
        """Subscribe to all events"""
        subscription_id = f"wildcard:{uuid.uuid4()}"
        self._wildcard_subscribers.append(callback)
        return subscription_id

    def unsubscribe(self, event_type: str, callback: SubscriberCallback) -> bool:
        """Unsubscribe a callback from an event type"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
                return True
            except ValueError:
                pass
        return False

    def unsubscribe_all(self, callback: SubscriberCallback) -> bool:
        """Unsubscribe a callback from all events"""
        removed = False
        for event_type in list(self._subscribers.keys()):
            try:
                self._subscribers[event_type].remove(callback)
                removed = True
            except ValueError:
                pass
        try:
            self._wildcard_subscribers.remove(callback)
            removed = True
        except ValueError:
            pass
        return removed

    def pending_events(self) -> int:
        """Return number of events waiting in the internal queue."""
        return self._event_queue.qsize() if self._event_queue is not None else 0