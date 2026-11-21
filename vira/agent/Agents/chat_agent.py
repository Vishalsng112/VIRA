"""Chat agent connected to the VIRA chat webpage.

Small on purpose: prompts, capability and routing defaults live here; the
conversation mechanics come from :class:`ConversationalAgent`.
"""
from __future__ import annotations

from vira.agent.conversational_agent import ConversationalAgent


class ChatAgent(ConversationalAgent):
    default_name = "ChatAgent"
    default_description = "Conversational AI agent with tool support"
    default_system_prompt = (
        "You are VIRA, a helpful assistant running on the user's own machine. "
        "Be concise and accurate."
    )
    capability_name = "chat"
    capability_description = (
        "Respond to user messages, using local/MCP tools and sub-agents over "
        "several steps."
    )
    #: Requests without an explicit agent target go to this agent.
    is_default_agent = True
    role = "chat"
