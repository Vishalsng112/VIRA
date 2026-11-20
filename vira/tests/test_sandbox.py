import tarfile
import asyncio
import json
import unittest

from vira.sandbox.bubblewrap import BubblewrapBackend
from vira.sandbox.models import SandboxPolicy
from vira.tools.sandbox import SandboxTool


class SandboxLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_lifecycle(self):
        backend = BubblewrapBackend(root=self.temp_dir.name, bwrap_binary="/bin/true")
        sandbox = await backend.create("agent-a", run_id="run-1")
        self.assertEqual(sandbox.workspace, sandbox.workspace.parent / "workspace")

        result = await backend.execute(sandbox.sandbox_id, ["echo", "hello"], agent_id="agent-a")
        self.assertEqual(result["exit_code"], 0)

        with self.assertRaises(PermissionError):
            await backend.execute(sandbox.sandbox_id, ["echo"], agent_id="agent-b")

        archive = await backend.archive(sandbox.sandbox_id, agent_id="agent-a")
        restored = await backend.restore(archive, agent_id="agent-a")
        self.assertEqual(restored.workspace, restored.workspace.parent / "workspace")

        await backend.delete(restored.sandbox_id, agent_id="agent-a")
        self.assertFalse(restored.workspace.parent.exists())

    async def test_install_requires_no_explicit_sandbox_id(self):
        class FakeManager:
            async def create(self, agent_id, run_id=None):
                return {"sandbox_id": "generated", "workspace": "/AgentWorkspace/generated/workspace"}

            async def install(self, sandbox_id, packages, agent_id):
                return {"exit_code": 0, "stdout": "installed", "stderr": ""}

            async def get(self, sandbox_id, agent_id):
                return {"sandbox_id": sandbox_id, "workspace": "/AgentWorkspace/generated/workspace"}

        result = await SandboxTool(FakeManager()).execute(
            "install", agent_id="agent-a", packages=["matplotlib"]
        )
        payload = json.loads(result.content[0].text)
        self.assertEqual(payload["sandbox_id"], "generated")
        self.assertEqual(payload["workspace"], "/AgentWorkspace/generated/workspace")


def test_policy_rejects_invalid_limits():
    with unittest.TestCase().assertRaises(ValueError):
        SandboxPolicy(timeout_seconds=0)
    with unittest.TestCase().assertRaises(ValueError):
        SandboxPolicy(max_processes=0)


def test_package_validation_rejects_shell_input():
    with unittest.TestCase().assertRaises(ValueError):
        BubblewrapBackend._validate_packages(["matplotlib; touch /workspace/unsafe"])
    assert BubblewrapBackend._validate_packages(["matplotlib", "numpy>=2.0"]) == [
        "matplotlib", "numpy>=2.0"
    ]


def test_tool_auto_creates_sandbox_for_execute():
    class FakeManager:
        async def create(self, agent_id, run_id=None):
            return {"sandbox_id": "generated", "workspace": "/AgentWorkspace/generated/workspace"}

        async def execute(self, sandbox_id, command, agent_id, timeout_seconds=None):
            return {"exit_code": 0, "stdout": "figure.png", "stderr": ""}

        async def get(self, sandbox_id, agent_id):
            return {"sandbox_id": sandbox_id, "workspace": "/AgentWorkspace/generated/workspace"}

    import asyncio
    result = asyncio.run(SandboxTool(FakeManager()).execute(
        "execute", agent_id="agent-a", command=["python", "plot.py"]
    ))
    payload = json.loads(result.content[0].text)
    assert payload["sandbox_id"] == "generated"
    assert payload["workspace"].endswith("/workspace")


