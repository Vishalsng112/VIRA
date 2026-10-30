"""In-process progress hub: lets the chat API show what the agent is doing.

The agent loop calls ``hub.emit(run_id, event)`` for every thinking step, tool
call, validation and so on.  Every event is recorded (so the trace can be saved
with the answer and replayed after a page reload) and, when a client is
streaming, pushed to its queue.  With no listener the cost is one list append.
"""
import asyncio
import threading
from typing import Any, Dict, List, Optional

MAX_EVENTS = 150  # per run; keeps stored traces small


class _Run:
    __slots__ = ("trace", "queue")

    def __init__(self, queue: Optional[asyncio.Queue]):
        self.trace: List[Dict[str, Any]] = []
        self.queue = queue


class ProgressHub:
    def __init__(self):
        self._runs: Dict[str, _Run] = {}
        self._lock = threading.Lock()

    def begin(self, run_id: str, queue: Optional[asyncio.Queue] = None) -> None:
        with self._lock:
            self._runs[run_id] = _Run(queue)

    def emit(self, run_id: Optional[str], event: Dict[str, Any]) -> None:
        """Never raises: progress reporting must not be able to break a chat."""
        if not run_id:
            return
        run = self._runs.get(run_id)
        if run is None:
            return
        try:
            if len(run.trace) < MAX_EVENTS:
                run.trace.append(event)
            if run.queue is not None:
                run.queue.put_nowait(event)
        except Exception:
            pass

    def end(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            run = self._runs.pop(run_id, None)
        return run.trace if run else []


hub = ProgressHub()
