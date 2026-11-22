"""Tests for the domain tool packs and their MCP entrypoints."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from vira.tooling import ServerManifest, ToolContext, ToolRegistry, build_server
from vira.tooling.servers.runtime import TOOLS as RUNTIME_TOOLS
from vira.tooling.servers.workspace import TOOLS as WORKSPACE_TOOLS
from vira.mcp.connection import MCPServerConnection

ROOT = Path(__file__).resolve().parents[2]


class WorkspaceToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _ctx(self):
        return ToolContext(user_id=1, workspace_root=str(self.root))

    async def test_write_read_list_and_search(self):
        write = WORKSPACE_TOOLS[1]()
        result = await write.invoke({"path": "src/a.txt", "content": "hello world"}, self._ctx())
        self.assertTrue(result.ok)
        read = await WORKSPACE_TOOLS[0]().invoke({"path": "src/a.txt"}, self._ctx())
        self.assertEqual(read.data.content, "hello world")
        listing = await WORKSPACE_TOOLS[2]().invoke({"path": "src"}, self._ctx())
        self.assertEqual(listing.data.entries[0].path, "src/a.txt")
        search = await WORKSPACE_TOOLS[3]().invoke({"pattern": "world"}, self._ctx())
        self.assertEqual(search.data.matches[0].line, 1)

    async def test_path_escape_is_rejected(self):
        result = await WORKSPACE_TOOLS[0]().invoke({"path": "../outside"}, self._ctx())
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "path_escape")


class RuntimeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_shell_chaining(self):
        result = await RUNTIME_TOOLS[0]().invoke({"command": "pwd; whoami"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "unsafe_command")

    async def test_runs_safe_read_only_command(self):
        result = await RUNTIME_TOOLS[0]().invoke({"command": ["whoami"]})
        self.assertTrue(result.ok)
        self.assertEqual(result.data.exit_code, 0)


class McpServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_server_lists_domain_tools(self):
        server, registry = build_server(
            ServerManifest(id="workspace", title="Workspace", description="Files", category="workspace"),
            WORKSPACE_TOOLS,
        )
        self.assertEqual(
            registry.list(),
            [
                "workspace.list_directory",
                "workspace.make_directory",
                "workspace.read_file",
                "workspace.search_files",
                "workspace.write_file",
            ],
        )

    async def test_real_stdio_workspace_server_lists_and_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "VIRA_WORKSPACE_ROOT": tmp,
                "VIRA_CALLER_USER_ID": "1",
            }
            connection = MCPServerConnection.stdio(
                "workspace",
                sys.executable,
                ["-m", "vira.mcp.servers.workspace.server"],
                env=env,
            )
            async with connection:
                tools = await connection.session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertIn("write_file", names)
                self.assertIn("read_file", names)
                call = await connection.session.call_tool(
                    "write_file", {"path": "hello.txt", "content": "hello"}
                )
                envelope = json.loads(call.content[0].text)
                self.assertTrue(envelope["ok"])
                self.assertEqual(envelope["data"]["path"], "hello.txt")
