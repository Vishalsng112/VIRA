import asyncio
import time
from loguru import logger
from typing import Optional, Dict, Any
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
    def __init__(self, registry, max_concurrent: int = 10):
        self._registry = registry          # <-- store registry
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def schedule_agent(self, agent: BaseAgent, event: Optional[Event] = None, 
                             input_data: Optional[Dict] = None, timeout: float = 60.0):
        if agent.agent_id in self._running_tasks:
            logger.warning(f"Agent {agent.agent_id} already running, skipping")
            return

        await self._registry.update_state(agent.agent_id, AgentState.RUNNING)

        await self._semaphore.acquire()
        try:
            task = asyncio.create_task(
                self._run_agent_with_timeout(agent, event, input_data, timeout)
            )
            self._running_tasks[agent.agent_id] = task
            await task
        finally:
            self._semaphore.release()
            if agent.agent_id in self._running_tasks:
                del self._running_tasks[agent.agent_id]

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

    async def _run_agent_with_timeout(self, agent, event, input_data, timeout):
        try:
            if event:
                await agent.handle(event)
            else:
                await agent.run(input_data=input_data)
            await self._registry.update_state(agent.agent_id, AgentState.READY)
        except Exception as e:
            logger.error(f"Agent {agent.agent_id} failed: {e}")
            await self._registry.update_state(agent.agent_id, AgentState.FAILED)