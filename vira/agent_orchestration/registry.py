# vira/agent_orchestration/registry.py
import time
from typing import Dict, List, Optional, Protocol, Set
from pydantic import BaseModel, Field
from enum import Enum
import uuid
import asyncio
from dataclasses import dataclass, field

class AgentState(str, Enum):
    INITIALIZED = "initialized"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    FAILED = "failed"
    TERMINATED = "terminated"

class AgentCapability(BaseModel):
    name: str
    description: str
    input_schema: Optional[Dict] = None
    output_schema: Optional[Dict] = None

class AgentMetadata(BaseModel):
    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: List[AgentCapability] = []
    subscribed_events: List[str] = []  # event types this agent handles
    interval_seconds: Optional[float] = None  # for periodic agents
    state: AgentState = AgentState.INITIALIZED
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class AgentRegistry:
    """Central registry for agent metadata and lifecycle."""

    def __init__(self):
        self._agents: Dict[str, AgentMetadata] = {}
        self._agent_instances: Dict[str, "BaseAgent"] = {}
        self._lock = asyncio.Lock()

    async def register(self, agent: "BaseAgent") -> str:
        """Register an agent instance, store metadata, and transition to INITIALIZED."""
        async with self._lock:
            if agent.agent_id in self._agents:
                raise ValueError(f"Agent {agent.agent_id} already registered")
            meta = AgentMetadata(
                agent_id=agent.agent_id,
                name=agent.name,
                description=agent.description,
                capabilities=agent.capabilities,
                subscribed_events=agent.subscribed_events,
                interval_seconds=agent.interval_seconds,
                state=AgentState.INITIALIZED
            )
            self._agents[agent.agent_id] = meta
            self._agent_instances[agent.agent_id] = agent
            return agent.agent_id

    async def unregister(self, agent_id: str) -> bool:
        """Remove an agent; stop it first if running."""
        async with self._lock:
            if agent_id not in self._agents:
                return False
            agent = self._agent_instances[agent_id]
            if agent.state in (AgentState.RUNNING, AgentState.WAITING):
                await agent.stop()
            del self._agents[agent_id]
            del self._agent_instances[agent_id]
            return True

    async def get_metadata(self, agent_id: str) -> Optional[AgentMetadata]:
        return self._agents.get(agent_id)

    async def get_instance(self, agent_id: str) -> Optional["BaseAgent"]:
        return self._agent_instances.get(agent_id)

    async def list_agents(self, state: Optional[AgentState] = None) -> List[AgentMetadata]:
        if state:
            return [m for m in self._agents.values() if m.state == state]
        return list(self._agents.values())

    async def update_state(self, agent_id: str, state: AgentState) -> bool:
        async with self._lock:
            if agent_id not in self._agents:
                return False
            self._agents[agent_id].state = state
            self._agents[agent_id].updated_at = time.time()
            return True

    async def find_by_capability(self, capability_name: str) -> List[AgentMetadata]:
        return [m for m in self._agents.values() 
                if any(c.name == capability_name for c in m.capabilities)]

    async def find_by_event(self, event_type: str) -> List[AgentMetadata]:
        return [m for m in self._agents.values() 
                if event_type in m.subscribed_events or "*" in m.subscribed_events]