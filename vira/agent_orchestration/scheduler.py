import asyncio
import time
from collections import deque
from loguru import logger
from typing import Optional, Dict, Any, Deque, Tuple
from dataclasses import dataclass, field
from .registry import AgentState
from vira.agent.base import BaseAgent
from vira.kernel.event_bus import Event

# logger = logging.getLogger(__name__)

@dataclass
class AgentTask:
    agent_id: str
    event: Optional[Event] = None
    input_data: Optional[Dict] = None
    timeout: float = 60.0
    created_at: float = field(default_factory=time.time)


class RuntimeScheduler:
    """Schedules agent work.

    Multi-user / multi-device behaviour:

    * Re-entrant agents (``agent.reentrant``) run each event concurrently, bounded
      by ``max_concurrent`` - e.g. chat for several users at once.
    * Other agents process one event at a time.  Events that arrive while the
      agent is busy are queued (bounded, oldest dropped first with a warning)
      instead of being discarded, so one device's burst cannot silently drop
      another user's or device's events.
    """

    def __init__(self, registry, max_concurrent: int = 10, max_queue_per_agent: int = 1000):
        self._registry = registry          # <-- store registry
        self._max_concurrent = max_concurrent
        self._max_queue = max_queue_per_agent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._queues: Dict[str, Deque[Tuple[Optional[Event], Optional[Dict], float]]] = {}
        self._dropped: Dict[str, int] = {}
        self._failures: Dict[str, int] = {}

    def queue_depth(self, agent_id: str) -> int:
        return len(self._queues.get(agent_id, ()))

    async def schedule_agent(self, agent: BaseAgent, event: Optional[Event] = None,
                             input_data: Optional[Dict] = None, timeout: float = 60.0):
        if getattr(agent, "reentrant", False):
            await self._run_slot(agent, event, input_data, timeout, track=False)
            return

        queue = self._queues.setdefault(agent.agent_id, deque())
        if agent.agent_id in self._running_tasks:
            if len(queue) >= self._max_queue:
                queue.popleft()
                self._dropped[agent.agent_id] = self._dropped.get(agent.agent_id, 0) + 1
                logger.warning(
                    f"Agent {agent.agent_id} queue full; dropped oldest event "
                    f"(total dropped: {self._dropped[agent.agent_id]})"
                )
            queue.append((event, input_data, timeout))
            return

        # This call becomes the agent's worker and drains whatever queues up.
        pending: Optional[Tuple] = (event, input_data, timeout)
        while pending is not None:
            await self._run_slot(agent, *pending, track=True)
            pending = queue.popleft() if queue else None

    async def _run_slot(self, agent: BaseAgent, event, input_data, timeout, track: bool):
        if track:
            await self._registry.update_state(agent.agent_id, AgentState.RUNNING)
        await self._semaphore.acquire()
        try:
            task = asyncio.create_task(
                self._run_agent_with_timeout(agent, event, input_data, timeout, track)
            )
            if track:
                self._running_tasks[agent.agent_id] = task
            await task
        finally:
            self._semaphore.release()
            if track:
                self._running_tasks.pop(agent.agent_id, None)

    async def run_agent(self, agent: BaseAgent, input_data: Dict, timeout: float = 60.0) -> Any:
        await self._registry.update_state(agent.agent_id, AgentState.RUNNING)
        try:
            result = await asyncio.wait_for(
                agent.run(input_data=input_data),
                timeout=timeout
            )
            await self._registry.update_state(agent.agent_id, AgentState.READY)
            return result
        except asyncio.TimeoutError:
            await self._registry.update_state(agent.agent_id, AgentState.FAILED)
            raise
        except Exception as e:
            await self._registry.update_state(agent.agent_id, AgentState.FAILED)
            raise

    async def _run_agent_with_timeout(self, agent, event, input_data, timeout, track=True):
        try:
            if event:
                await agent.handle(event)
            else:
                await agent.run(input_data=input_data)
        except Exception as e:
            # A failure while serving one user's/device's event must not disable
            # the agent for everyone else: record it and return to READY.
            self._failures[agent.agent_id] = self._failures.get(agent.agent_id, 0) + 1
            logger.error(f"Agent {agent.agent_id} failed handling an event: {e}")
            agent.state = AgentState.READY
        if track:
            await self._registry.update_state(agent.agent_id, AgentState.READY)
