"""Adapter for a tool exposed by an external MCP server."""
from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult, Tool

from .contract import ToolPermission, text_result


class MCPToolAdapter:
    """Duck-typed tool backed by a remote MCP server.

    Dynamic MCP schemas cannot be represented as static Pydantic models, so this
    adapter intentionally implements the registry/executor protocol directly.
    """

    def __init__(
        self,
        tool: Tool,
        session: ClientSession,
        permissions: ToolPermission,
        server_name: str,
    ) -> None:
        self.name = tool.name
        self.description = tool.description or ""
        self.permissions = permissions
        self.server_name = server_name
        self.input_schema = tool.inputSchema
        self.output_schema = tool.outputSchema
        self.session = session

    def get_schema(self) -> dict[str, Any]:
        return self.input_schema

    async def execute(self, **kwargs: Any) -> CallToolResult:
        try:
            return await self.session.call_tool(self.name, arguments=kwargs)
        except Exception as exc:  # noqa: BLE001 - MCP boundary
            return text_result(f"MCP tool '{self.name}' failed: {exc}", is_error=True)
