"""Example core module: Health monitoring"""
import time

from loguru import logger
from vira.kernel import ViraModule, Event, EventPriority

# logger = logging.getLogger(__name__)


class HealthModule(ViraModule):
    """Monitors kernel health and publishes heartbeat events"""

    def __init__(self, name: str = "health"):
        super().__init__(name)
        self._scheduler = None
        self._event_bus = None
        self._job_id = None

    async def initialize(self) -> None:
        pass

    async def start(self) -> None:
        self._running = True
        if self._scheduler:
            self._job_id = await self._scheduler.schedule_interval(
                self._heartbeat,
                interval_seconds=10.0
            )
        logger.info(f"Module {self.name} started")

    async def stop(self) -> None:
        if self._job_id and self._scheduler:
            await self._scheduler.cancel(self._job_id)
        self._running = False
        logger.info(f"Module {self.name} stopped")

    async def health(self):
        return {"name": self.name, "running": self._running, "status": "healthy"}

    def set_scheduler(self, scheduler):
        self._scheduler = scheduler

    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    async def _heartbeat(self):
        if self._event_bus:
            await self._event_bus.publish(Event(
                type="kernel.heartbeat",
                data={"timestamp": int(time.time())},
                source=self.name,
                priority=EventPriority.LOW
            ))