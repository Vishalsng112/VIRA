# vira/agent/messaging.py
from typing import Dict, List, Any, Optional
import asyncio
from pydantic import BaseModel, Field
from datetime import datetime

class AgentMessage(BaseModel):
    id: str
    from_agent: str
    to_agent: str
    content: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)
    correlation_id: Optional[str] = None

class AgentMailbox:
    """Each agent has a mailbox for incoming messages."""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._queue: asyncio.Queue = asyncio.Queue()

    async def put(self, message: AgentMessage):
        await self._queue.put(message)

    async def get(self) -> AgentMessage:
        return await self._queue.get()

class MessageBus:
    """Global message bus for agent‑to‑agent communication."""
    def __init__(self):
        self._mailboxes: Dict[str, AgentMailbox] = {}

    def register_agent(self, agent_id: str):
        self._mailboxes[agent_id] = AgentMailbox(agent_id)

    async def send(self, message: AgentMessage):
        if message.to_agent not in self._mailboxes:
            raise ValueError(f"Agent {message.to_agent} not registered")
        await self._mailboxes[message.to_agent].put(message)

    def get_mailbox(self, agent_id: str) -> AgentMailbox:
        return self._mailboxes[agent_id]