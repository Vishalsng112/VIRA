"""Shipped agents.

VIRA ships one chat agent: :class:`ChatAgent`. Add your own agents by extending
:class:`vira.agent.base.BaseAgent` (or :class:`vira.agent.llm_agent.LLMAgent`)
and registering them in ``config.yaml``.
"""
from .chat_agent import ChatAgent

__all__ = ["ChatAgent"]
