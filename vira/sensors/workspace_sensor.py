# vira/sensors/workspace_sensor.py
import platform

from vira.sensors.event_sensor import EventSensor


class WorkspaceSensor(EventSensor):

    EVENT_TYPE = "sensor.workspace.state"

    def __init__(self, interval=2.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="workspace_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self):
        return {
            "platform": platform.system(),
            "active_window": None,
            "focused_application": None,
        }