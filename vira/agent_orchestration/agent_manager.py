# vira/agent_orchestration/agent_manager.py
import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger

from vira.agent.base import BaseAgent
from .registry import AgentRegistry, AgentState
from .scheduler import RuntimeScheduler
from .router import EventRouter
from .capability_registry import CapabilityRegistry, Capability
from .planner import Planner
from vira.kernel.event_bus import EventBus, Event
from vira.kernel.event_dispatcher import EventDispatcher


class AgentManager:
    """Central manager for agent lifecycle, routing, and scheduling."""

    def __init__(self, event_bus: EventBus, dispatcher: EventDispatcher, registry: AgentRegistry):
        self.event_bus = event_bus
        self.dispatcher = dispatcher
        self.registry = registry
        self.capability_registry = CapabilityRegistry()
        self.scheduler = RuntimeScheduler(registry, max_concurrent=10)
        self.router = EventRouter(
            event_bus=event_bus,
            registry=registry,
            scheduler=self.scheduler,
            agent_message_bus=None
        )
        self.planner = Planner(registry, self.capability_registry)
        self._agent_instances: Dict[str, BaseAgent] = {}

    async def start(self):
        await self.router.start()
        logger.info("AgentManager started")

    async def stop(self):
        await self.router.stop()
        for agent_id, agent in self._agent_instances.items():
            if agent.state not in (AgentState.TERMINATED, AgentState.FAILED):
                await agent.stop()
        logger.info("AgentManager stopped")

    async def register_agent(self, agent: BaseAgent) -> str:
        agent_id = await self.registry.register(agent)
        self._agent_instances[agent_id] = agent
        await agent.initialize()
        await agent.start()
        for cap in agent.capabilities:
            self.capability_registry.register(
                Capability(
                    name=cap.name,
                    description=cap.description,
                    provider_type="agent",
                    provider_id=agent_id,
                    input_schema=cap.input_schema,
                    output_schema=cap.output_schema,
                    tags=[],
                )
            )
        await self.dispatcher.publish(Event(
            type="agent.registered",
            data={"agent_id": agent_id, "name": agent.name},
            source="AgentManager"
        ))
        logger.info(f"Agent registered: {agent.name} ({agent_id})")
        return agent_id

    async def unregister_agent(self, agent_id: str) -> bool:
        agent = self._agent_instances.get(agent_id)
        if not agent:
            return False
        await agent.stop()
        await self.registry.unregister(agent_id)
        self.capability_registry.unregister("agent", agent_id)
        del self._agent_instances[agent_id]
        await self.dispatcher.publish(Event(
            type="agent.unregistered",
            data={"agent_id": agent_id},
            source="AgentManager"
        ))
        return True

    async def list_agents(self) -> List[Dict[str, Any]]:
        metas = await self.registry.list_agents()
        result = []
        for meta in metas:
            agent = self._agent_instances.get(meta.agent_id)
            state = agent.state if agent else meta.state
            result.append({
                "agent_id": meta.agent_id,
                "name": meta.name,
                "description": meta.description,
                "state": state.value,
                "capabilities": [c.dict() for c in meta.capabilities],
                "subscribed_events": meta.subscribed_events,
                "interval_seconds": meta.interval_seconds,
                "created_at": meta.created_at,
                "updated_at": meta.updated_at,
            })
        return result

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        meta = await self.registry.get_metadata(agent_id)
        if not meta:
            return None
        agent = self._agent_instances.get(agent_id)
        state = agent.state if agent else meta.state
        return {
            "agent_id": meta.agent_id,
            "name": meta.name,
            "description": meta.description,
            "state": state.value,
            "capabilities": [c.dict() for c in meta.capabilities],
            "subscribed_events": meta.subscribed_events,
            "interval_seconds": meta.interval_seconds,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
        }

    async def load_agent_from_file(self, file_path: str, class_name: str = None) -> str:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Agent file not found: {file_path}")

        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[file_path.stem] = module
        spec.loader.exec_module(module)

        if class_name:
            agent_cls = getattr(module, class_name, None)
        else:
            agent_cls = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseAgent) and attr != BaseAgent:
                    agent_cls = attr
                    break

        if not agent_cls:
            raise ValueError(f"No BaseAgent subclass found in {file_path}")

        agent = agent_cls()
        return await self.register_agent(agent)