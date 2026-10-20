# vira/agent_runtime/context.py (extending earlier)
class AgentContext(BaseModel):
    agent_id: str
    session: Dict[str, Any]
    kernel_snapshot: Dict[str, Any]
    current_time: datetime
    environment: Dict[str, str]  # system env vars relevant
    permissions: List[str]