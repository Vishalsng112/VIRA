# vira/tools/executor.py
import inspect
# import logging
from loguru import logger
from typing import List

from mcp.types import CallToolResult

from vira.tools.base import text_result
from vira.tools.registry import ToolRegistry

# logger = logging.getLogger(__name__)

class ToolExecutor:
    def __init__(self, registry: ToolRegistry, security_manager):
        self._registry = registry
        self._security = security_manager

    async def execute(self, tool_name: str, required_action: str = "execute", **kwargs) -> CallToolResult:
        # Debug: log current registry state
        logger.debug(
            f"ToolExecutor.execute: looking for '{tool_name}', "
            f"registry keys: {list(self._registry._tools.keys())}, "
            f"unqualified index: {self._registry._unqualified_index}"
        )

        # First try the normal lookup (unqualified or qualified)
        tool = self._registry.get(tool_name)

        # If not found, fallback: search by base name directly
        if tool is None:
            candidates = []
            for key, t in self._registry._tools.items():
                if t.name == tool_name:   # t.name is the base name (e.g., "web_browse")
                    candidates.append((key, t))
            if len(candidates) == 1:
                tool = candidates[0][1]
                logger.debug(f"Resolved '{tool_name}' to qualified name '{candidates[0][0]}'")
            elif len(candidates) > 1:
                return text_result(
                    f"Ambiguous tool name '{tool_name}': found {len(candidates)} candidates: "
                    f"{[c[0] for c in candidates]}. Please use the fully qualified name.",
                    is_error=True
                )

        if not tool:
            all_tools = list(self._registry._tools.keys())
            return text_result(
                f"Tool '{tool_name}' not found. Available tools: {all_tools}",
                is_error=True,
            )

        # Permission check
        if required_action not in tool.permissions.actions:
            return text_result(
                f"Permission denied: '{tool_name}' does not allow '{required_action}'",
                is_error=True,
            )

        # Authorize with flexible signature handling (supports sync/async)
        if self._security:
            sig = inspect.signature(self._security.authorize)
            # Try binding arguments flexibly
            try:
                bound = sig.bind(tool_name=tool_name, action=required_action, kwargs=kwargs)
            except TypeError:
                try:
                    bound = sig.bind(tool_name, required_action, kwargs)
                except TypeError:
                    try:
                        bound = sig.bind(tool_name, required_action)
                    except TypeError:
                        raise TypeError(
                            f"SecurityManager.authorize signature {sig} does not accept "
                            f"(tool_name, action, kwargs) or (tool_name, action). "
                            "Please update your SecurityManager to support one of these signatures."
                        )
            # Call sync or async accordingly
            if inspect.iscoroutinefunction(self._security.authorize):
                authorized = await self._security.authorize(*bound.args, **bound.kwargs)
            else:
                authorized = self._security.authorize(*bound.args, **bound.kwargs)

            if not authorized:
                return text_result(
                    f"Permission denied by security manager for '{tool_name}'",
                    is_error=True
                )

        # Execute the tool
        return await tool.execute(**kwargs)

    def list_tools(self) -> List[str]:
        """Return names of all registered tools."""
        return self._registry.list()