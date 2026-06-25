# vira/sensors/hardware_sensor.py
import os
import time
import psutil

from vira.sensors.event_sensor import EventSensor


class HardwareSensor(EventSensor):

    EVENT_TYPE = "sensor.hardware.state"

    def __init__(self, interval=5.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="hardware_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self):
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        cpu_freq = psutil.cpu_freq()

        return {
            "cpu": {
                "usage_percent": psutil.cpu_percent(interval=0.1),
                "per_core": psutil.cpu_percent(percpu=True),
                "logical_cores": psutil.cpu_count(),
                "physical_cores": psutil.cpu_count(logical=False),
                "frequency": cpu_freq.current if cpu_freq else None,
            },
            "memory": {
                "percent": vm.percent,
                "used": vm.used,
                "available": vm.available,
                "total": vm.total,
                "swap_percent": swap.percent,
            },
            "disk": {
                "percent": disk.percent,
                "free": disk.free,
                "used": disk.used,
                "total": disk.total,
            },
            "network": {
                "bytes_sent": net.bytes_sent,
                "bytes_recv": net.bytes_recv,
            },
            "uptime": time.time() - psutil.boot_time(),
        }