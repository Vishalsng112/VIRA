"""Low-level MCP server adapter for domain tool packs."""
from __future__ import annotations

import asyncio
from typing import Iterable, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent

from .contract import BaseTool, ToolContext
from .manifest import ServerManifest
from .registry import ToolRegistry


def build_server(
    manifest: ServerManifest,
    tools: Iterable[type[BaseTool]],
    context: Optional[ToolContext] = None,
) -> tuple[Server, ToolRegistry]:
    registry = ToolRegistry(tools)
    server = Server(manifest.id, version=manifest.version, instructions=manifest.instructions)
    ctx = context or ToolContext.from_env()

    @server.list_tools()
    async def list_tools():
        return [tool.as_mcp_tool() for tool in registry.tools()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        envelope = await registry.invoke(name, arguments or {}, ctx)
        return CallToolResult(
            content=[TextContent(type="text", text=envelope.model_dump_json())],
            structuredContent=envelope.model_dump(mode="json"),
            isError=not envelope.ok,
        )

    return server, registry


async def serve_stdio(
    manifest: ServerManifest,
    tools: Iterable[type[BaseTool]],
    context: Optional[ToolContext] = None,
) -> None:
    server, _ = build_server(manifest, tools, context)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run_stdio(
    manifest: ServerManifest,
    tools: Iterable[type[BaseTool]],
    context: Optional[ToolContext] = None,
) -> None:
    asyncio.run(serve_stdio(manifest, tools, context))
