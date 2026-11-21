"""First-run model guidance shared by the API, docs and installers.

The tiers are deliberately conservative: a model that cannot hold the tool
catalogue and a few observations in context will look broken even when the
server is healthy. Tool use below roughly 4B parameters or 4 GB of RAM is
possible, but it is not the default first impression VIRA promises.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

TOOL_USE_WARNING = (
    "Tool use may be unreliable below about 4 GB RAM or a 4B-parameter model. "
    "If the agent repeats calls, ignores tools or returns malformed JSON, move "
    "to a larger local model or use a cloud fallback."
)

TIERS = [
    {
        "id": "minimal",
        "min_ram_gb": 0,
        "model": "llama3.2:3b",
        "label": "3B · minimal",
        "tool_reliability": "experimental",
        "note": "Chat works, but multi-step tool use is unreliable. Use for quick tests only.",
    },
    {
        "id": "recommended",
        "min_ram_gb": 8,
        "model": "qwen3.5:9b",
        "label": "9B · recommended default",
        "tool_reliability": "good",
        "note": "The default VIRA model. Reliable at VIRA's JSON tool protocol on an 8–16 GB machine.",
    },
    {
        "id": "comfortable",
        "min_ram_gb": 16,
        "model": "qwen2.5:14b",
        "label": "14B · comfortable",
        "tool_reliability": "better",
        "note": "Better instruction following and tool selection if you have the memory.",
    },
    {
        "id": "large",
        "min_ram_gb": 32,
        "model": "qwen2.5:32b",
        "label": "32B · large",
        "tool_reliability": "best local",
        "note": "Best local quality; needs a GPU or a large-memory CPU host to be usable.",
    },
]


def recommend(ram_gb: Optional[float], has_gpu: bool = False) -> Dict[str, Any]:
    """Return the suggested tier for a machine profile."""
    ram = float(ram_gb or 0)
    selected = TIERS[0]
    for tier in TIERS:
        if ram >= tier["min_ram_gb"]:
            selected = tier
    if has_gpu and ram >= 8 and selected["id"] == "minimal":
        selected = TIERS[1]
    return {
        **selected,
        "ram_gb": ram_gb,
        "has_gpu": has_gpu,
        "warning": TOOL_USE_WARNING if (ram and ram < 8) or selected["id"] == "minimal" else None,
    }


def hardware_ram_gb() -> Optional[float]:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return None


def cloud_fallback() -> Dict[str, str]:
    """Short, provider-neutral description of the cloud escape hatch."""
    return {
        "openai": "Set OPENAI_API_KEY and add an llm.models entry with provider: openai and api_key: ${OPENAI_API_KEY}, then reload.",
        "anthropic": "Set ANTHROPIC_API_KEY and add an llm.models entry with provider: anthropic and api_key: ${ANTHROPIC_API_KEY}, then reload.",
        "ollama_remote": "Point VIRA_OLLAMA_URL at a larger Ollama host instead of the local endpoint.",
    }
