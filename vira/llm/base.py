# vira/llm/base.py
import json
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator
from pydantic import BaseModel

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: Any) -> Dict[str, Any]:
    """Parse a JSON object from an LLM response.

    Handles fenced JSON, surrounding prose and the occasional trailing text.
    Raises ``ValueError`` when no JSON object can be recovered, so callers get a
    clear failure instead of a raw string that violates the return contract.
    """
    if isinstance(text, dict):
        return text
    if text is None:
        raise ValueError("LLM returned no structured content")
    raw = str(text).strip()
    fenced = _JSON_FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = None
    if value is None:
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
            except ValueError:
                continue
            if isinstance(value, dict):
                break
            value = None
    if not isinstance(value, dict):
        raise ValueError("LLM response was not a JSON object")
    return value


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