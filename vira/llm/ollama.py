# vira/llm/providers/ollama.py
import aiohttp
from typing import Dict, List, AsyncIterator
import json
from vira.llm.base import BaseLLMProvider, LLMResponse

class OllamaProvider(BaseLLMProvider):
    def __init__(self, model: str, base_url: str = "http://localhost:11434", **kwargs):
        self.model = model
        self.base_url = base_url
        self.default_params = kwargs

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        params = {**self.default_params, **kwargs}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            **params
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/api/generate", json=payload) as resp:
                data = await resp.json()
                return LLMResponse(
                    text=data["response"],
                    model=self.model,
                    usage={"prompt_tokens": data.get("prompt_eval_count", 0),
                           "completion_tokens": data.get("eval_count", 0),
                           "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)},
                    finish_reason="stop",
                    raw=data
                )

    async def stream(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        params = {**self.default_params, **kwargs}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            **params
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/api/generate", json=payload) as resp:
                async for line in resp.content:
                    if line:
                        data = json.loads(line.decode())
                        yield data.get("response", "")

    async def generate_structured(self, prompt: str, schema: Dict, **kwargs) -> Dict:
        # Ollama can use format parameter
        params = {**self.default_params, **kwargs}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": schema,
            "stream": False,
            **params
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/api/generate", json=payload) as resp:
                data = await resp.json()
                return json.loads(data["response"])

    async def tool_call(self, prompt: str, tools: List[Dict], **kwargs) -> Dict:
        # Ollama does not have native tool calling; we can instruct it to output JSON.
        # For simplicity, we generate structured output with a schema for tool call.
        tool_schema = {
            "type": "object",
            "properties": {
                "tool": {"type": "string"},
                "arguments": {"type": "object"}
            }
        }
        # Inject tool list into prompt
        tool_desc = "\n".join([f"- {t['function']['name']}: {t['function']['description']}" for t in tools])
        prompt_with_tools = f"{prompt}\n\nAvailable tools:\n{tool_desc}\n\nChoose a tool and respond with JSON: {{'tool': 'name', 'arguments': {{...}}}}"
        result = await self.generate_structured(prompt_with_tools, tool_schema, **kwargs)
        return {"name": result["tool"], "arguments": result.get("arguments", {})}

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False