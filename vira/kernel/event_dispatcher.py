# vira/kernel/event_dispatcher.py
"""Central event dispatcher with security and pipeline enforcement."""
from loguru import logger
import time
from typing import Optional

from .event_bus import EventBus, Event
from .event_pipeline import EventPipeline
from .security_manager import SecurityManager

# logger = logging.getLogger(__name__)


class EventDispatcher:
    """
    Single entry point for publishing events.
    Applies security checks (marking verified/unverified), pipeline enrichment,
    and metrics recording. Never discards events.
    """

    def __init__(
        self,
        event_bus: EventBus,
        pipeline: EventPipeline,
        security: SecurityManager,
        metrics_manager: Optional["MetricsManager"] = None,
    ):
        self._event_bus = event_bus
        self._pipeline = pipeline
        self._security = security
        self._metrics = metrics_manager

    async def publish(self, event: Event) -> int:
        """
        Process and publish an event. The event is always published,
        but its 'verified' flag is set to True if it passes security,
        else False.
        """
        # 1. Security check (does NOT reject; just marks)
        if self._security.can_publish_event(event.type, source=event.source):
            event.verified = True
        else:
            event.verified = False
            logger.warning(
                f"Event {event.type} from {event.source} is UNAUTHORISED – "
                "marked unverified but still published."
            )
            if self._metrics:
                self._metrics.record_error("security_denied", "event_dispatcher")

        # 2. Pipeline processing (enrichment, classification, prioritisation)
        start = time.time()
        try:
            enriched_event = await self._pipeline.process(event)
        except Exception as e:
            logger.error(f"Event pipeline failed for {event.type}: {e}")
            if self._metrics:
                self._metrics.record_error("pipeline_failure", "event_dispatcher")
            # We still publish the original event (or we could raise, but let's continue)
            enriched_event = event  # fallback

        duration = time.time() - start
        if self._metrics:
            self._metrics.observe_histogram(
                "event_pipeline_duration_seconds", duration, labels={"type": event.type}
            )

        # 3. Publish to the bus
        count = await self._event_bus.publish(enriched_event)

        # 4. Record metrics (optional)
        if self._metrics:
            self._metrics.record_event_published(event.type, event.source)

        return count

    # Convenience method to directly publish from a dict (optional)
    async def publish_dict(self, event_type: str, data: dict, source: str = "kernel") -> int:
        """Create and publish an event from a dict."""
        event = Event(type=event_type, data=data, source=source)
        return await self.publish(event)
    