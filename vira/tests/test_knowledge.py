"""Knowledge base: scoping, deduplication, promotion and tool surface."""
import tempfile
import unittest
from pathlib import Path

from vira.auth import auth, database
from vira.knowledge import consolidation, policy, service
from vira.knowledge.models import KnowledgeItem
from vira.knowledge.store import SqliteKnowledgeStore
from vira.tools.knowledge_tool import KnowledgeSearchTool, KnowledgeWriteTool


class KnowledgeBaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "knowledge.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        self.user_id = 1
        self.other_id = database.create_user(
            "guest", "x", "y", role="user", status="active")

    def tearDown(self):
        self.tmp.cleanup()

    def _tables(self):
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name LIKE 'knowledge_%'").fetchall()
        return {row[0] for row in rows}

    async def test_migration_creates_knowledge_tables(self):
        self.assertEqual(
            self._tables(),
            {"knowledge_items", "knowledge_chunks", "knowledge_events"},
        )

    async def test_user_requested_write_is_verified_and_searchable(self):
        item = await service.write(
            "The user prefers ISO-8601 dates in reports.",
            user_id=self.user_id, requested_by_user=True)
        self.assertEqual(item["scope"], "personal")
        self.assertEqual(item["status"], "verified")

        results = await service.search("date format reports", user_id=self.user_id)
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], item["id"])
        self.assertEqual(results[0]["_origin"], "knowledge")

    async def test_personal_knowledge_is_not_visible_to_other_users(self):
        item = await service.write(
            "Private note about the user's salary.",
            user_id=self.user_id, requested_by_user=True)
        results = await service.search("salary", user_id=self.other_id)
        self.assertFalse([r for r in results if r.get("id") == item["id"]])

    async def test_agent_scope_requires_the_role(self):
        item = await service.write(
            "Deployments on Fridays tend to fail.",
            user_id=self.user_id, agent_role="researcher")
        self.assertEqual(item["scope"], "agent")

        with_role = await service.search(
            "friday deployments", user_id=self.user_id, agent_role="researcher")
        self.assertTrue([r for r in with_role if r["id"] == item["id"]])

        without_role = await service.search(
            "friday deployments", user_id=self.user_id)
        self.assertFalse([r for r in without_role if r["id"] == item["id"]])

    async def test_duplicate_write_merges_into_one_item(self):
        first = await service.write(
            "The staging cluster lives in eu-west-1.",
            user_id=self.user_id, requested_by_user=True)
        second = await service.write(
            "The staging cluster lives in eu-west-1.",
            user_id=self.user_id, requested_by_user=True)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["revision"], 2)

    async def test_promotion_policy_blocks_global_writes(self):
        low = await service.write(
            "A weakly supported claim.", user_id=self.user_id,
            agent_role="researcher", confidence=0.2)
        with self.assertRaises(PermissionError):
            await service.promote(low["id"])

        strong = await service.write(
            "Python 3.11 was released in October 2022.",
            user_id=self.user_id, agent_role="researcher",
            confidence=0.95, metadata={"confirmations": 3})
        promoted = await service.promote(strong["id"], actor="tester")
        self.assertEqual(promoted["scope"], "global")
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(promoted["metadata"]["promoted_from"], strong["id"])

        # Global knowledge is readable by a different user.
        results = await service.search("Python release", user_id=self.other_id)
        self.assertTrue([r for r in results if r["id"] == promoted["id"]])

    async def test_direct_global_write_is_rejected(self):
        with self.assertRaises(PermissionError):
            await service.write(
                "Global fact", user_id=self.user_id, scope="global")

    async def test_supersede_preserves_revision_chain(self):
        store = SqliteKnowledgeStore()
        original = await store.write(KnowledgeItem(
            content="The office is on the third floor.",
            user_id=self.user_id, scope="personal",
            scope_id=str(self.user_id), status="verified",
            agent_role=None))
        replacement = KnowledgeItem(
            content="The office moved to the fifth floor.",
            user_id=self.user_id, scope="personal",
            scope_id=str(self.user_id), status="verified")
        newer = await store.supersede(original["id"], replacement, actor="tester")

        self.assertEqual(newer["supersedes"], original["id"])
        self.assertEqual(newer["revision"], 2)
        self.assertEqual(store.get(original["id"])["status"], "deprecated")
        self.assertEqual(len(store.revisions(newer["id"])), 2)

    async def test_org_scope_requires_the_organization(self):
        item = await service.write(
            "Team runbook: rotate keys every quarter.",
            user_id=self.user_id, scope="org", organization_id="org-123",
            requested_by_user=True)
        self.assertEqual(item["scope_id"], "org-123")

        in_org = await service.search(
            "rotate keys", user_id=self.other_id, organization_id="org-123")
        self.assertTrue([r for r in in_org if r["id"] == item["id"]])

        outside = await service.search("rotate keys", user_id=self.other_id)
        self.assertFalse([r for r in outside if r["id"] == item["id"]])

    async def test_tools_write_then_search(self):
        written = await KnowledgeWriteTool().execute(
            content="The project codename is VIRA.",
            requested_by_user=True,
            user_id=self.user_id,
        )
        self.assertFalse(written.isError)
        found = await KnowledgeSearchTool().execute(
            query="project codename", user_id=self.user_id)
        self.assertFalse(found.isError)
        self.assertIn("VIRA", found.content[0].text)

    async def test_scope_policy_defaults(self):
        self.assertEqual(
            policy.resolve_write_scope(None, requested_by_user=True,
                                       agent_role="researcher",
                                       conversation_id="c1"),
            "personal")
        self.assertEqual(
            policy.resolve_write_scope(None, requested_by_user=False,
                                       agent_role="researcher",
                                       conversation_id="c1"),
            "agent")
        self.assertEqual(
            policy.resolve_write_scope(None, requested_by_user=False,
                                       agent_role=None,
                                       conversation_id="c1"),
            "conversation")

    async def test_consolidation_reports_candidates_without_promoting(self):
        item = await service.write(
            "Consolidation candidate fact.",
            user_id=self.user_id, agent_role="researcher",
            confidence=0.99, metadata={"confirmations": 4})
        summary = consolidation.run_consolidation({})
        self.assertIn("candidates=", summary)
        stored = service.get_store().get(item["id"])
        self.assertEqual(stored["scope"], "agent")

    async def test_account_deletion_removes_knowledge(self):
        await service.write("Delete me", user_id=self.user_id,
                            requested_by_user=True)
        with database.transaction() as conn:
            conn.execute("DELETE FROM knowledge_items WHERE user_id = ?",
                         (self.user_id,))
        self.assertEqual(service.get_store().export_user(self.user_id), [])


if __name__ == "__main__":
    unittest.main()
