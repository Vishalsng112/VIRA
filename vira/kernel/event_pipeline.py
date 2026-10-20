"""Event enrichment and processing pipeline"""
from loguru import logger
import time
import uuid
from typing import Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field

from .event_bus import Event, EventPriority

# logger = logging.getLogger(__name__)


@dataclass
class EventEnvelope:
    """Wrapped event with pipeline metadata"""
    event: Event
    pipeline_stage: str = "raw"
    enriched: Dict[str, Any] = field(default_factory=dict)


class EventPipeline:
    """Normalizes, enriches, classifies, and prioritizes events"""

    def __init__(self):
        self._normalizers: List[Callable[[Event], Event]] = []
        self._enrichers: List[Callable[[Event], Dict[str, Any]]] = []
        self._classifiers: List[Callable[[Event], str]] = []
        self._prioritizers: List[Callable[[Event], EventPriority]] = []

    async def start(self):
        """Start pipeline"""
        logger.info("EventPipeline started")

    async def stop(self):
        """Stop pipeline"""
        logger.info("EventPipeline stopped")

    def register_normalizer(self, normalizer: Callable[[Event], Event]):
        """Register a normalizer function"""
        self._normalizers.append(normalizer)

    def register_enricher(self, enricher: Callable[[Event], Dict[str, Any]]):
        """Register an enricher function"""
        self._enrichers.append(enricher)

    def register_classifier(self, classifier: Callable[[Event], str]):
        """Register a classifier function"""
        self._classifiers.append(classifier)

    def register_prioritizer(self, prioritizer: Callable[[Event], EventPriority]):
        """Register a prioritizer function"""
        self._prioritizers.append(prioritizer)

    async def process(self, event: Event) -> Event:
        """Process event through the entire pipeline"""
        # 1. Normalization
        for normalizer in self._normalizers:
            try:
                event = normalizer(event)
            except Exception as e:
                logger.error(f"Normalizer failed: {e}")

        # 2. Enrichment (add metadata)
        enrichment_data = {}
        for enricher in self._enrichers:
            try:
                enrichment_data.update(enricher(event))
            except Exception as e:
                logger.error(f"Enricher failed: {e}")

        if enrichment_data:
            if not hasattr(event, "enrichments"):
                event.enrichments = {}
            event.enrichments.update(enrichment_data)

        # 3. Classification (add tags/category)
        for classifier in self._classifiers:
            try:
                category = classifier(event)
                if not hasattr(event, "categories"):
                    event.categories = []
                event.categories.append(category)
            except Exception as e:
                logger.error(f"Classifier failed: {e}")

        # 4. Prioritization (override priority)
        for prioritizer in self._prioritizers:
            try:
                new_priority = prioritizer(event)
                if new_priority:
                    event.priority = new_priority
            except Exception as e:
                logger.error(f"Prioritizer failed: {e}")

        return event

    # Default built-in pipeline stages
    @staticmethod
    def default_timestamp_enricher() -> Callable[[Event], Dict[str, Any]]:
        """Adds timestamp if missing"""
        def enrich(event: Event) -> Dict[str, Any]:
            return {"pipeline_timestamp": time.time(), "correlation_id": event.correlation_id}
        return enrich

    @staticmethod
    def default_priority_classifier() -> Callable[[Event], EventPriority]:
        """Classify priority based on event type patterns"""
        def classify(event: Event) -> EventPriority:
            if "error" in event.type.lower() or "crash" in event.type.lower():
                return EventPriority.CRITICAL
            if "warning" in event.type.lower():
                return EventPriority.HIGH
            if "telemetry" in event.type.lower():
                return EventPriority.LOW
            return EventPriority.NORMAL
        return classify