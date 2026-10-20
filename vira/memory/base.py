# vira/memory/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.now)
    ttl: Optional[int] = None

class MemoryStore(ABC):
    @abstractmethod
    async def store(self, item: MemoryItem) -> str:
        pass

    @abstractmethod
    async def retrieve(self, query: str, limit: int = 10) -> List[MemoryItem]:
        pass

    @abstractmethod
    async def retrieve_by_id(self, item_id: str) -> Optional[MemoryItem]:
        pass

    @abstractmethod
    async def retrieve_by_metadata(self, filters: Dict, limit: int = 10) -> List[MemoryItem]:
        pass

    @abstractmethod
    async def delete(self, item_id: str) -> bool:
        pass

    @abstractmethod
    async def clear(self):
        pass

    @abstractmethod
    async def compact(self) -> int:
        pass