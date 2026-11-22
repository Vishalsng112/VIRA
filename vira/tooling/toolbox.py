"""Registry, toolbox and meta-tools for the domain tool framework."""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from .catalog import CatalogEntry, ToolCatalog
from .contract import (
    BaseTool,
    StrictModel,
    ToolContext,
    ToolEnvelope,
)
from .policy import ToolPolicy
from .registry import ToolRegistry


class ToolSearchInput(StrictModel):
    query: str
    limit: int = Field(default=8, ge=1, le=30)
    category: str = ""


class ToolSearchOutput(StrictModel):
    entries: list[CatalogEntry]
    query: str


class ToolSearchTool(BaseTool):
    namespace = "tooling"
    name = "tool_search"
    title = "Search tools"
    description = "Find the most relevant tools for the current task."
    when_to_use = (
        "Use when the needed tool is not in the current shortlist, or when the "
        "task spans an app, domain or workflow you have not used yet."
    )
    when_not_to_use = "Do not use when the needed tool is already visible."
    category = "discovery"
    tags = ("search", "discover", "tools", "capabilities")
    timeout_seconds = 5
    input_model = ToolSearchInput
    output_model = ToolSearchOutput

    def __init__(self, catalog: ToolCatalog, policy: Optional[ToolPolicy] = None) -> None:
        self._catalog = catalog
        self._policy = policy or ToolPolicy()

    async def run(self, params: ToolSearchInput, context: ToolContext) -> ToolSearchOutput:
        allowed = self._policy.visible(self._catalog.names())
        entries = self._catalog.search(
            params.query,
            limit=params.limit,
            category=params.category or None,
            allowed=allowed,
        )
        return ToolSearchOutput(entries=entries, query=params.query)


class ToolDescribeInput(StrictModel):
    name: str


class ToolDescribeOutput(StrictModel):
    entry: Optional[CatalogEntry] = None


class ToolDescribeTool(BaseTool):
    namespace = "tooling"
    name = "tool_describe"
    title = "Describe tool"
    description = "Return the full input/output schema and usage guidance for one tool."
    when_to_use = "Use after tool_search when you need the exact schema for a tool."
    when_not_to_use = "Do not use to execute the tool."
    category = "discovery"
    tags = ("schema", "describe", "tools")
    timeout_seconds = 5
    input_model = ToolDescribeInput
    output_model = ToolDescribeOutput

    def __init__(self, catalog: ToolCatalog, policy: Optional[ToolPolicy] = None) -> None:
        self._catalog = catalog
        self._policy = policy or ToolPolicy()

    async def run(self, params: ToolDescribeInput, context: ToolContext) -> ToolDescribeOutput:
        entry = self._catalog.get(params.name)
        if entry is None or not self._policy.allows(entry.qualified_name):
            return ToolDescribeOutput(entry=None)
        return ToolDescribeOutput(entry=entry)


class Toolbox:
    """Per-agent view over a registry with policy and retrieval."""

    def __init__(self, registry: ToolRegistry, policy: Optional[ToolPolicy] = None) -> None:
        self.registry = registry
        self.policy = policy or ToolPolicy()

    def names(self) -> list[str]:
        return self.policy.visible(self.registry.list())

    def search(self, query: str, limit: int = 8, category: str = "") -> list[CatalogEntry]:
        return self.registry.catalog.search(
            query, limit=limit, category=category or None, allowed=self.names()
        )

    def select(self, query: str, limit: int = 8) -> list[dict]:
        pinned = [name for name in self.names() if self.policy.is_pinned(name)]
        return self.registry.catalog.select(
            query, limit=limit, required=pinned, allowed=self.names()
        )

    def describe(self, name: str) -> Optional[CatalogEntry]:
        if not self.policy.allows(name):
            return None
        return self.registry.catalog.get(name)

    def meta_tools(self) -> list[type[BaseTool]]:
        return [
            _bound_search(self.registry.catalog, self.policy),
            _bound_describe(self.registry.catalog, self.policy),
        ]

    async def invoke(
        self,
        name: str,
        arguments: dict,
        context: Optional[ToolContext] = None,
    ) -> ToolEnvelope:
        if not self.policy.allows(name):
            return ToolEnvelope(
                ok=False,
                error={"code": "forbidden", "message": f"Tool '{name}' is not allowed."},
            )
        return await self.registry.invoke(name, arguments, context)


def _bound_search(catalog: ToolCatalog, policy: ToolPolicy) -> type[BaseTool]:
    class _Search(ToolSearchTool):
        def __init__(self) -> None:
            super().__init__(catalog, policy)

    return _Search


def _bound_describe(catalog: ToolCatalog, policy: ToolPolicy) -> type[BaseTool]:
    class _Describe(ToolDescribeTool):
        def __init__(self) -> None:
            super().__init__(catalog, policy)

    return _Describe
