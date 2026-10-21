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


def test_restore_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    outside = tmp_path / "outside.txt"
    outside.write_text("unsafe", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(outside, arcname="../../outside.txt")

    backend = BubblewrapBackend(root=str(tmp_path), bwrap_binary="/bin/true")
    with unittest.TestCase().assertRaisesRegex(ValueError, "outside"):
        asyncio.run(backend.restore(str(archive), agent_id="agent-a"))
