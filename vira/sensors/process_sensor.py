# vira/sensors/process_sensor.py
import psutil

from vira.sensors.event_sensor import EventSensor


class ProcessSensor(EventSensor):

    EVENT_TYPE = "sensor.process.state"

    def __init__(self, interval=10.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="process_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self):
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                processes.append(proc.info)
            except Exception:
                pass

        return {
            "process_count": len(processes),
            "top_cpu_processes": sorted(
                processes, key=lambda p: p["cpu_percent"] or 0, reverse=True
            )[:10],
            "top_memory_processes": sorted(
                processes, key=lambda p: p["memory_percent"] or 0, reverse=True
            )[:10],
        }