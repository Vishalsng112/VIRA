# vira/llm/providers/openai.py
import os
from typing import Dict, List, AsyncIterator
from openai import AsyncOpenAI
from vira.llm.base import BaseLLMProvider, LLMResponse

class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str = None, **kwargs):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.default_params = kwargs

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        params = {**self.default_params, **kwargs}
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            **params
        )
        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content,
            model=response.model,
            usage=response.usage.model_dump(),
            finish_reason=choice.finish_reason,
            raw=response
        )

    async def stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        params = {**self.default_params, **kwargs}
        async for chunk in await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            **params
        ):
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def generate_structured(self, prompt: str, schema: Dict, **kwargs) -> Dict:
        # Use function calling or JSON mode if available
        params = {**self.default_params, **kwargs}
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            **params
        )
        return response.choices[0].message.content  # parse as dict

    async def tool_call(self, prompt: str, tools: List[Dict], **kwargs) -> Dict:
        params = {**self.default_params, **kwargs}
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            tool_choice="auto",
            **params
        )
        choice = response.choices[0]
        if choice.message.tool_calls:
            return choice.message.tool_calls[0].function
        return {}

    async def health_check(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False