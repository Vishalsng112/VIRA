"""P4 tests: plugin SDK, MCP marketplace/policies, organizations, storage,
usage/quota, update channel and broker selection."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from vira.agent_orchestration.registry import AgentRegistry
from vira.auth import auth, database
from vira.auth.principals import UserPrincipal
from vira.kernel.plugin_manager import PluginManager
from vira.mcp import catalog, store as mcp_store
from vira.mcp import policy as mcp_policy
from vira.organizations import service as orgs
from vira.scaling import get_broker
from vira.storage import service as storage
from vira.tools.base import BaseTool, ToolPermission, text_result
from vira.tools.executor import ToolExecutor
from vira.tools.registry import ToolRegistry
from vira.updates import service as updates
from vira.llm import usage


class _EventBus:
    def subscribe(self, *args):
        pass

    def unsubscribe(self, *args):
        pass


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


class _RiskTool(BaseTool):
    def __init__(self, name="echo", server_name="demo"):
        super().__init__(name, "Echo text", ToolPermission(actions=["read"]))
        self.server_name = server_name

    async def execute(self, text: str = "", **kwargs):
        return text_result(text)


class P4Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "p4.sqlite3"
        database.init_db()
        self.admin_id = database.create_user("admin", "hash", "hash", "admin")
        self.member_id = database.create_user("member", "hash", "hash", "user")

    def tearDown(self):
        self.tmp.cleanup()


class PluginSdkTests(P4Base):
    def test_manifest_plugin_loads_registers_tool_and_route(self):
        kernel = _Kernel()
        manager = PluginManager("examples/plugins", kernel=kernel)
        asyncio.run(manager.load_plugins())
        status = manager.status()
        self.assertEqual(status["loaded"], 1)
        plugin = manager.list_plugins()[0]
        self.assertEqual(plugin["id"], "example.hello-world")
        self.assertEqual(plugin["status"], "active")
        self.assertIn("example_word_count", kernel.agent_orchestrator.tool_registry.list())
        self.assertTrue(manager.collect_routers())

        asyncio.run(manager.set_enabled("example.hello-world", False))
        self.assertNotIn("example_word_count", kernel.agent_orchestrator.tool_registry.list())
        self.assertFalse(manager.collect_routers())

    def test_permissions_are_denied_when_not_declared(self):
        plugin_dir = Path(self.tmp.name) / "bad"
        plugin_dir.mkdir()
        (plugin_dir / "vira-plugin.json").write_text(
            '{"id":"bad.plugin","name":"Bad","version":"1.0.0","entrypoint":"plugin.py:Bad",'
            '"permissions":["sensors.register"]}'
        )
        (plugin_dir / "plugin.py").write_text(
            "from vira.plugins.api import Plugin\n"
            "class Bad(Plugin):\n"
            "    async def setup(self, ctx):\n"
            "        from vira.tools.base import BaseTool, ToolPermission\n"
            "        class T(BaseTool):\n"
            "            def __init__(self):\n"
            "                super().__init__('bad_tool','bad',ToolPermission(actions=['read']))\n"
            "            async def execute(self, **kw):\n"
            "                return None\n"
            "        ctx.register_tool(T())\n"
        )
        manager = PluginManager(str(plugin_dir.parent), kernel=_Kernel())
        asyncio.run(manager.load_plugins())
        item = manager.list_plugins()[0]
        self.assertEqual(item["status"], "error")
        self.assertIn("tools.register", item["error"])


class McpMarketplaceTests(P4Base):
    def test_marketplace_search_and_install(self):
        self.assertTrue(catalog.search("browser"))
        self.assertEqual(catalog.search("fetch")[0]["id"], "fetch")
        record = mcp_store.upsert_server({
            "name": "demo", "transport": "stdio", "command": "true",
            "allowed_tools": ["echo"], "enabled": True,
        }, self.admin_id)
        self.assertEqual(mcp_store.get_server_by_name("demo")["id"], record["id"])
        self.assertEqual(len(mcp_store.list_servers(enabled_only=True)), 1)

    def test_policy_precedence_and_executor_denial(self):
        record = mcp_store.upsert_server({
            "name": "demo", "transport": "stdio", "command": "true",
            "allowed_tools": [], "denied_tools": [], "enabled": True,
        }, self.admin_id)
        mcp_store.set_policy(record["id"], "default", "*", True,
                             allowed_tools=["echo"], denied_tools=[])
        mcp_store.set_policy(record["id"], "user", str(self.member_id), False,
                             allowed_tools=[], denied_tools=[])
        self.assertTrue(mcp_policy.is_allowed(record, "echo", user_id=self.admin_id))
        self.assertFalse(mcp_policy.is_allowed(record, "echo", user_id=self.member_id))

        registry = ToolRegistry()
        registry.register(_RiskTool(), qualified_name="demo.echo")
        executor = ToolExecutor(registry, None)
        result = asyncio.run(executor.execute(
            "demo.echo", caller_user_id=self.member_id, text="hi"))
        self.assertTrue(result.isError)


class OrganizationTests(P4Base):
    def test_org_membership_and_roles(self):
        org = orgs.create(self.admin_id, "Acme Team")
        self.assertIn("acme-team", org["slug"])
        orgs.add_member(org["id"], self.admin_id, self.member_id, "admin")
        self.assertEqual(orgs.role_of(org["id"], self.member_id), "admin")
        self.assertTrue(orgs.is_member(org["id"], self.member_id))
        orgs.update_member(org["id"], self.admin_id, self.member_id, "member")
        self.assertEqual(orgs.role_of(org["id"], self.member_id), "member")
        self.assertTrue(orgs.remove_member(org["id"], self.admin_id, self.member_id))
        self.assertFalse(orgs.is_member(org["id"], self.member_id))


class ObjectStorageTests(P4Base):
    def setUp(self):
        super().setUp()
        os.environ["VIRA_OBJECT_DIR"] = str(Path(self.tmp.name) / "objects")
        os.environ["VIRA_OBJECT_STORE"] = "local"
        storage.reset_backend()

    def tearDown(self):
        storage.reset_backend()
        os.environ.pop("VIRA_OBJECT_DIR", None)
        os.environ.pop("VIRA_OBJECT_STORE", None)
        super().tearDown()

    def test_put_read_delete_and_org_access(self):
        org = orgs.create(self.admin_id, "Storage Team")
        orgs.add_member(org["id"], self.admin_id, self.member_id, "member")
        record = asyncio.run(storage.put(
            b"hello", "text/plain", self.admin_id, org["id"], "notes/hello.txt"))
        self.assertEqual(record["size_bytes"], 5)
        self.assertTrue(storage.can_access(record, self.member_id))
        self.assertEqual(asyncio.run(storage.read(record)), b"hello")
        self.assertTrue(asyncio.run(storage.delete(record["id"])))
        self.assertIsNone(storage.get_record(record["id"]))


class UsageAndUpdateTests(P4Base):
    def test_usage_record_summary_and_quota(self):
        usage.record(self.admin_id, "chat", "ollama", "llama3",
                     100, 50, 12.5)
        summary = usage.summary(self.admin_id, 30)
        self.assertEqual(summary["totals"]["tokens"], 150)
        self.assertEqual(summary["totals"]["calls"], 1)
        usage.set_quota("user", str(self.admin_id), "month", token_limit=100)
        with self.assertRaises(usage.QuotaExceeded):
            usage.check_quota(self.admin_id)

    def test_update_check_semver(self):
        self.assertEqual(updates.compare("1.2.0", "1.10.0"), -1)
        self.assertEqual(updates.compare("2.0.0-beta.1", "2.0.0"), -1)
        updates.publish("client", "stable", "1.2.0", notes="new", user_id=self.admin_id)
        result = updates.check("client", "stable", "1.0.0")
        self.assertTrue(result["update_available"])
        self.assertFalse(updates.check("client", "stable", "1.2.0")["update_available"])

    def test_database_broker_is_default(self):
        os.environ.pop("VIRA_BROKER", None)
        self.assertEqual(get_broker().name, "database")


if __name__ == "__main__":
    unittest.main()
