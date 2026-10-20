# vira/content/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class LLMInput(BaseModel):
    text: str
    metadata: Dict[str, Any] = {}
    embeddings: Optional[List[float]] = None
    source: Optional[str] = None
    modality: str  # "text", "image", "audio", "video", "pdf", etc.

class ContentProcessor(ABC):
    """Process a specific modality into LLMInput."""

    @abstractmethod
    async def process(self, content: Any, **kwargs) -> LLMInput:
        pass