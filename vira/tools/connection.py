# vira/tools/connection.py
"""Owns the actual connection lifecycle to an MCP server."""
from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, Dict, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


class MCPServerConnection:
    """A live connection to one MCP server, over stdio or streamable HTTP."""

    def __init__(self, name: str):
        self.name = name
        self.session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connector = None  # set by .stdio()/.http(), called in connect()

    @classmethod
    def stdio(
        cls,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> "MCPServerConnection":
        """Configure a connection to a server launched as a subprocess
        speaking MCP over stdio (the most common case for local tool servers,
        e.g. `npx -y @modelcontextprotocol/server-filesystem /path`)."""
        conn = cls(name)
        params = StdioServerParameters(command=command, args=args or [], env=env)

        async def _connect(stack: AsyncExitStack) -> ClientSession:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            return session

        conn._connector = _connect
        return conn

    @classmethod
    def http(cls, name: str, url: str) -> "MCPServerConnection":
        """Configure a connection to a server exposed over Streamable HTTP
        (the recommended transport for remote/production MCP servers)."""
        conn = cls(name)

        async def _connect(stack: AsyncExitStack) -> ClientSession:
            read, write, _get_session_id = await stack.enter_async_context(
                streamablehttp_client(url)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            return session

        conn._connector = _connect
        return conn
    
    async def connect(self) -> ClientSession:
        if self.session is not None:
            return self.session
        if self._connector is None:
            raise RuntimeError(
                f"MCPServerConnection '{self.name}' was not configured; "
                "use MCPServerConnection.stdio(...) or .http(...)"
            )
        self._exit_stack = AsyncExitStack()
        session = await self._connector(self._exit_stack)
        await session.initialize()
        self.session = session
        return session

    async def close(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self.session = None

    async def __aenter__(self) -> "MCPServerConnection":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()
