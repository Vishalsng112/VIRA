import asyncio
from loguru import logger
import time
from pathlib import Path
import platform
import os
import subprocess

import pyperclip

from vira.sensors.base_sensor import BaseSensor
from vira.kernel import Event, EventPriority

# logger = logging.getLogger(__name__)


class UserActivitySensor(BaseSensor):
    """
    Sensor that monitors user activity, such as clipboard changes. Will add screenshot monitoring in the future. 
    Currently, it only monitors clipboard changes and publishes events when the clipboard content changes.
    """

    def __init__(
        self,
        interval: float = 0.5,
        event_bus=None,
        dispatcher=None,
        storage_dir: str = "data/user_activity",
        **kwargs
    ):
        super().__init__("user_activity_sensor")

        self.poll_interval = interval
        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self._publisher = dispatcher or event_bus
        if self._publisher is None:
            raise ValueError("Either event_bus or dispatcher must be provided")

        self.storage_dir = Path(storage_dir)

        self._last_clipboard = None
        self._running = False
        self._task = None

        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("UserActivitySensor started (clipboard monitoring)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("UserActivitySensor stopped")

    async def read(self):
        return {"clipboard": self._last_clipboard}

    async def _run(self):
        while self._running:
            try:
                current = await asyncio.to_thread(self._get_clipboard_text)

                if current != self._last_clipboard:
                    self._last_clipboard = current
                    if self._publisher:
                        await self._publisher.publish(
                            Event(
                                type="sensor.clipboard.changed",
                                data={
                                    "timestamp": int(time.time()),
                                    "clipboard": current,
                                },
                                source=self.name,
                                priority=EventPriority.LOW,
                            )
                        )
                    logger.debug(f"Clipboard changed: {current[:50] if current else '<empty>'}")

                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Clipboard polling failed")
                await asyncio.sleep(1.0)

    def _get_clipboard_text(self) -> str:
        try:
            system = platform.system().lower()
            if system == "linux":
                session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
                if session_type == "wayland":
                    try:
                        result = subprocess.run(
                            ["wl-paste", "--no-newline"],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=1.0,
                        )
                        return result.stdout
                    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                        pass
                else:
                    try:
                        result = subprocess.run(
                            ["xclip", "-selection", "clipboard", "-o"],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=1.0,
                        )
                        return result.stdout
                    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                        try:
                            result = subprocess.run(
                                ["xsel", "--clipboard", "--output"],
                                capture_output=True,
                                text=True,
                                check=True,
                                timeout=1.0,
                            )
                            return result.stdout
                        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                            pass

            return pyperclip.paste()

        except Exception as e:
            logger.exception("Failed to read clipboard")
            return ""