# vira/llm/factory.py
import os
# from vira.llm.providers.openai import OpenAIProvider
# from vira.llm.providers.anthropic import AnthropicProvider
# from vira.llm.providers.ollama import OllamaProvider

from vira.llm.ollama import OllamaProvider
from vira.llm.openai import OpenAIProvider
from vira.llm.anthropic import AnthropicProvider

def create_provider(provider_config: dict):
    provider_type = provider_config.get("provider")
    if provider_type == "openai":
        return OpenAIProvider(
            api_key=os.environ.get(provider_config.get("api_key", "").strip("${}"), ""),
            model=provider_config["model"],
            base_url=provider_config.get("base_url"),
            **{k: v for k, v in provider_config.items() if k not in ["provider", "api_key", "model", "base_url"]}
        )
    elif provider_type == "anthropic":
        return AnthropicProvider(
            api_key=os.environ.get(provider_config.get("api_key", "").strip("${}"), ""),
            model=provider_config["model"],
            **{k: v for k, v in provider_config.items() if k not in ["provider", "api_key", "model"]}
        )
    elif provider_type == "ollama":
        return OllamaProvider(
            model=provider_config["model"],
            base_url=provider_config.get("base_url", "http://localhost:11434"),
            **{k: v for k, v in provider_config.items() if k not in ["provider", "model", "base_url"]}
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")