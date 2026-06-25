# vira/llm/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator
from pydantic import BaseModel

class LLMResponse(BaseModel):
    text: str
    model: str
    usage: Dict[str, int]  # {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    finish_reason: Optional[str] = None
    raw: Any = None

class BaseLLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a complete response."""
        pass

    @abstractmethod
    async def stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        """Stream response tokens."""
        pass

    @abstractmethod
    async def generate_structured(self, prompt: str, schema: Dict, **kwargs) -> Dict:
        """Generate structured output conforming to a JSON schema."""
        pass

    @abstractmethod
    async def tool_call(self, prompt: str, tools: List[Dict], **kwargs) -> Dict:
        """Call tools with the LLM."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass