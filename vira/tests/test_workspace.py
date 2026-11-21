"""Workspace-centric sandbox behaviour: sharing, visibility, host mode."""
import tempfile
import unittest
from pathlib import Path

from vira.sandbox import SandboxManager
from vira.sandbox.models import SandboxPolicy
from vira.workspace.service import WorkspaceService


class WorkspaceServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = WorkspaceService(
            root=str(Path(self.tmp.name) / "workspaces"),
            allow_user_paths=True, default_execution_mode="bubblewrap")

    def test_default_workspace_is_shared_per_user(self):
        first = self.service.resolve(None, 7)
        second = self.service.resolve(None, 7)
        other = self.service.resolve(None, 8)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["path"], second["path"])
        self.assertTrue(first["path"].endswith("user-7"))
        self.assertNotEqual(first["path"], other["path"])
        self.assertTrue(Path(first["path"]).is_dir())

    def test_named_workspace_is_stable_and_sanitized(self):
        first = self.service.resolve("Coffee Shop!", 1)
        second = self.service.resolve("Coffee Shop!", 1)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["name"], "Coffee-Shop")
        self.assertTrue(first["path"].endswith("Coffee-Shop"))

    def test_absolute_user_path_is_used_when_allowed(self):
        custom = Path(self.tmp.name) / "existing-project"
        custom.mkdir()
        record = self.service.resolve(str(custom), 1)
        self.assertEqual(record["path"], str(custom.resolve()))
        self.assertTrue(Path(record["path"]).is_dir())

    def test_absolute_path_rejected_when_disallowed(self):
        strict = WorkspaceService(
            root=str(Path(self.tmp.name) / "strict"),
            allow_user_paths=False, default_execution_mode="bubblewrap")
        with self.assertRaises(PermissionError):
            strict.resolve(str(Path(self.tmp.name) / "outside"), 1)

    def test_system_paths_are_rejected(self):
        with self.assertRaises(PermissionError):
            self.service.resolve("/etc", 1)
        with self.assertRaises(PermissionError):
            self.service.resolve("/", 1)

    def test_execution_mode_is_per_workspace(self):
        record = self.service.resolve("host-project", 1, execution_mode="host")
        self.assertEqual(record["execution_mode"], "host")
        again = self.service.resolve("host-project", 1)
        self.assertEqual(again["execution_mode"], "host")


class SharedWorkspaceSandboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = SandboxManager(
            root=str(Path(self.tmp.name) / "sandboxes"),
            bwrap_binary="/bin/true",
            workspace_root=str(Path(self.tmp.name) / "workspaces"),
        )

    async def test_two_agents_attach_to_the_same_workspace(self):
        first = await self.manager.find_or_create("agent-a", 3)
        second = await self.manager.find_or_create("agent-b", 3)
        self.assertEqual(first["workspace"], second["workspace"])
        self.assertEqual(first["workspace_id"], second["workspace_id"])
        self.assertNotEqual(first["sandbox_id"], second["sandbox_id"])
        # Each agent keeps its own sandbox namespace but sees the same files.
        await self.manager.write_file(
            first["sandbox_id"], "agent-a", "shared.txt", "hello", user_id=3)
        read = await self.manager.read_file(
            second["sandbox_id"], "agent-b", "shared.txt", user_id=3)
        self.assertEqual(read["content"], "hello")

    async def test_explicit_workspace_name_changes_the_project(self):
        default = await self.manager.find_or_create("agent-a", 3)
        coffee = await self.manager.find_or_create("agent-a", 3,
                                                   workspace="coffee-shop")
        self.assertNotEqual(default["workspace"], coffee["workspace"])
        self.assertTrue(coffee["workspace"].endswith("coffee-shop"))

    async def test_deleting_one_sandbox_keeps_the_shared_workspace(self):
        first = await self.manager.find_or_create("agent-a", 3)
        workspace = Path(first["workspace"])
        await self.manager.write_file(
            first["sandbox_id"], "agent-a", "keep.txt", "data", user_id=3)
        await self.manager.delete(first["sandbox_id"], "agent-a", user_id=3)
        self.assertTrue(workspace.is_dir())
        self.assertTrue((workspace / "keep.txt").is_file())

    async def test_host_mode_uses_the_workspace_and_host_tools(self):
        sandbox = await self.manager.create_for(
            "agent-a", 3, execution_mode="host")
        self.assertEqual(sandbox["policy"]["execution_mode"], "host")
        workspace = Path(sandbox["workspace"])
        result = await self.manager.execute(
            sandbox["sandbox_id"], "pwd", "agent-a", shell=True, user_id=3)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(Path(result["stdout"].strip()), workspace.resolve())

        await self.manager.write_file(
            sandbox["sandbox_id"], "agent-a", "hello.txt", "hi", user_id=3)
        # Virtual /workspace paths are translated for host execution.
        listed = await self.manager.execute(
            sandbox["sandbox_id"], "cat /workspace/hello.txt", "agent-a",
            shell=True, user_id=3)
        self.assertEqual(listed["exit_code"], 0)
        self.assertEqual(listed["stdout"].strip(), "hi")

    async def test_host_mode_does_not_require_bubblewrap(self):
        sandbox = await self.manager.create_for(
            "agent-a", 3, execution_mode="host")
        result = await self.manager.execute(
            sandbox["sandbox_id"], ["/bin/echo", "ok"], "agent-a", user_id=3)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].strip(), "ok")

    async def test_sandbox_listing_exposes_workspace_location(self):
        await self.manager.find_or_create("agent-a", 3)
        listed = await self.manager.list("agent-a", user_id=3)
        item = listed["sandboxes"][0]
        self.assertIn("workspace", item)
        self.assertIn("workspace_id", item)
        self.assertTrue(Path(item["workspace"]).is_absolute())

    async def test_reusing_a_sandbox_raises_its_limits(self):
        first = await self.manager.find_or_create("agent-a", 3)
        self.assertEqual(first["policy"]["timeout_seconds"], 900)
        second = await self.manager.find_or_create(
            "agent-a", 3, policy={"timeout_seconds": 3600, "cpu_seconds": 3600})
        self.assertEqual(second["sandbox_id"], first["sandbox_id"])
        self.assertEqual(second["policy"]["timeout_seconds"], 3600)
        self.assertEqual(second["policy"]["cpu_seconds"], 3600)


if __name__ == "__main__":
    unittest.main()
