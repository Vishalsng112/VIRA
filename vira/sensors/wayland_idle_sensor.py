"""Wayland session presence and idle-state sensor."""

import asyncio
import os
import subprocess
import time
from typing import Any, Optional

from loguru import logger

from vira.kernel import Event, EventPriority
from vira.sensors.base_sensor import BaseSensor


class WaylandIdleSensor(BaseSensor):
    """Publish presence changes without inspecting other applications.

    Wayland intentionally does not expose a portable global input or focused
    window API. ``loginctl`` provides the desktop session's coarse idle hint
    without requiring X11 access or input-event snooping.
    """

    EVENT_TYPE = "sensor.session.state"
    PRIORITY = EventPriority.LOW

    def __init__(
        self,
        interval: float = 5.0,
        event_bus: Optional[Any] = None,
        dispatcher: Optional[Any] = None,
        idle_threshold_seconds: int = 60,
    ):
        super().__init__("wayland_idle_sensor")
        self.interval = interval
        self.idle_threshold_seconds = idle_threshold_seconds
        self._publisher = dispatcher or event_bus
        if self._publisher is None:
            raise ValueError("Either event_bus or dispatcher must be provided")
        self._task: Optional[asyncio.Task] = None
        self._last_state: Optional[dict] = None

    async def start(self) -> None:
        if os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
            raise RuntimeError("WaylandIdleSensor requires XDG_SESSION_TYPE=wayland")
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("WaylandIdleSensor started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WaylandIdleSensor stopped")

    async def read(self) -> dict:
        return await asyncio.to_thread(self._read_session)

    async def _run(self) -> None:
        while self._running:
            try:
                state = await self.read()
                comparable_state = {key: value for key, value in state.items() if key != "timestamp"}
                if comparable_state != self._last_state:
                    await self._publisher.publish(
                        Event(
                            type=self.EVENT_TYPE,
                            data=state,
                            source=self.name,
                            priority=self.PRIORITY,
                        )
                    )
                    self._last_state = comparable_state
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Wayland session state read failed")
                await asyncio.sleep(self.interval)

    def _read_session(self) -> dict:
        session_id = os.environ.get("XDG_SESSION_ID")
        if not session_id:
            raise RuntimeError("XDG_SESSION_ID is not set")

        result = subprocess.run(
            [
                "loginctl",
                "show-session",
                session_id,
                "--property=IdleHint",
                "--property=IdleSinceHintMonotonic",
                "--value",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=1.0,
        )
        values = [line.strip() for line in result.stdout.splitlines()]
        if len(values) < 2:
            raise RuntimeError("loginctl returned incomplete idle state")

        idle_hint = values[0].lower() == "yes"
        idle_since = int(values[1]) if values[1].isdigit() else 0
        return {
            "session_type": "wayland",
            "session_id": session_id,
            "present": not idle_hint,
            "idle": idle_hint,
            "idle_threshold_seconds": self.idle_threshold_seconds,
            "idle_since_monotonic_us": idle_since or None,
            "timestamp": time.time(),
        }