def test_tool_installs_packages_and_normalizes_python_command():
    class FakeManager:
        def __init__(self):
            self.installed = None
            self.executed = None

        async def create(self, agent_id, run_id=None):
            return {"sandbox_id": "generated", "workspace": "/AgentWorkspace/generated/workspace"}

        async def install(self, sandbox_id, packages, agent_id):
            self.installed = (sandbox_id, packages, agent_id)
            return {"exit_code": 0}

        async def execute(self, sandbox_id, command, agent_id, timeout_seconds=None):
            self.executed = command
            return {"exit_code": 0, "stdout": "figure.png", "stderr": ""}

        async def get(self, sandbox_id, agent_id):
            return {"sandbox_id": sandbox_id, "workspace": "/AgentWorkspace/generated/workspace"}

    manager = FakeManager()
    result = asyncio.run(SandboxTool(manager).execute(
        "execute", agent_id="agent-a", packages=["matplotlib"],
        command=["python -c \"print('figure.png')\""],
    ))
    assert manager.installed == ("generated", ["matplotlib"], "agent-a")
    assert manager.executed[:2] == ["/workspace/.venv/bin/python", "-c"]
    assert json.loads(result.content[0].text)["sandbox_id"] == "generated"


def test_restore_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    outside = tmp_path / "outside.txt"
    outside.write_text("unsafe", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(outside, arcname="../../outside.txt")

    backend = BubblewrapBackend(root=str(tmp_path), bwrap_binary="/bin/true")
    with unittest.TestCase().assertRaisesRegex(ValueError, "outside"):
        asyncio.run(backend.restore(str(archive), agent_id="agent-a"))


def test_process_limit_leaves_headroom_for_existing_user_tasks():
    import resource
    from unittest import mock

    seen = {}
    with mock.patch.object(resource, "setrlimit", lambda kind, value: seen.setdefault(kind, value)):
        BubblewrapBackend._apply_limits(SandboxPolicy(max_processes=128), existing_tasks=3000)
    assert seen[resource.RLIMIT_NPROC] == (3128, 3128)


class SandboxFileTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_read_run_alias_and_escape(self):
        import tempfile
        from vira.sandbox import SandboxManager
        with tempfile.TemporaryDirectory() as root:
            manager = SandboxManager(root=root, bwrap_binary="/bin/true")
            tool = SandboxTool(manager)
            wrote = await tool.execute("write", agent_id="a", user_id=1, path="max.py", content="print(1)")
            first = json.loads(wrote.content[0].text)
            self.assertEqual(first["path"], "max.py")
            # the same user's next call reuses the sandbox; 'run' maps to execute
            ran = await tool.execute("run", agent_id="a", user_id=1, command="python3 max.py")
            self.assertEqual(json.loads(ran.content[0].text)["sandbox_id"], first["sandbox_id"])
            read = await tool.execute("read", agent_id="a", user_id=1, path="/workspace/max.py")
            self.assertEqual(json.loads(read.content[0].text)["content"], "print(1)")
            other = await tool.execute("write", agent_id="a", user_id=2, path="x.py", content="")
            self.assertNotEqual(json.loads(other.content[0].text)["sandbox_id"], first["sandbox_id"])
            bad = await tool.execute("write", agent_id="a", user_id=1, path="../../etc/x", content="no")
            self.assertTrue(getattr(bad, "isError", None) or getattr(bad, "is_error", False))
            unknown = await tool.execute("frobnicate", agent_id="a", user_id=1)
            self.assertIn("Valid operations", unknown.content[0].text)


class SandboxWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from vira.sandbox import SandboxManager
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = SandboxManager(root=self.temp_dir.name, bwrap_binary="/bin/true")
        self.tool = SandboxTool(self.manager)
        created = await self.tool.execute("create", agent_id="agent-a", user_id=7)
        self.sandbox_id = json.loads(created.content[0].text)["sandbox_id"]

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_multi_file_workflow(self):
        written = await self.tool.execute(
            "write_many", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
            files={"src/app.py": "print('hi')\n", "README.md": "demo\n"},
        )
        payload = json.loads(written.content[0].text)
        self.assertEqual(payload["count"], 2)

        listed = json.loads((await self.tool.execute(
            "list", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
        )).content[0].text)
        self.assertEqual({item["path"] for item in listed["files"]},
                         {"src/app.py", "README.md"})

        read = json.loads((await self.tool.execute(
            "read", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
            path="src/app.py",
        )).content[0].text)
        self.assertIn("print", read["content"])

        search = json.loads((await self.tool.execute(
            "search", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
            pattern="print", glob="*.py",
        )).content[0].text)
        self.assertEqual(search["matches"][0]["path"], "src/app.py")

        copied = json.loads((await self.tool.execute(
            "copy", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
            source="src/app.py", destination="src/copy.py",
        )).content[0].text)
        self.assertTrue(copied["copied"])

        moved = json.loads((await self.tool.execute(
            "move", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
            source="src/copy.py", destination="app_copy.py",
        )).content[0].text)
        self.assertTrue(moved["moved"])

        deleted = json.loads((await self.tool.execute(
            "delete_file", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
            path="app_copy.py",
        )).content[0].text)
        self.assertTrue(deleted["deleted"])

    async def test_ownership_blocks_other_user(self):
        denied = await self.tool.execute(
            "read", agent_id="agent-a", user_id=99, sandbox_id=self.sandbox_id, path="x")
        self.assertTrue(denied.isError)

    async def test_sandbox_registry_survives_manager_restart(self):
        from vira.sandbox import SandboxManager
        restarted = SandboxManager(root=self.temp_dir.name, bwrap_binary="/bin/true")
        loaded = await restarted.get(self.sandbox_id, "agent-a", user_id=7)
        self.assertEqual(loaded["sandbox_id"], self.sandbox_id)

    async def test_sandbox_listing_and_usage(self):
        listed = json.loads((await self.tool.execute(
            "sandboxes", agent_id="agent-a", user_id=7)).content[0].text)
        self.assertEqual(listed["count"], 1)
        usage = json.loads((await self.tool.execute(
            "usage", agent_id="agent-a", user_id=7, sandbox_id=self.sandbox_id,
        )).content[0].text)
        self.assertGreater(usage["quota_bytes"], 0)

    def test_shell_command_uses_bash_inside_sandbox(self):
        sandbox = self.manager.backend.get(self.sandbox_id, "agent-a", 7)
        args = self.manager.backend._command(
            sandbox, "echo hi && python3 -V", shell=True)
        self.assertIn("/bin/bash", args)
        self.assertIn("-lc", args)
        self.assertIn("echo hi && python3 -V", args)
        self.assertIn("--cap-drop", args)


class ChatAgentToolPermissionTests(unittest.TestCase):
    def _agent(self, **config):
        from vira.agent.Agents.chat_agent import ChatAgent

        class _Tool:
            def __init__(self, name):
                self.name = name
                self.description = name
            def get_schema(self):
                return {"properties": {}}

        class _Registry:
            def get(self, name):
                return _Tool(name)

        class _Executor:
            def __init__(self):
                self._registry = _Registry()
            def list_tools(self):
                return ["sandbox", "web", "mcp_server.database_query"]

        class _Runtime:
            tool_executor = _Executor()

        return ChatAgent(_Runtime(), {"name": "ChatAgent", "delegation": False, **config})

    def test_allow_list_is_enforced(self):
        agent = self._agent(tools={"allow": ["sandbox"], "pinned": ["sandbox"]})
        self.assertEqual([tool["name"] for tool in agent.available_tools], ["sandbox"])
        self.assertEqual(agent.pinned_tools, ["sandbox"])

    def test_glob_allow_list_accepts_mcp_tools(self):
        agent = self._agent(tools={"allow": ["mcp_server.*", "sandbox"]})
        self.assertEqual({tool["name"] for tool in agent.available_tools},
                         {"sandbox", "mcp_server.database_query"})

    def test_tool_timeout_overrides_are_parsed(self):
        agent = self._agent(tools={"allow": []}, tool_timeouts={"sandbox": 600})
        self.assertEqual(agent.loop_config.tool_timeouts["sandbox"], 600.0)


def test_shipped_config_auto_approves_sandbox_operations():
    from pathlib import Path
    import yaml
    from vira.security import approvals

    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    approval_config = config["security"]["approvals"]
    assert "sandbox" in approval_config.get("safe_tools", [])
    for operation in ("write", "execute", "install", "run", "delete_file"):
        assert approvals.approval_reason(
            "sandbox", "execute", {"operation": operation}, approval_config) is None
    # Other destructive tools remain gated.
    assert approvals.approval_reason(
        "filesystem", "execute", {"operation": "write"}, approval_config)
