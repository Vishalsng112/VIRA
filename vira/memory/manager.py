# vira/memory/manager.py
from typing import List, Dict, Any, Optional
from .base import MemoryItem, MemoryStore
from vira.auth import database

class MemoryManager:
    def __init__(self):
        self._stores: Dict[str, MemoryStore] = {}
        self._default_store = None

    def register_store(self, name: str, store: MemoryStore, is_default: bool = False):
        self._stores[name] = store
        if is_default:
            self._default_store = store

    async def store(self, content: str, store_name: Optional[str] = None, **kwargs) -> str:
        user_id = kwargs.pop("user_id", None)
        return database.store_memory(user_id=user_id, content=content, **kwargs)

    async def retrieve(
        self,
        query: str,
        store_name: Optional[str] = None,
        limit: int = 10,
        user_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        memory_type: Optional[str] = None,
    ) -> List[MemoryItem]:
        if user_id is None:
            raise ValueError("user_id is required for scoped memory")
        return [
            MemoryItem(
                id=item["id"],
                content=item["content"],
                metadata={
                    **item["metadata"],
                    "user_id": item["user_id"],
                    "agent_id": item["agent_id"],
                    "conversation_id": item["conversation_id"],
                    "type": item["memory_type"],
                },
            )
            for item in database.search_memories(
                user_id=user_id,
                query=query,
                limit=limit,
                agent_id=agent_id,
                conversation_id=conversation_id,
                memory_type=memory_type,
            )
        ]

    async def summarize(self, store_name: Optional[str] = None, max_items: int = 20) -> str:
        return ""

    async def delete(self, memory_id: str, user_id: Optional[int] = None) -> bool:
        return database.delete_memory(memory_id, user_id)

    async def compact(self, user_id: Optional[int] = None) -> int:
        return database.compact_memories(user_id)

    def _get_store(self, name: Optional[str]) -> MemoryStore:
        # Return a dummy store that satisfies the interface
        class DummyStore(MemoryStore):
            async def store(self, item): return "id"
            async def retrieve(self, query, limit=10): return []
            async def retrieve_by_id(self, item_id): return None
            async def retrieve_by_metadata(self, filters, limit=10): return []
            async def delete(self, item_id): return True
            async def clear(self): pass
            async def compact(self): return 0
        return DummyStore()