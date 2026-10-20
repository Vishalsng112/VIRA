"""Example core module: Event logger"""
from loguru import logger
from vira.kernel import ViraModule, Event

# logger = logging.getLogger(__name__)


class LoggerModule(ViraModule):
    """Logs all events to the system logger"""

    def __init__(self, name: str = "logger"):
        super().__init__(name)
        self._subscription_id = None
        self._event_bus = None

    async def initialize(self) -> None:
        # Will get event bus from kernel via service registry
        # For simplicity, we'll assume it's set externally
        pass

    async def start(self) -> None:
        self._running = True
        logger.info(f"Module {self.name} started")

    async def stop(self) -> None:
        self._running = False
        logger.info(f"Module {self.name} stopped")

    async def health(self):
        return {"name": self.name, "running": self._running, "status": "healthy"}

    def set_event_bus(self, event_bus):
        """Inject event bus dependency"""
        self._event_bus = event_bus
        self._subscription_id = event_bus.subscribe_all(self._on_event)

    async def _on_event(self, event: Event):
        logger.debug(f"Event received: {event.type} from {event.source}")