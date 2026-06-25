# vira/sensors/project_sensor.py
from pathlib import Path

from vira.sensors.event_sensor import EventSensor


class ProjectSensor(EventSensor):

    EVENT_TYPE = "sensor.project.state"

    def __init__(self, interval=60.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="project_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self):
        repositories = []
        try:
            for git_dir in Path.home().rglob(".git"):
                repositories.append(str(git_dir.parent))
                if len(repositories) >= 20:
                    break
        except Exception:
            pass
        return {"repositories": repositories}