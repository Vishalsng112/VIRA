from loguru import logger
import asyncio
from typing import Optional, List
from vira.kernel.event_bus import Event
from vira.agent_orchestration.base import BaseAgent
from .registry import AgentRegistry, AgentState
from vira.agent_orchestration.messages import AgentMessage
from vira.agent_runtime.runtime import AgentRuntime

# logger = logging.getLogger(__name__)

# Global scheduler reference (set during module startup)
_runtime_scheduler = None

def set_runtime_scheduler(scheduler):
    global _runtime_scheduler
    _runtime_scheduler = scheduler

def get_runtime_scheduler():
    if _runtime_scheduler is None:
        raise RuntimeError("RuntimeScheduler not set")
    return _runtime_scheduler


class EventRouter:
    def __init__(self, event_bus, registry: AgentRegistry, pipeline=None, scheduler=None, agent_message_bus=None):
        self._event_bus = event_bus
        self._registry = registry
        self._pipeline = pipeline
        self._scheduler = scheduler          # injected directly
        self._agent_message_bus = agent_message_bus   # <-- new
        self._subscription_id = None
        self._agent_subscription = None   # for the agent bus
        self._running = False

    async def start(self):
        self._running = True
        # self._subscription_id = self._event_bus.subscribe_all(self._route_event)
        self._subscription_id = self._event_bus.subscribe_all(self._route_kernel_event)
        # Agent bus subscription (wildcard)
        if self._agent_message_bus:
            await self._agent_message_bus.subscribe("*", self._route_agent_message)
        logger.info("EventRouter started")

    async def stop(self):
        self._running = False
        if self._subscription_id:
            # self._event_bus.unsubscribe_all(self._route_event)
            self._event_bus.unsubscribe_all(self._route_kernel_event)
        # Unsubscribe from agent bus (we need to store the callback reference)
        # For simplicity, we'll store the callback and unsubscribe.
        if self._agent_message_bus and self._agent_subscription:
            await self._agent_message_bus.unsubscribe("*", self._route_agent_message)
        logger.info("EventRouter stopped")


    async def _route_kernel_event(self, event: Event):
        # Convert kernel event to an internal message structure
        # We'll create a pseudo AgentMessage with no sender (None)
        msg = AgentMessage(
            type=event.type,
            data=event.data,
            sender_agent_id=None,
            target_agent_ids=None,
            exclude_sender=False
        )
        await self._route_message(msg)

    async def _route_agent_message(self, msg: AgentMessage):
        # is the Agent has sent this message
        if msg.type == "agent.response":
            kernel_event = Event(
                type=msg.type,
                data=msg.data,
                source=msg.sender_agent_id or "agent",
            )
            await self._event_bus.publish(kernel_event)
            logger.debug(f"Forwarded agent.response to kernel bus: {kernel_event.data}")
        await self._route_message(msg)

    async def _route_message(self, msg: AgentMessage):
        if not self._running:
            return

        # 1. Find agents that handle this event type
        candidates = await self._registry.find_by_event(msg.type)

        # 2. Filter by target if specified
        if msg.target_agent_ids is not None:
            target_set = set(msg.target_agent_ids)
            candidates = [m for m in candidates if m.agent_id in target_set]

        # 3. Exclude sender if requested
        if msg.exclude_sender and msg.sender_agent_id:
            candidates = [m for m in candidates if m.agent_id != msg.sender_agent_id]

        if not candidates:
            return

        # 4. Optionally apply pipeline enrichment (skipped for agent messages)

        # 5. Schedule each matching agent
        for meta in candidates:
            agent = await self._registry.get_instance(meta.agent_id)
            if not agent:
                continue
            if agent.state not in (AgentState.READY, AgentState.WAITING):
                continue
            if not await agent.can_handle(msg):   # we need to adapt can_handle to accept msg
                continue
            scheduler = self._scheduler or get_runtime_scheduler()
            asyncio.create_task(scheduler.schedule_agent(agent, event=msg))  # event can be the msg

    # async def _route_event(self, event: Event):
    #     if not self._running:
    #         return

    #     # ---- DEBUG ----
    #     logger.info(f"[ROUTER] Received event: {event.type} from {event.source}")

    #     # 1. Find agents that handle this event type
    #     matching = await self._registry.find_by_event(event.type)
    #     logger.info(f"[ROUTER] Matching agents for {event.type}: {[m.agent_id for m in matching]}")

    #     if not matching:
    #         return

    #     # # 2. Optional pipeline enrichment
    #     # if self._pipeline:
    #     #     try:
    #     #         event = await self._pipeline.process(event)
    #     #     except Exception as e:
    #     #         logger.error(f"Pipeline enrichment failed: {e}")

    #     # 3. Fan‑out
    #     for meta in matching:
    #         agent = await self._registry.get_instance(meta.agent_id)
    #         if not agent:
    #             logger.warning(f"[ROUTER] Agent instance not found for {agent.agent_id}")
    #             continue

    #         if agent.state not in (AgentState.READY, AgentState.WAITING):
    #             logger.warning(f"[ROUTER] Agent:{agent.agent_id} state is {agent.state}, skipping")
    #             continue


    #         can_handle = await agent.can_handle(event)
    #         logger.info(f"[ROUTER] Agent:{agent.agent_id} can_handle({event.type}) = {can_handle}")

    #         if not can_handle:
    #             continue

    #         logger.info(f"[ROUTER] Scheduling Agent:{agent.agent_id} for event {event.type}")
    #         # Use injected scheduler or global
    #         scheduler = self._scheduler or get_runtime_scheduler()
    #         asyncio.create_task(scheduler.schedule_agent(agent, event=event))

    async def _trigger_agent(self, agent: BaseAgent, event: Event):
        # This method is now unused; scheduling is done directly in _route_event.
        # Keep for backward compatibility or remove.
        scheduler = self._scheduler or get_runtime_scheduler()
        await scheduler.schedule_agent(agent, event=event)