# vira/agent_orchestration/events.py
from pydantic import BaseModel
from typing import Dict, Any, Optional

class AgentEvent(BaseModel):
    agent_id: str
    event_type: str
    data: Dict

class TaskEvent(BaseModel):
    task_id: str
    workflow_id: str
    step_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None

class MemoryEvent(BaseModel):
    operation: str  # store, retrieve, delete
    agent_id: str
    memory_id: Optional[str] = None
    content: Optional[str] = None