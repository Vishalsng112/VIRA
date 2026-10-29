# vira/agent_orchestration/messages.py
from pydantic import BaseModel
from typing import Optional, List, Any

class AgentMessage(BaseModel):
    type: str                     # event type (matches kernel Event)
    data: Any
    sender_agent_id: Optional[str] = None   # None means external/kernel event
    target_agent_ids: Optional[List[str]] = None
    exclude_sender: bool = True
    # Provenance copied from the kernel event so agents can keep per-device /
    # per-user state apart (multi-device design 7.5).  Server-resolved values.
    event_id: Optional[str] = None
    correlation_id: Optional[str] = None
    device_id: Optional[str] = None
    actor_user_id: Optional[int] = None
    source_component: Optional[str] = None
