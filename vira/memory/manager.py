# vira/memory/manager.py
from typing import List, Dict, Any, Optional
from .base import MemoryItem, MemoryStore

class MemoryManager:
    def __init__(self):
        self._stores: Dict[str, MemoryStore] = {}
        self._default_store = None

    def register_store(self, name: str, store: MemoryStore, is_default: bool = False):
        self._stores[name] = store
        if is_default:
            self._default_store = store

    async def store(self, content: str, store_name: Optional[str] = None, **kwargs) -> str:
        # Dummy implementation
        return "stub_id"

    async def retrieve(self, query: str, store_name: Optional[str] = None, limit: int = 10) -> List[MemoryItem]:
        return []

    async def summarize(self, store_name: Optional[str] = None, max_items: int = 20) -> str:
        return "Stub summary"

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