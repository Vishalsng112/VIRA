"""Complete plugin and MCP examples must load, register and actually work."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from vira.agent.definitions import load_definitions
from vira.agent_orchestration.registry import AgentRegistry
from vira.auth import database
from vira.kernel.plugin_manager import PluginManager
from vira.mcp.connection import MCPServerConnection
from vira.tooling.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]


class _EventBus:
    def __init__(self):
        self.handlers = {}

    def subscribe(self, event_type, handler):
        self.handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type, handler):
        handlers = self.handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)


class _Orchestrator:
    def __init__(self):
        self.tool_registry = ToolRegistry()
        self.registry = AgentRegistry()
        self.runtime = None


class _Kernel:
    def __init__(self):
        self.event_bus = _EventBus()
        self.agent_orchestrator = _Orchestrator()

    def register_sensor(self, name, factory):
        pass


class ExamplePluginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "examples.sqlite3"
        database.init_db()
        self.kernel = _Kernel()
        self.manager = PluginManager(
            str(ROOT / "examples" / "plugins"),
            kernel=self.kernel,
            config=None,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_examples_load_and_register(self):
        asyncio.run(self.manager.load_plugins())
        status = self.manager.status()
        self.assertEqual(status["loaded"], 3, self.manager.list_plugins())
        ids = {item["id"] for item in self.manager.list_plugins()}
        self.assertTrue({
            "example.hello-world",
            "example.reading-list",
            "example.focus-budget",
        } <= ids)

        tools = set(self.kernel.agent_orchestrator.tool_registry.list())
        self.assertTrue({
            "example.word_count", "example.reading_list", "example.reading_add", "example.focus_budget",
        } <= tools)
        self.assertEqual(len(self.manager.collect_routers()), 3)
        self.assertIn("reading_coach", load_definitions())
        self.assertIn("device.focus.session", self.kernel.event_bus.handlers)

    def test_reading_list_tool_round_trip(self):
        asyncio.run(self.manager.load_plugins())
        registry = self.kernel.agent_orchestrator.tool_registry
        add = registry.get("example.reading_add")
        listing = registry.get("example.reading_list")
        added = asyncio.run(add.execute(title="Designing Data-Intensive Applications",
                                        url="https://example.com/ddia"))
        self.assertFalse(added.isError)
        result = asyncio.run(listing.execute())
        self.assertFalse(result.isError)
        self.assertIn("Data-Intensive", result.content[0].text)

    def test_focus_budget_tool_and_event(self):
        asyncio.run(self.manager.load_plugins())
        tool = self.kernel.agent_orchestrator.tool_registry.get("example.focus_budget")
        result = asyncio.run(tool.execute())
        self.assertIn("focus minutes", result.content[0].text)

        handler = self.kernel.event_bus.handlers["device.focus.session"][0]
        event = type("Event", (), {"data": {"payload": {"duration_seconds": 600}}})
        asyncio.run(handler(event))
        result = asyncio.run(tool.execute())
        self.assertIn("10 focus minutes", result.content[0].text)


class ExampleMcpServerTests(unittest.TestCase):
    def test_notes_server_handshake_and_tools(self):
        connection = MCPServerConnection.stdio(
            name="notes-example",
            command=sys.executable,
            args=[str(ROOT / "examples" / "mcp" / "notes_server.py")],
            env={"PYTHONPATH": str(ROOT)},
        )

        async def exercise():
            await connection.connect()
            try:
                tools = await connection.session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertTrue({"notes_save", "notes_list", "notes_search"} <= names)
                saved = await connection.session.call_tool(
                    "notes_save", {"title": "Example note", "body": "hello from MCP"})
                self.assertIn("saved note", saved.content[0].text)
                listed = await connection.session.call_tool(
                    "notes_list", {"limit": 10})
                self.assertIn("Example note", listed.content[0].text)
                found = await connection.session.call_tool(
                    "notes_search", {"query": "hello"})
                self.assertIn("Example note", found.content[0].text)
            finally:
                await connection.close()

        asyncio.run(exercise())

    def test_office_server_handshake_and_reads(self):
        from datetime import datetime, timezone
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        office = Path(tmp.name)
        today = datetime.now(timezone.utc).date().isoformat()
        (office / "emails.json").write_text(json.dumps([
            {"from": "sam@example.com", "subject": "Review plan",
             "body": "Can you review?", "link": "https://mail.example/1"}
        ]), encoding="utf-8")
        (office / "calendar.json").write_text(json.dumps({"events": [
            {"title": "Standup", "start": f"{today}T09:00:00+00:00",
             "end": f"{today}T09:15:00+00:00"}
        ]}), encoding="utf-8")
        (office / "tasks.json").write_text(json.dumps({"tasks": [
            {"title": "Pay invoice", "due": f"{today}T17:00:00+00:00"}
        ]}), encoding="utf-8")
        connection = MCPServerConnection.stdio(
            name="office-example",
            command=sys.executable,
            args=[str(ROOT / "examples" / "mcp" / "office_server.py")],
            env={"PYTHONPATH": str(ROOT), "VIRA_OFFICE_DIR": str(office)},
        )

        async def exercise():
            await connection.connect()
            try:
                tools = await connection.session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertTrue({"email_inbox", "calendar_today", "tasks_due"} <= names)
                email = await connection.session.call_tool("email_inbox", {"limit": 5})
                self.assertIn("Review plan", email.content[0].text)
                calendar = await connection.session.call_tool("calendar_today", {})
                self.assertIn("Standup", calendar.content[0].text)
                tasks = await connection.session.call_tool("tasks_due", {"days": 7})
                self.assertIn("Pay invoice", tasks.content[0].text)
            finally:
                await connection.close()

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
