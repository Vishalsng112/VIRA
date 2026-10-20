# vira/tools/base.py
"""Base tool interface, aligned with the real MCP Python SDK (mcp>=1.28)."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel


class ToolPermission(BaseModel):
    """Local authorization policy for a tool. This is framework-level concept;
    MCP itself has no notion of permissions, so it is not part of mcp.types."""

    actions: List[str]  # e.g., ["read", "write", "execute"]


class BaseTool(ABC):
    """Base interface for tools, local or MCP-backed."""
    def __init__(
        self,
        name: str,
        description: str,
        permissions: ToolPermission,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.permissions = permissions
        self.input_schema = input_schema or {"type": "object", "properties": {}}
        self.output_schema = output_schema

    @abstractmethod
    async def execute(self, **kwargs) -> CallToolResult:
        """Execute the tool and return a standard MCP CallToolResult."""
        raise NotImplementedError

    def as_mcp_tool(self) -> Tool:
        """Describe this tool using MCP's own wire schema (`mcp.types.Tool`).

        This lets the rest of the framework (and any MCP client we expose
        ourselves through) treat local and MCP-sourced tools uniformly.
        """
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
            outputSchema=self.output_schema,
        )

    def get_schema(self) -> Dict[str, Any]:
        """Return JSON schema for tool input (kept for backwards compatibility
        with callers expecting a plain dict; prefer as_mcp_tool() for new code)."""
        return self.input_schema


def text_result(text: str, is_error: bool = False) -> CallToolResult:
    """Convenience helper: wrap plain text in a standard CallToolResult."""
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=is_error)
