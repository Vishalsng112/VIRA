# vira/llm/manager.py
import random
from typing import List, Optional
from vira.llm.base import BaseLLMProvider, LLMResponse
from typing import Dict
from loguru import logger

class LLMManager:
    """
    Manages multiple providers with routing, failover, and fallback.
    """

    def __init__(self):
        self._providers: Dict[str, BaseLLMProvider] = {}
        self._routing_config: Dict[str, List[str]] = {}  # model -> list of provider names
        self._tool_registry = None   # will be injected later


    def set_tool_registry(self, tool_registry):
        self._tool_registry = tool_registry

    def register_provider(self, name: str, provider: BaseLLMProvider, models: List[str]):
        self._providers[name] = provider
        for model in models:
            if model not in self._routing_config:
                self._routing_config[model] = []
            self._routing_config[model].append(name)

    async def generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> LLMResponse:
        """Route to appropriate provider(s) with failover."""
        if model and model in self._routing_config:
            providers = self._routing_config[model]
        else:
            # Use default or pick first available
            providers = list(self._providers.keys())

        # Try each provider in order
        for provider_name in providers:
            try:
                provider = self._providers[provider_name]
                return await provider.generate(prompt, **kwargs)
            except Exception as e:
                logger.warning(f"Provider {provider_name} failed: {e}")
                continue
        raise RuntimeError("All LLM providers failed")


    async def get_tool_schemas(self) -> List[dict]:
        if not self._tool_registry:
            return []
        schemas = []
        for tool_name in self._tool_registry.list():
            tool = self._tool_registry.get(tool_name)
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.get_schema()
                }
            })
        return schemas

    async def tool_call(self, prompt: str, model: Optional[str] = None, **kwargs) -> Dict:
        providers = self._routing_config.get(model, list(self._providers.keys()))
        for provider_name in providers:
            try:
                provider = self._providers[provider_name]
                tools = await self.get_tool_schemas()
                return await provider.tool_call(prompt, tools, **kwargs)
            except Exception as e:
                logger.warning(f"Provider {provider_name} tool_call failed: {e}")
                continue
        raise RuntimeError("All LLM providers failed for tool call")
