# vira/sensors/activity_sensor.py
''' Capturing load on the system '''
import time
import psutil

from vira.sensors.event_sensor import EventSensor


class ActivitySensor(EventSensor):

    EVENT_TYPE = "sensor.activity.state"

    def __init__(self, interval=3.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="activity_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self):
        cpu = psutil.cpu_percent(interval=0.1)
        return {
            "activity_score": cpu,
            "active": cpu > 5,
            "timestamp": time.time(),
        }