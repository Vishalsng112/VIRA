"""Reusable tool policy and discovery for agents.

Every agent gets the same behaviour: discover registered local and MCP tools,
apply an allow/deny/pinned policy, build one catalog, select a small relevant
set, and execute with the right permission action.  Before this module each
agent reimplemented that logic, which is how read-only tools ended up being
called with the wrong action and MCP tools were only half connected.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from vira.tooling.catalog import ToolCatalog
from vira.tooling.policy import ToolPolicy


class Toolbox:
    """Live view of the tools an agent may use."""

    def __init__(self, runtime, policy: Optional[ToolPolicy] = None):
        self.runtime = runtime
        self.policy = policy or ToolPolicy()
        self._specs: List[Dict[str, Any]] = []
        self._catalog = ToolCatalog([])
        self._version = -1
        self._names: List[str] = []
        self.refresh(force=True)

    # ------------------------------------------------------------------ state
    def _executor(self):
        return getattr(self.runtime, "tool_executor", None)

    def _registry(self):
        return getattr(self._executor(), "_registry", None)

    def registry_version(self) -> int:
        try:
            return int(getattr(self._registry(), "version", 0))
        except Exception:
            return 0

    def refresh(self, force: bool = False) -> bool:
        """Reload tool specs when the registry changed. Returns True if reloaded."""
        version = self.registry_version()
        if not force and version == self._version and self._specs:
            return False
        executor = self._executor()
        registry = self._registry()
        names: List[str] = []
        if executor is not None:
            try:
                names = list(executor.list_tools())
            except Exception:
                names = []
        specs: List[Dict[str, Any]] = []
        for name in names:
            if not self.policy.allows(name):
                continue
            tool = registry.get(name) if registry is not None else None
            specs.append({
                "name": name,
                "description": getattr(tool, "description", "No description"),
                "parameters": (tool.get_schema()
                               if tool is not None and hasattr(tool, "get_schema")
                               else {}),
                "provider": getattr(tool, "server_name", None) or "local",
                "category": _category(name, tool),
            })
        self._names = [spec["name"] for spec in specs]
        self._specs = specs
        self._catalog = ToolCatalog(specs)
        self._version = version
        return True

    # --------------------------------------------------------------- accessors
    @property
    def specs(self) -> List[Dict[str, Any]]:
        self.refresh()
        return list(self._specs)

    @property
    def names(self) -> List[str]:
        self.refresh()
        return list(self._names)

    @property
    def catalog(self) -> ToolCatalog:
        self.refresh()
        return self._catalog

    @property
    def pinned(self) -> List[str]:
        return [name for name in self.names if self.policy.is_pinned(name)]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        self.refresh()
        return next((spec for spec in self._specs if spec["name"] == name), None)

    def select(self, query: str, limit: int = 8,
               required: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        available = set(self.names)
        needed = [name for name in (required or []) if name in available]
        needed += [name for name in self.pinned if name not in needed]
        return self.catalog.select(
            query, limit=limit, required=needed, allowed=self.names
        )

    def search(self, query: str, limit: int = 8):
        return self.catalog.search(query, limit=limit)

    def describe(self) -> Dict[str, Any]:
        return {
            "names": self.names,
            "pinned": self.pinned,
            "allow": list(self.policy.allow) if self.policy.allow else None,
            "deny": list(self.policy.deny),
            "count": len(self._specs),
        }

    # -------------------------------------------------------------- execution
    async def call(self, agent_id: str, name: str, **params) -> Any:
        """Execute a tool through the runtime with the correct action."""
        if not self.policy.allows(name):
            raise PermissionError(f"tool '{name}' is not allowed for this agent")
        params.pop("tool_name", None)
        params.pop("required_action", None)
        return await self.runtime.use_tool(
            agent_id, name, required_action=self._preferred_action(name), **params)

    def _preferred_action(self, name: str) -> Optional[str]:
        resolver = getattr(self.runtime, "tool_actions", None)
        actions = resolver(name) if callable(resolver) else None
        if actions is None:
            registry = self._registry()
            tool = registry.get(name) if registry is not None else None
            actions = getattr(getattr(tool, "permissions", None), "actions", []) or []
        return _preferred_action(actions)


def _preferred_action(actions: Any) -> Optional[str]:
    actions = list(actions or [])
    for candidate in ("execute", "write", "read"):
        if candidate in actions:
            return candidate
    return actions[0] if actions else None


def _category(name: str, tool) -> str:
    if "." in name:
        return "mcp"
    return "local"
