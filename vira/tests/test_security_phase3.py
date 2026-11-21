"""Phase 3 security tests: approvals, redaction and cross-user isolation."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from vira import errors
from vira.auth import auth, database
from vira.auth.principals import UserPrincipal
from vira.agent_orchestration import workflow_store
from vira.agent_orchestration.workflow import Workflow, WorkflowStep
from vira.devices import DeviceService
from vira.rag import service as rag_service
from vira.security import approvals
from vira.security.redaction import REDACTED, redact
from vira.tools import database_query
from vira.tools.builtin import FilesystemTool
from vira.tools.executor import ToolExecutor
from vira.tools.registry import ToolRegistry


def principal_for(user_id: int) -> UserPrincipal:
    user = database.get_user_by_id(user_id)
    return UserPrincipal(
        user_id=user_id, username=user["username"],
        roles=(user["role"],), session_id="test", public_id=user["public_id"],
    )


class _AllowAll:
    def authorize(self, permission: str) -> bool:
        return True


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "approvals.sqlite3"
        database.init_db()
        auth.create_admin("approver", "approvepass1")
        self.user_id = 1
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_classification(self):
        self.assertIsNotNone(approvals.approval_reason("filesystem", "execute", {"operation": "write"}))
        self.assertIsNone(approvals.approval_reason("filesystem", "execute", {"operation": "read"}))
        self.assertIsNotNone(approvals.approval_reason("sandbox", "execute", {"operation": "execute"}))
        self.assertIsNotNone(approvals.approval_reason("shell", "execute", {}))
        self.assertIsNone(approvals.approval_reason("database_query.database_query", "execute", {}))
        self.assertIsNone(approvals.approval_reason(
            "filesystem", "execute", {"operation": "write"}, {"enabled": False}))
        self.assertIsNotNone(approvals.approval_reason(
            "custom.tool", "execute", {}, {"destructive_tools": ["custom"]}))

    def test_approve_consume_and_deny(self):
        request = approvals.request_approval(
            "filesystem", "execute", {"operation": "write", "path": "a.txt"},
            user_id=self.user_id, reason="test", ttl_minutes=5,
        )
        self.assertEqual(request["status"], "pending")
        args = {"operation": "write", "path": "a.txt"}
        self.assertIsNone(approvals.find_approved(self.user_id, "filesystem", "execute", args))

        approved = approvals.decide(request["id"], True, self.user_id, "ok")
        self.assertEqual(approved["status"], "approved")
        consumed = approvals.find_approved(self.user_id, "filesystem", "execute", args)
        self.assertEqual(consumed["id"], request["id"])
        # Single use: a second identical call has no approval left.
        self.assertIsNone(approvals.find_approved(self.user_id, "filesystem", "execute", args))

        denied_request = approvals.request_approval(
            "shell", "execute", {"command": "ls"}, user_id=self.user_id,
        )
        denied = approvals.decide(denied_request["id"], False, self.user_id, "no")
        self.assertEqual(denied["status"], "denied")
        self.assertIsNone(approvals.find_approved(
            self.user_id, "shell", "execute", {"command": "ls"}))

    def test_arguments_are_redacted_before_storage(self):
        request = approvals.request_approval(
            "shell", "execute",
            {"command": "env", "api_key": "sk-abcdefghijklmnop", "token": "top-secret"},
            user_id=self.user_id,
        )
        self.assertNotIn("sk-abcdefghijklmnop", str(request["arguments"]))
        self.assertEqual(request["arguments"].get("token"), REDACTED)

    def test_executor_blocks_then_runs_after_approval(self):
        registry = ToolRegistry()
        registry.register(FilesystemTool(self.workspace))
        executor = ToolExecutor(registry, _AllowAll(), approval_config={"enabled": True})
        kwargs = {"agent_id": "agent", "caller_user_id": self.user_id,
                  "operation": "write", "path": "note.txt", "content": "hello"}
        blocked = asyncio.run(executor.execute("filesystem", **kwargs))
        self.assertTrue(blocked.isError)
        self.assertIn("APPROVAL_REQUIRED", blocked.content[0].text)

        pending = approvals.list_requests(self.user_id, "pending")
        self.assertEqual(len(pending), 1)
        approvals.decide(pending[0]["id"], True, self.user_id)

        allowed = asyncio.run(executor.execute("filesystem", **kwargs))
        self.assertFalse(allowed.isError, allowed.content[0].text)
        self.assertEqual((self.workspace / "note.txt").read_text(), "hello")

        # The approval was consumed; the next write asks again.
        again = asyncio.run(executor.execute("filesystem", **kwargs))
        self.assertIn("APPROVAL_REQUIRED", again.content[0].text)

    def test_reads_do_not_need_approval(self):
        (self.workspace / "note.txt").write_text("hello")
        registry = ToolRegistry()
        registry.register(FilesystemTool(self.workspace))
        executor = ToolExecutor(registry, _AllowAll(), approval_config={"enabled": True})
        result = asyncio.run(executor.execute(
            "filesystem", agent_id="agent", caller_user_id=self.user_id,
            operation="read", path="note.txt"))
        self.assertFalse(result.isError, result.content[0].text)
        self.assertIn("hello", result.content[0].text)


class RedactionTests(unittest.TestCase):
    def test_nested_keys_and_token_shapes(self):
        payload = {
            "username": "alice",
            "password": "hunter2",
            "nested": {"api_key": "abc", "note": "Bearer supersecrettoken12345"},
            "list": [{"authorization": "Bearer abcdefghijklmnop"}, "sk-abcdefghijklmnop"],
        }
        clean = redact(payload)
        self.assertEqual(clean["username"], "alice")
        self.assertEqual(clean["password"], REDACTED)
        self.assertEqual(clean["nested"]["api_key"], REDACTED)
        self.assertNotIn("supersecrettoken", clean["nested"]["note"])
        self.assertEqual(clean["list"][0]["authorization"], REDACTED)
        self.assertNotIn("sk-abcdefghijklmnop", str(clean))


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "isolation.sqlite3"
        database.init_db()
        auth.create_admin("alice", "alicepass1")
        self.alice = 1
        self.bob = database.create_user("bob", "hash", "recovery", role="user")
        self.alice_principal = principal_for(self.alice)
        self.bob_principal = principal_for(self.bob)

    def tearDown(self):
        self.tmp.cleanup()

    def test_chat_isolation(self):
        conversation = database.create_conversation(self.alice, "Alice private")
        database.append_message(conversation, self.alice, "user", "alice secret")
        other = database.create_conversation(self.bob, "Bob private")
        database.append_message(other, self.bob, "user", "bob secret")
        self.assertIsNone(database.get_conversation(conversation, self.bob))
        self.assertEqual(database.list_messages(conversation, self.bob), [])
        self.assertFalse(database.delete_conversation(conversation, self.bob))
        self.assertTrue(database.get_conversation(conversation, self.alice))
        self.assertEqual(database.delete_all_conversations(self.alice), 1)
        self.assertIsNone(database.get_conversation(conversation, self.alice))
        self.assertIsNotNone(database.get_conversation(other, self.bob))

    def test_memory_isolation(self):
        database.store_memory(self.alice, "alice private memory", memory_type="long_term")
        self.assertEqual(database.search_memories(self.bob, "alice private"), [])
        self.assertTrue(database.search_memories(self.alice, "alice private"))

    def test_rag_isolation(self):
        asyncio.run(rag_service.ingest(
            self.alice, "Alice notes", "The secret launch date is Thursday."))
        self.assertEqual(rag_service.list_documents(self.bob), [])
        self.assertEqual(asyncio.run(rag_service.search(self.bob, "launch date")), [])
        self.assertTrue(asyncio.run(rag_service.search(self.alice, "launch date")))

    def test_device_and_insight_isolation(self):
        service = DeviceService()
        device = service.register_device(
            self.alice_principal, "Alice phone", "android", "phone")
        device_id = device["device_id"]
        self.assertEqual(service.authorize(self.alice_principal, device_id)[0]["id"], device_id)
        with self.assertRaises(errors.NotFound):
            service.authorize(self.bob_principal, device_id)
        # Insight routes call the same authorize() and never return aggregates
        # without a grant.
        with self.assertRaises(errors.NotFound):
            service.authorize(self.bob_principal, device_id, allow_admin=True)

    def test_workflow_isolation(self):
        workflow = Workflow(
            id="wf-alice", name="Alice workflow",
            steps=[WorkflowStep(id="s1", name="step", agent_id="agent")],
            created_by_user_id=self.alice,
        )
        workflow_store.create(workflow, self.alice)
        self.assertEqual(workflow_store.list_workflows(self.bob), [])
        self.assertEqual(len(workflow_store.list_workflows(self.alice)), 1)

    def test_database_tool_isolation(self):
        conversation = database.create_conversation(self.alice, "Alice chat")
        database.append_message(conversation, self.alice, "user", "hello")
        database.store_memory(self.bob, "bob memory")

        assert database_query.validate_sql("SELECT password_hash FROM users")[0] is False
        denied = database_query.run_query("SELECT 1", caller_user_id=self.bob)
        self.assertFalse(denied["ok"])
        self.assertIn("administrator", denied["error"])

        alice_summary = database_query.account_summary(self.alice)
        bob_summary = database_query.account_summary(self.bob)
        self.assertEqual(alice_summary["chat"]["conversations"], 1)
        self.assertEqual(alice_summary["chat"]["memories"], 0)
        self.assertEqual(bob_summary["chat"]["conversations"], 0)
        self.assertEqual(bob_summary["chat"]["memories"], 1)


try:
    from fastapi.testclient import TestClient

    from vira.api.app import create_app

    class _Config:
        def get(self, key, default=None):
            if key == "auth.https_only":
                return False
            if key == "auth.session_max_age":
                return 86400
            return default

        def get_all(self):
            return {}

        def set(self, key, value):
            pass

        def save(self, value):
            pass

    class _Bus:
        def subscribe_all(self, callback):
            return "sub"

        def unsubscribe_all(self, callback):
            return True

    class _Metrics:
        def record_error(self, *args, **kwargs):
            pass

        def increment_counter(self, *args, **kwargs):
            pass

        def observe_histogram(self, *args, **kwargs):
            pass

    class _Kernel:
        config_manager = _Config()
        event_bus = _Bus()
        metrics_manager = _Metrics()
        local_device = None
        device_service = None
        ingestion_service = None

    class AuditExportApiTests(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            database.DB_PATH = Path(self.tmp.name) / "audit.sqlite3"
            database.init_db()
            auth.create_admin("auditor", "auditorpass1")
            self.client = TestClient(create_app(_Kernel()))
            response = self.client.post(
                "/api/v1/auth/login",
                json={"username": "auditor", "password": "auditorpass1"},
            )
            self.assertEqual(response.status_code, 200, response.text)

        def tearDown(self):
            self.tmp.cleanup()

        def test_redacted_json_export(self):
            database.record_auth_audit(
                "test", "secret.action", True, user_id=1,
                details="password=hunter2 api_key=sk-abcdefghijklmnop",
            )
            database.record_tool_call(
                "filesystem", {"operation": "write", "token": "top-secret"},
                {"ok": True}, "succeeded", True, "execute", 0.01,
            )
            response = self.client.get("/api/v1/admin/audit/export?kind=all&format=json")
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertGreaterEqual(payload["count"], 2)
            body = str(payload)
            self.assertNotIn("hunter2", body)
            self.assertNotIn("top-secret", body)
            self.assertNotIn("sk-abcdefghijklmnop", body)

        def test_csv_export(self):
            database.record_auth_audit("test", "csv.action", True, user_id=1,
                                       details="token=supersecret")
            response = self.client.get("/api/v1/admin/audit/export?format=csv")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("text/csv", response.headers["content-type"])
            self.assertNotIn("supersecret", response.text)

        def test_client_diagnostics_are_redacted_and_listed(self):
            response = self.client.post(
                "/api/v1/diagnostics",
                json={
                    "app": "VIRA Link",
                    "app_version": "1.0.0",
                    "platform": "android",
                    "sync_state": "error",
                    "last_sync_error": "Bearer supersecrettoken12345",
                    "events": [{"message": "password=hunter2"}],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            listing = self.client.get("/api/v1/admin/diagnostics")
            self.assertEqual(listing.status_code, 200, listing.text)
            body = listing.text
            self.assertIn("client_diagnostic", body)
            self.assertNotIn("supersecrettoken", body)
            self.assertNotIn("hunter2", body)

    tests_available = True
except ImportError:  # pragma: no cover - minimal installs without FastAPI
    tests_available = False


if __name__ == "__main__":
    unittest.main()
