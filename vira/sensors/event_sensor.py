# vira/sensors/event_sensor.py
import asyncio
import time
from loguru import logger
from typing import Optional, Any

from vira.sensors.base_sensor import BaseSensor
from vira.kernel import Event, EventPriority

# logger = logging.getLogger(__name__)


class EventSensor(BaseSensor):
    """Base implementation for event‑producing sensors."""

    EVENT_TYPE = "sensor.unknown"
    PRIORITY = EventPriority.LOW

    def __init__(
        self,
        name: str,
        interval: float = 5.0,
        event_bus: Optional[Any] = None,
        dispatcher: Optional[Any] = None,
    ):
        super().__init__(name)
        self.interval = interval
        self.event_bus = event_bus
        self.dispatcher = dispatcher
        # Prefer dispatcher; fallback to event_bus
        self._publisher = dispatcher or event_bus
        if self._publisher is None:
            raise ValueError("Either event_bus or dispatcher must be provided")

        self._task = None
        self._running = False
        self._last_read_at = None
        self._last_event_at = None
        self._last_error = None
        self._read_count = 0
        self._error_count = 0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Sensor %s started", self.name)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Sensor %s stopped", self.name)

    async def _run(self):
        while self._running:
            try:
                data = await self.read()
                self._last_read_at = time.time()
                self._read_count += 1
                if self._publisher:
                    await self._publisher.publish(
                        Event(
                            type=self.EVENT_TYPE,
                            data=data,
                            source=self.name,
                            priority=self.PRIORITY,
                        )
                    )
                    self._last_event_at = time.time()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception:
                self._last_error = "sensor read or publication failed"
                self._error_count += 1
                logger.exception("Sensor %s failed", self.name)
                await asyncio.sleep(self.interval)

    def health(self) -> dict:
        return {
            "name": self.name,
            "event_type": self.EVENT_TYPE,
            "running": self._running,
            "last_read_at": self._last_read_at,
            "last_event_at": self._last_event_at,
            "last_error": self._last_error,
            "read_count": self._read_count,
            "error_count": self._error_count,
        }

    async def read(self):
        """Override in subclass to return sensor data."""
        raise NotImplementedError