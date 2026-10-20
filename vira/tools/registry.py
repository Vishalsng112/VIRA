# vira/tools/registry.py
from typing import Dict, List, Optional

from vira.tools.base import BaseTool, ToolPermission
from vira.tools.connection import MCPServerConnection
from vira.tools.mcp_tool import MCPTool


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}          # qualified name -> tool
        self._unqualified_index: Dict[str, List[str]] = {}  # bare name -> [qualified names]
        self._connections: Dict[str, MCPServerConnection] = {}

    def register(self, tool: BaseTool, qualified_name: Optional[str] = None) -> None:
        key = qualified_name or tool.name
        self._tools[key] = tool
        self._unqualified_index.setdefault(tool.name, []).append(key)

    def get(self, name: str) -> Optional[BaseTool]:
        if name in self._tools:
            return self._tools[name]
        # fall back to unqualified lookup only if unambiguous
        candidates = self._unqualified_index.get(name, [])
        if len(candidates) == 1:
            return self._tools[candidates[0]]
        return None

    def list(self) -> List[str]:
        return list(self._tools.keys())

    async def register_mcp_server(
        self,
        connection: MCPServerConnection,
        default_permissions: Optional[ToolPermission] = None,
    ) -> List[str]:
        """Connect to an MCP server (if not already connected), fetch its
        tools via the real `list_tools()` call, and register each as an
        MCPTool adapter. Returns the list of qualified names registered."""
        if default_permissions is None:
            default_permissions = ToolPermission(actions=["read", "execute"])

        session = await connection.connect()
        self._connections[connection.name] = connection

        result = await session.list_tools()  # ListToolsResult
        registered: List[str] = []
        for tool in result.tools:  # tool: mcp.types.Tool
            mcp_tool = MCPTool(
                mcp_tool=tool,
                session=session,
                permissions=default_permissions,
                server_name=connection.name,
            )
            qualified_name = f"{connection.name}.{tool.name}"
            self.register(mcp_tool, qualified_name=qualified_name)
            registered.append(qualified_name)
        return registered

    async def close_all(self) -> None:
        """Close every MCP server connection this registry opened."""
        for connection in self._connections.values():
            await connection.close()
        self._connections.clear()
