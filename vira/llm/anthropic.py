# vira/llm/providers/anthropic.py
import os
from typing import Dict, List, AsyncIterator
from anthropic import AsyncAnthropic
from vira.llm.base import BaseLLMProvider, LLMResponse

class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str, **kwargs):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.default_params = kwargs

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        params = {**self.default_params, **kwargs}
        response = await self.client.messages.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            **params
        )
        return LLMResponse(
            text=response.content[0].text,
            model=response.model,
            usage={"prompt_tokens": response.usage.input_tokens,
                   "completion_tokens": response.usage.output_tokens,
                   "total_tokens": response.usage.input_tokens + response.usage.output_tokens},
            finish_reason=response.stop_reason,
            raw=response
        )

    async def stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        params = {**self.default_params, **kwargs}
        async with self.client.messages.stream(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            **params
        ) as stream:
            async for chunk in stream:
                if chunk.type == "content_block_delta":
                    yield chunk.delta.text

    async def generate_structured(self, prompt: str, schema: Dict, **kwargs) -> Dict:
        # Anthropic does not have native JSON mode; we can prompt for JSON.
        # For simplicity, call generate and parse.
        resp = await self.generate(prompt + "\n\nRespond only with valid JSON.", **kwargs)
        return resp.text

    async def tool_call(self, prompt: str, tools: List[Dict], **kwargs) -> Dict:
        # Anthropic's tool use is similar; we pass tools in the request.
        params = {**self.default_params, **kwargs}
        response = await self.client.messages.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice={"type": "auto"},
            **params
        )
        # Extract tool call from content
        for block in response.content:
            if block.type == "tool_use":
                return {"name": block.name, "arguments": block.input}
        return {}

    async def health_check(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False