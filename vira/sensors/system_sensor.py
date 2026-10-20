# vira/sensors/system_sensor.py
import asyncio
import platform
import socket
import os
import psutil
from datetime import datetime, timezone
from typing import Optional, Any
from loguru import logger

from vira.sensors.event_sensor import EventSensor
from vira.kernel import Event, EventPriority


class SystemSensor(EventSensor):
    EVENT_TYPE = "sensor.system.state"
    PRIORITY = EventPriority.LOW

    def __init__(
        self,
        interval: float = 10.0,          # polling interval (seconds)
        event_bus: Optional[Any] = None,
        dispatcher: Optional[Any] = None,
    ):
        super().__init__(
            name="system_sensor",
            interval=interval,
            event_bus=event_bus,
            dispatcher=dispatcher,
        )

        self._hostname = socket.gethostname()
        self._os_version = platform.platform()
        self._user = os.getenv("USER") or os.getenv("LOGNAME") or "unknown"
        self._session_type = os.getenv("XDG_SESSION_TYPE") or "unknown"

        # State tracking for change detection
        self._last_battery = None          # tuple (percent, power_plugged)

        # Emit startup event when sensor begins
        self._startup_emitted = False

    async def _run(self):
        """Start the sensor loop, emitting events at the specified interval."""
        self._running = True

        while self._running:
            try:
                # Emit startup event on the first iteration
                if not self._startup_emitted:
                    await self._emit_event("startup", {
                        "boot_time": datetime.now().isoformat()
                    })
                    self._startup_emitted = True

                # Battery state and power source
                await self._check_battery()

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"SystemSensor polling error: {e}")
                await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        """Stop the sensor and emit a shutdown event."""
        # Emit shutdown event before stopping
        if self._running:
            await self._emit_event("shutdown", {
                "shutdown_time": datetime.now().isoformat()
            })
        await super().stop()


    async def _emit_event(self, subtype: str, extra: Optional[dict] = None):
        data = {
            subtype: subtype,
            "timestamp": datetime.now().isoformat(),
            "hostname": self._hostname,
            "os_version": self._os_version,
            "user": self._user,
            "session_type": self._session_type,
            **(extra or {})
        }
        event = Event(
            type=self.EVENT_TYPE,
            data=data,
            source=self.name,
            priority=self.PRIORITY,
        )
        if self._publisher:
            await self._publisher.publish(event)
        else:
            logger.warning("No publisher available for SystemSensor event")

    async def _check_battery(self):
        """Detect changes in battery percentage or power source."""
        battery = psutil.sensors_battery()
        if battery is None:
            # No battery (desktop): we can emit a "power_source" event once
            if self._last_battery is None:
                await self._emit_event("power_source", {"on_battery": False})
                self._last_battery = (None, False)
            return

        percent = battery.percent
        plugged = battery.power_plugged
        current = (percent, plugged)

        if self._last_battery is None:
            # First reading: emit current state
            await self._emit_event("battery_state", {
                "percentage": percent,
                "power_plugged": plugged,
            })
            await self._emit_event("power_source", {"on_battery": not plugged})
        elif current != self._last_battery:
            # Change detected
            await self._emit_event("battery_state", {
                "percentage": percent,
                "power_plugged": plugged,
            })
            await self._emit_event("power_source", {"on_battery": not plugged})

        self._last_battery = current

    #  Future OS‑specific event listeners (stubs)
    #   - Sleep / Wake
    #   - Login / Logout
    #   - Screen Lock / Unlock
    #   - Idle Begin / End
    #   - Display Configuration
    # For now, they are not implemented.