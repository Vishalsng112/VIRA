"""Unified registry for local domain tools and external MCP tools."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .catalog import ToolCatalog
from .contract import BaseTool, ToolEnvelope, ToolPermission
from .mcp_tool import MCPToolAdapter


class ToolRegistry:
    def __init__(self, tools=None) -> None:
        self._tools: Dict[str, Any] = {}
        self._unqualified: Dict[str, List[str]] = {}
        self._connections: Dict[str, Any] = {}
        self.version = 0
        for tool in tools or ():
            self.register(tool)

    @staticmethod
    def _qualified_name(tool: Any) -> str:
        if isinstance(tool, BaseTool):
            return type(tool).qualified_name()
        return str(getattr(tool, "name", ""))

    @staticmethod
    def _instantiate(tool: Any) -> Any:
        if isinstance(tool, type):
            return tool()
        return tool

    def register(self, tool: Any, qualified_name: Optional[str] = None) -> None:
        instance = self._instantiate(tool)
        key = qualified_name or self._qualified_name(instance)
        if not key:
            raise ValueError("tool must expose a name or be registered with qualified_name")
        previous = self._tools.get(key)
        if previous is not None:
            names = self._unqualified.get(getattr(previous, "name", ""), [])
            if key in names:
                names.remove(key)
        self._tools[key] = instance
        local = getattr(instance, "name", key.split(".")[-1])
        self._unqualified.setdefault(local, [])
        if key not in self._unqualified[local]:
            self._unqualified[local].append(key)
        self.version += 1

    def unregister(self, name: str) -> bool:
        tool = self._tools.pop(name, None)
        if tool is None:
            return False
        local = getattr(tool, "name", name.split(".")[-1])
        names = self._unqualified.get(local, [])
        if name in names:
            names.remove(name)
        if not names:
            self._unqualified.pop(local, None)
        self.version += 1
        return True

    def remove_by_plugin(self, plugin_id: str) -> int:
        names = [k for k, v in self._tools.items() if getattr(v, "plugin_id", None) == plugin_id]
        for name in names:
            self.unregister(name)
        return len(names)

    def remove_by_provider(self, provider: str) -> int:
        names = [k for k, v in self._tools.items() if getattr(v, "server_name", None) == provider]
        for name in names:
            self.unregister(name)
        self._connections.pop(provider, None)
        return len(names)

    def get(self, name: str) -> Optional[Any]:
        if name in self._tools:
            return self._tools[name]
        candidates = self._unqualified.get(name, [])
        return self._tools[candidates[0]] if len(candidates) == 1 else None

    def list(self) -> List[str]:
        return sorted(self._tools)

    def tools(self) -> List[Any]:
        return list(self._tools.values())

    def metadata(self) -> List[Dict[str, Any]]:
        catalog = ToolCatalog()
        for name, tool in self._tools.items():
            catalog.add(tool, qualified_name=name)
        return [entry.as_dict() for entry in catalog.all()]

    @property
    def catalog(self) -> ToolCatalog:
        catalog = ToolCatalog()
        for name, tool in self._tools.items():
            catalog.add(tool, qualified_name=name)
        return catalog

    async def invoke(self, name: str, arguments: dict | None,
                     context=None) -> ToolEnvelope:
        tool = self.get(name)
        if tool is None:
            return ToolEnvelope(
                ok=False,
                error={"code": "not_found", "message": f"Unknown tool '{name}'."},
            )
        if isinstance(tool, BaseTool):
            return await tool.invoke(arguments, context)
        return ToolEnvelope(
            ok=False,
            error={"code": "not_invocable", "message": f"Tool '{name}' is not a domain tool."},
        )

    def register_builtins(self, root: str = ".") -> List[str]:
        """Register VIRA's domain tool packs."""
        from .servers import all_tools
        names = []
        for tool in all_tools():
            self.register(tool)
            names.append(tool.qualified_name())
        return names

    async def register_mcp_server(
        self,
        connection,
        default_permissions: Optional[ToolPermission] = None,
        allowed_tools: Optional[List[str]] = None,
        denied_tools: Optional[List[str]] = None,
    ) -> List[str]:
        if default_permissions is None:
            default_permissions = ToolPermission(actions=["read", "execute"])
        session = await connection.connect()
        self._connections[connection.name] = connection
        result = await session.list_tools()
        registered: List[str] = []
        allowed = set(allowed_tools or [])
        denied = set(denied_tools or [])
        for tool in result.tools:
            if allowed and tool.name not in allowed:
                continue
            if tool.name in denied:
                continue
            adapter = MCPToolAdapter(
                tool=tool,
                session=session,
                permissions=default_permissions,
                server_name=connection.name,
            )
            qualified = f"{connection.name}.{tool.name}"
            self.register(adapter, qualified_name=qualified)
            registered.append(qualified)
        return registered

    async def close_all(self) -> None:
        for connection in self._connections.values():
            await connection.close()
        self._connections.clear()
