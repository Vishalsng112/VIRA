# vira/tools/mcp_tool.py
from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult, Tool

from vira.tools.base import BaseTool, ToolPermission, text_result


class MCPTool(BaseTool):
    """Wraps one tool exposed by a connected MCP server as a local BaseTool."""
    def __init__(
        self,
        mcp_tool: Tool,
        session: ClientSession,
        permissions: ToolPermission,
        server_name: str = "",
    ):
        super().__init__(
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            permissions=permissions,
            input_schema=mcp_tool.inputSchema,
            output_schema=mcp_tool.outputSchema,
        )
        self._session = session
        self.server_name = server_name

    async def execute(self, **kwargs: Any) -> CallToolResult:
        try:
            return await self._session.call_tool(self.name, arguments=kwargs)
        except Exception as exc:  # surface failures as a normal tool error,
            # consistent with how MCP servers themselves report tool errors
            return text_result(f"MCP tool '{self.name}' failed: {exc}", is_error=True)
