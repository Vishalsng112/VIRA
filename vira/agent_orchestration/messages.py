# vira/agent_orchestration/messages.py
from pydantic import BaseModel
from typing import Optional, List, Any

class AgentMessage(BaseModel):
    type: str                     # event type (matches kernel Event)
    data: Any
    sender_agent_id: Optional[str] = None   # None means external/kernel event
    target_agent_ids: Optional[List[str]] = None
    exclude_sender: bool = True