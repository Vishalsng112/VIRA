# vira/sensors/system_sensor.py
import psutil
from loguru import logger
from vira.sensors.event_sensor import EventSensor
from vira.kernel import EventPriority

# logger = logging.getLogger(__name__)


class SystemSensor(EventSensor):
    EVENT_TYPE = "sensor.system.metrics"
    PRIORITY = EventPriority.LOW

    def __init__(self, interval: float = 5.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="system_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self):
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent,
        }