# vira/sensors/event_sensor.py
import asyncio
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
                if self._publisher:
                    await self._publisher.publish(
                        Event(
                            type=self.EVENT_TYPE,
                            data=data,
                            source=self.name,
                            priority=self.PRIORITY,
                        )
                    )
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Sensor %s failed", self.name)
                await asyncio.sleep(self.interval)

    async def read(self):
        """Override in subclass to return sensor data."""
        raise NotImplementedError