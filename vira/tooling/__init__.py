"""Pydantic-first domain tool framework."""
from .catalog import CatalogEntry, ToolCatalog
from .contract import (
    BaseTool,
    EchoInput,
    EchoOutput,
    EchoTool,
    StrictModel,
    ToolContext,
    ToolEnvelope,
    ToolError,
    ToolExample,
    ToolFailure,
    ToolMetadata,
    ToolPermission,
    ToolSideEffects,
    text_result,
)
from .manifest import ServerManifest
from .mcp import build_server, run_stdio, serve_stdio
from .policy import ToolPolicy
from .registry import ToolRegistry
from .toolbox import (
    Toolbox,
    ToolDescribeTool,
    ToolSearchTool,
)

__all__ = [
    "BaseTool",
    "CatalogEntry",
    "EchoInput",
    "EchoOutput",
    "EchoTool",
    "ServerManifest",
    "StrictModel",
    "Toolbox",
    "ToolCatalog",
    "ToolContext",
    "ToolDescribeTool",
    "ToolEnvelope",
    "ToolError",
    "ToolExample",
    "ToolFailure",
    "ToolMetadata",
    "ToolPermission",
    "ToolPolicy",
    "ToolRegistry",
    "ToolSearchTool",
    "ToolSideEffects",
    "text_result",
    "build_server",
    "run_stdio",
    "serve_stdio",
]
