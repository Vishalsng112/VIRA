# vira/agent_orchestration/capability_registry.py
from typing import Dict, List, Optional
from pydantic import BaseModel

class Capability(BaseModel):
    name: str
    description: str
    provider_type: str  # "agent" or "tool"
    provider_id: str    # agent_id or tool_id
    input_schema: Optional[Dict] = None
    output_schema: Optional[Dict] = None
    tags: List[str] = []

class CapabilityRegistry:
    """Index of agent and tool capabilities for discovery."""

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}

    def register(self, capability: Capability) -> str:
        key = f"{capability.provider_type}:{capability.provider_id}:{capability.name}"
        self._capabilities[key] = capability
        return key

    def unregister(self, provider_type: str, provider_id: str):
        to_remove = [k for k, v in self._capabilities.items() 
                     if v.provider_type == provider_type and v.provider_id == provider_id]
        for k in to_remove:
            del self._capabilities[k]

    def search(self, query: str, tags: List[str] = None) -> List[Capability]:
        # Simple keyword search; could be enhanced with embeddings
        results = []
        query_lower = query.lower()
        for cap in self._capabilities.values():
            if query_lower in cap.name.lower() or query_lower in cap.description.lower():
                if tags and not any(t in cap.tags for t in tags):
                    continue
                results.append(cap)
        return results

    def get_by_provider(self, provider_type: str, provider_id: str) -> List[Capability]:
        return [c for c in self._capabilities.values() 
                if c.provider_type == provider_type and c.provider_id == provider_id]