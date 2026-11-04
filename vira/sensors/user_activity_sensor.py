import asyncio
from loguru import logger
import time
from pathlib import Path
import os
import subprocess

from vira.sensors.base_sensor import BaseSensor
from vira.kernel import Event, EventPriority

# logger = logging.getLogger(__name__)


class UserActivitySensor(BaseSensor):
    """
    Wayland-only clipboard change sensor.

    Wayland does not provide a general clipboard-change subscription to
    unrelated clients, so this is deliberately a low-rate poll. Clipboard
    contents are not emitted unless explicitly enabled.
    """

    def __init__(
        self,
        interval: float = 0.5,
        event_bus=None,
        dispatcher=None,
        storage_dir: str = "data/user_activity",
        include_content: bool = False,
        max_content_chars: int = 0,
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
        self.include_content = include_content
        self.max_content_chars = max_content_chars
        if self.include_content and self.max_content_chars <= 0:
            raise ValueError("max_content_chars must be positive when content is enabled")

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
        return {
            "has_clipboard": self._last_clipboard is not None,
            "content_length": len(self._last_clipboard or ""),
        }

    async def _run(self):
        while self._running:
            try:
                current = await asyncio.to_thread(self._get_clipboard_text)

                if current != self._last_clipboard:
                    self._last_clipboard = current
                    if self._publisher:
                        data = {
                            "timestamp": int(time.time()),
                            "changed": True,
                            "content_length": len(current),
                        }
                        if self.include_content:
                            data["content"] = current[:self.max_content_chars]

                        await self._publisher.publish(
                            Event(
                                type="sensor.clipboard.changed",
                                data=data,
                                source=self.name,
                                priority=EventPriority.LOW,
                            )
                        )
                        logger.debug("Clipboard changed (content suppressed)")

                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Clipboard polling failed")
                await asyncio.sleep(1.0)

    def _get_clipboard_text(self) -> str:
        try:
            if os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
                raise RuntimeError("Clipboard sensor requires XDG_SESSION_TYPE=wayland")
            result = subprocess.run(
                ["wl-paste", "--no-newline"],
                capture_output=True,
                text=True,
                check=True,
                timeout=1.0,
            )
            return result.stdout

        except Exception as e:
            logger.exception("Failed to read clipboard")
            raise RuntimeError("Wayland clipboard read failed") from e