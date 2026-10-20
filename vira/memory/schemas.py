# vira/memory/schemas.py
class MemoryEntry(BaseModel):
    id: str
    agent_id: str
    type: str  # short_term, long_term, episodic, semantic
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    expires_at: Optional[datetime] = None
    importance: float = 0.0