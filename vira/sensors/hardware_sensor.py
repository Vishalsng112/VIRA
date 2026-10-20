# vira/sensors/hardware_sensor.py
import os
import time
import subprocess
import platform
from typing import Dict, Any, Optional
import psutil
import GPUtil
from screeninfo import get_monitors
import cups
from vira.sensors.event_sensor import EventSensor

class HardwareSensor(EventSensor):
    """Sensor that collects detailed hardware state across multiple subsystems."""

    EVENT_TYPE = "sensor.hardware.state"

    def __init__(self, interval: float = 5.0, event_bus=None, dispatcher=None):
        super().__init__(
            name="hardware_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

    async def read(self) -> Dict[str, Any]:
        """Collect and return a comprehensive hardware status dictionary."""
        data = {
            "cpu": self._get_cpu(),
            "memory": self._get_memory(),
            "disk": self._get_disk(),
            "network": self._get_network(),
            "gpu": self._get_gpu(),
            "battery": self._get_battery(),
            "temperature": self._get_temperature(),
            "usb_devices": self._get_usb_devices(),
            "display": self._get_display(),
            "printer": self._get_printer(),
            "uptime": time.time() - psutil.boot_time(),
        }
        return data

    # ---------- Helper methods ----------

    def _get_cpu(self) -> Dict[str, Any]:
        try:
            freq = psutil.cpu_freq()
            return {
                "usage_percent": psutil.cpu_percent(interval=0.1),
                "per_core": psutil.cpu_percent(percpu=True),
                "logical_cores": psutil.cpu_count(),
                "physical_cores": psutil.cpu_count(logical=False),
                "frequency": freq.current if freq else None,
            }
        except Exception:
            return {"error": "Failed to collect CPU data"}

    def _get_memory(self) -> Dict[str, Any]:
        try:
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            return {
                "percent": vm.percent,
                "used": vm.used,
                "available": vm.available,
                "total": vm.total,
                "swap_percent": swap.percent,
                "swap_used": swap.used,
                "swap_total": swap.total,
            }
        except Exception:
            return {"error": "Failed to collect memory data"}

    def _get_disk(self) -> Dict[str, Any]:
        try:
            disk = psutil.disk_usage("/")
            return {
                "percent": disk.percent,
                "free": disk.free,
                "used": disk.used,
                "total": disk.total,
            }
        except Exception:
            return {"error": "Failed to collect disk data"}

    def _get_network(self) -> Dict[str, Any]:
        try:
            net = psutil.net_io_counters()
            return {
                "bytes_sent": net.bytes_sent,
                "bytes_recv": net.bytes_recv,
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
            }
        except Exception:
            return {"error": "Failed to collect network data"}

    def _get_gpu(self) -> Dict[str, Any]:
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return {"available": False}
            gpu = gpus[0]  # first GPU
            return {
                "available": True,
                "name": gpu.name,
                "load": gpu.load * 100,
                "memory_used": gpu.memoryUsed,
                "memory_total": gpu.memoryTotal,
                "temperature": gpu.temperature,
            }
        except Exception:
            return {"error": "Failed to collect GPU data"}

    def _get_battery(self) -> Dict[str, Any]:
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                return {"available": False}
            return {
                "available": True,
                "percent": battery.percent,
                "secsleft": battery.secsleft,
                "power_plugged": battery.power_plugged,
            }
        except Exception:
            return {"error": "Failed to collect battery data"}

    def _get_temperature(self) -> Dict[str, Any]:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return {"available": False}
            # Return the first temperature sensor found
            for name, entries in temps.items():
                if entries:
                    return {
                        "available": True,
                        "sensor": name,
                        "current": entries[0].current,
                        "high": entries[0].high,
                        "critical": entries[0].critical,
                    }
            return {"available": False}
        except Exception:
            return {"error": "Failed to collect temperature data"}

    def _get_usb_devices(self) -> Dict[str, Any]:
        """List USB devices using lsusb (Linux) or fallback."""
        if platform.system() != "Linux":
            return {"error": "USB detection only supported on Linux"}
        try:
            output = subprocess.check_output(["lsusb"], text=True).strip().split("\n")
            devices = [line.strip() for line in output if line.strip()]
            return {"count": len(devices), "devices": devices}
        except Exception:
            return {"error": "Failed to list USB devices"}


    def _get_display(self) -> Dict[str, Any]:
        """Get display resolution and refresh rate using screeninfo or fallback."""
        try:
            monitors = get_monitors()
            if monitors:
                m = monitors[0]
                return {
                    "available": True,
                    "width": m.width,
                    "height": m.height,
                    "width_mm": m.width_mm,
                    "height_mm": m.height_mm,
                    "refresh_rate": getattr(m, "refresh_rate", None),
                }
        except Exception:
            pass
        return {"error": "Display detection failed"}

    def _get_printer(self) -> Dict[str, Any]:
        """List printers using CUPS or lpstat."""
        try:
            conn = cups.Connection()
            printers = conn.getPrinters()
            return {
                "available": bool(printers),
                "devices": list(printers.keys()),
            }
        except Exception:
            pass

        return {"error": "Printer detection failed"}