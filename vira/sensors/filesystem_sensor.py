import asyncio
from loguru import logger
import fnmatch
import time
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from vira.sensors.base_sensor import BaseSensor
from vira.kernel.event_bus import Event, EventPriority

# logger = logging.getLogger(__name__)


class FileSystemSensor(BaseSensor):
    """
    Watches a directory and publishes file system events with debouncing.
    """

    def __init__(
        self,
        watch_path: str,
        event_bus=None,
        dispatcher=None,
        metrics_manager=None,
        recursive: bool = True,
        event_types: Optional[List[str]] = None,
        include_patterns: Optional[List[str]] = None,
        ignore_patterns: Optional[List[str]] = None,
        debounce_seconds: float = 0.3,
    ):
        super().__init__("filesystem_sensor")
        self.watch_path = Path(watch_path).resolve()
        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self._publisher = dispatcher or event_bus
        if self._publisher is None:
            raise ValueError("Either event_bus or dispatcher must be provided")

        self.metrics_manager = metrics_manager
        self.recursive = recursive
        self._event_types = event_types or ["created", "modified", "deleted", "moved"]
        self._include_patterns = include_patterns or []
        self._ignore_patterns = ignore_patterns or []
        self._debounce_seconds = debounce_seconds
        self._last_event_time: Dict[Tuple[str, str], float] = {}   # (path, type) -> timestamp
        self._observer: Optional[Observer] = None
        self._loop = asyncio.get_event_loop()
        self._running = False

    async def start(self) -> None:
        if not self.watch_path.exists():
            logger.error(f"Watch path does not exist: {self.watch_path}")
            return
        if not self.watch_path.is_dir():
            logger.error(f"Watch path is not a directory: {self.watch_path}")
            return

        self._running = True
        self._observer = Observer()
        handler = self._create_handler()
        self._observer.schedule(handler, str(self.watch_path), recursive=self.recursive)
        self._observer.start()
        logger.info(
            f"FileSystemSensor started: watching {self.watch_path} "
            f"(recursive={self.recursive}, include={self._include_patterns or 'all'}, "
            f"debounce={self._debounce_seconds}s)"
        )

    async def stop(self) -> None:
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        logger.info("FileSystemSensor stopped")

    async def read(self) -> dict:
        return {
            "watching": str(self.watch_path),
            "recursive": self.recursive,
            "event_types": self._event_types,
            "include_patterns": self._include_patterns,
            "ignore_patterns": self._ignore_patterns,
            "debounce_seconds": self._debounce_seconds,
            "running": self._running,
        }

    def _create_handler(self) -> FileSystemEventHandler:
        class EventHandler(FileSystemEventHandler):
            def __init__(self, sensor):
                self.sensor = sensor

            def _should_process(self, path: str) -> bool:
                if self.sensor._include_patterns:
                    if not any(fnmatch.fnmatch(path, pattern) for pattern in self.sensor._include_patterns):
                        return False
                if self.sensor._ignore_patterns:
                    if any(fnmatch.fnmatch(path, pattern) for pattern in self.sensor._ignore_patterns):
                        return False
                return True

            def _is_debounced(self, path: str, event_type: str) -> bool:
                key = (path, event_type)
                now = time.time()
                last = self.sensor._last_event_time.get(key, 0)
                if now - last < self.sensor._debounce_seconds:
                    return True
                self.sensor._last_event_time[key] = now
                return False

            def on_created(self, event):
                if event.is_directory:
                    return
                if not self._should_process(event.src_path):
                    return
                if "created" not in self.sensor._event_types:
                    return
                if self._is_debounced(event.src_path, "created"):
                    return
                self.sensor._loop.call_soon_threadsafe(
                    asyncio.create_task,
                    self.sensor._publish_event("file.created", {"path": event.src_path})
                )

            def on_modified(self, event):
                if event.is_directory:
                    return
                if not self._should_process(event.src_path):
                    return
                if "modified" not in self.sensor._event_types:
                    return
                if self._is_debounced(event.src_path, "modified"):
                    return
                self.sensor._loop.call_soon_threadsafe(
                    asyncio.create_task,
                    self.sensor._publish_event("file.modified", {"path": event.src_path})
                )

            def on_deleted(self, event):
                if event.is_directory:
                    return
                if not self._should_process(event.src_path):
                    return
                if "deleted" not in self.sensor._event_types:
                    return
                if self._is_debounced(event.src_path, "deleted"):
                    return
                self.sensor._loop.call_soon_threadsafe(
                    asyncio.create_task,
                    self.sensor._publish_event("file.deleted", {"path": event.src_path})
                )

            def on_moved(self, event):
                if event.is_directory:
                    return
                if not self._should_process(event.src_path) or not self._should_process(event.dest_path):
                    return
                if "moved" not in self.sensor._event_types:
                    return
                if self._is_debounced(event.dest_path, "moved"):
                    return
                self.sensor._loop.call_soon_threadsafe(
                    asyncio.create_task,
                    self.sensor._publish_event(
                        "file.moved",
                        {"src": event.src_path, "dest": event.dest_path}
                    )
                )

        return EventHandler(self)

    async def _publish_event(self, event_type: str, data: dict):
        if not self._publisher:
            return
        event = Event(
            type=event_type,
            data=data,
            source=self.name,
            priority=EventPriority.NORMAL
        )
        await self._publisher.publish(event)
        logger.debug(f"Published {event_type}: {data}")