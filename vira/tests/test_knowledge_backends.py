"""Storage conformance suite.

The same contract tests run against the SQL adapter and the in-memory adapter.
That is how "not limited by the database type" is proven rather than asserted:
if a future Postgres/Mongo/Qdrant adapter passes this file, callers keep working.
"""
import tempfile
import unittest
from pathlib import Path

from vira.auth import database
from vira.knowledge.backends.memory import MemoryKnowledgeStore
from vira.knowledge.cache import InProcessTtlCache
from vira.knowledge.models import KnowledgeItem
from vira.knowledge.ports import KnowledgeQuery
from vira.knowledge.store import SqliteKnowledgeStore, set_store


class KnowledgeStoreContract:
    expected_durable: bool = True

    async def make_store(self):
        raise NotImplementedError

    async def make_users(self):
        return (1, 2, 7)

    async def prepare(self):
        return None

    async def asyncSetUp(self):
        await self.prepare()
        self.user_a, self.user_b, self.user_c = await self.make_users()
        self.store = await self.make_store()
        set_store(self.store)

    async def asyncTearDown(self):
        set_store(None)

    async def write(self, content, **kwargs):
        user_id = kwargs.pop("user_id", self.user_a)
        scope = kwargs.pop("scope", "personal")
        agent_role = kwargs.pop("agent_role", None)
        scope_id = kwargs.pop("scope_id",
                              str(user_id) if scope == "personal" else agent_role)
        item = KnowledgeItem(
            content=content,
            user_id=user_id,
            scope=scope,
            scope_id=scope_id,
            agent_role=agent_role,
            status=kwargs.pop("status", "verified"),
            confidence=kwargs.pop("confidence", 0.8),
            **kwargs,
        )
        return await self.store.write(item)

    async def search(self, text, **kwargs):
        scopes = kwargs.pop("scopes", None) or ["personal", "agent", "global"]
        query = KnowledgeQuery(text=text, scopes=scopes,
                               user_id=kwargs.pop("user_id", self.user_a), **kwargs)
        return await self.store.search(query)

    async def test_capabilities_are_declared(self):
        caps = self.store.capabilities
        self.assertEqual(caps.durable, self.expected_durable)
        self.assertIsInstance(caps.as_dict(), dict)

    async def test_personal_scope_isolation(self):
        item = await self.write("Private salary information", user_id=self.user_a)
        own = await self.search("salary", user_id=self.user_a)
        other = await self.search("salary", user_id=self.user_b)
        self.assertIn(item["id"], [hit["id"] for hit in own])
        self.assertNotIn(item["id"], [hit["id"] for hit in other])

    async def test_agent_scope_requires_role_and_owner(self):
        item = await self.write(
            "Friday deployments fail", user_id=self.user_a, scope="agent",
            agent_role="researcher")
        with_role = await self.search(
            "friday deployments", user_id=self.user_a, agent_role="researcher")
        self.assertIn(item["id"], [hit["id"] for hit in with_role])
        no_role = await self.search("friday deployments", user_id=self.user_a)
        self.assertNotIn(item["id"], [hit["id"] for hit in no_role])
        other_user = await self.search(
            "friday deployments", user_id=self.user_b, agent_role="researcher")
        self.assertNotIn(item["id"], [hit["id"] for hit in other_user])

    async def test_duplicate_write_merges(self):
        first = await self.write("The staging cluster is in eu-west-1")
        second = await self.write("The staging cluster is in eu-west-1")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["revision"], 2)

    async def test_supersede_creates_revision_chain(self):
        original = await self.write("Office is on floor three")
        replacement = KnowledgeItem(
            content="Office moved to floor five", user_id=1,
            scope="personal", scope_id="1", status="verified")
        newer = await self.store.supersede(original["id"], replacement)
        self.assertEqual(newer["supersedes"], original["id"])
        self.assertEqual(newer["revision"], 2)
        self.assertEqual(self.store.get(original["id"])["status"], "deprecated")
        self.assertEqual(len(self.store.revisions(newer["id"])), 2)

    async def test_promotion_copies_to_global(self):
        item = await self.write(
            "Python 3.11 was released in October 2022",
            user_id=self.user_a, scope="agent", agent_role="researcher")
        promoted = await self.store.promote(item["id"], actor="tester")
        self.assertEqual(promoted["scope"], "global")
        self.assertEqual(promoted["metadata"]["promoted_from"], item["id"])
        other = await self.search("python release", user_id=self.user_b,
                                  scopes=["global"])
        self.assertIn(promoted["id"], [hit["id"] for hit in other])

    async def test_direct_global_write_is_rejected(self):
        item = KnowledgeItem(content="global fact", scope="global")
        with self.assertRaises(PermissionError):
            await self.store.write(item)

    async def test_status_and_kind_filters(self):
        visible = await self.write("Deployment runbook", kind="procedure")
        draft = await self.write("Unverified deployment rumour", status="draft")
        procedures = await self.search("deployment", kinds=["procedure"])
        self.assertIn(visible["id"], [hit["id"] for hit in procedures])
        self.assertNotIn(draft["id"], [hit["id"] for hit in procedures])

    async def test_cache_is_invalidated_by_writes(self):
        await self.write("Initial deployment note")
        await self.search("deployment")
        added = await self.write("Deployment rollback requires approval")
        results = await self.search("deployment rollback approval")
        self.assertIn(added["id"], [hit["id"] for hit in results])

    async def test_delete_and_export(self):
        item = await self.write("Exportable note", user_id=self.user_c)
        self.assertEqual(len(self.store.export_user(self.user_c)), 1)
        self.assertTrue(self.store.delete(item["id"], user_id=self.user_c))
        self.assertIsNone(self.store.get(item["id"]))
        self.assertEqual(self.store.export_user(self.user_c), [])

    async def test_deprecate_hides_from_search(self):
        item = await self.write("Temporary deployment workaround")
        self.assertTrue(self.store.deprecate(item["id"], reason="fixed"))
        results = await self.search("temporary deployment workaround")
        self.assertNotIn(item["id"], [hit["id"] for hit in results])


class SqliteKnowledgeStoreContract(KnowledgeStoreContract,
                                    unittest.IsolatedAsyncioTestCase):
    expected_durable = True

    async def make_store(self):
        return SqliteKnowledgeStore(cache=InProcessTtlCache(ttl_seconds=60))

    async def prepare(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        database.DB_PATH = Path(self._tmp.name) / "knowledge.sqlite3"
        database.init_db()

    async def make_users(self):
        from vira.auth import auth
        auth.create_admin("root", "rootpass1")
        user_b = database.create_user("user-b", "x", "y", role="user")
        user_c = database.create_user("user-c", "x", "y", role="user")
        return (1, user_b, user_c)


class MemoryKnowledgeStoreContract(KnowledgeStoreContract,
                                   unittest.IsolatedAsyncioTestCase):
    expected_durable = False

    async def make_store(self):
        return MemoryKnowledgeStore(cache=InProcessTtlCache(ttl_seconds=60))


class FactoryTests(unittest.TestCase):
    def test_factory_selects_backend(self):
        from vira.knowledge.factory import create_store

        sql = create_store({"backend": "sql", "cache": "none"})
        memory = create_store({"backend": "memory", "cache": "none"})
        self.assertIsInstance(sql, SqliteKnowledgeStore)
        self.assertIsInstance(memory, MemoryKnowledgeStore)
        self.assertTrue(sql.capabilities.durable)
        self.assertFalse(memory.capabilities.durable)

    def test_factory_rejects_unknown_backend(self):
        from vira.knowledge.factory import create_store

        with self.assertRaises(ValueError):
            create_store({"backend": "quantum", "cache": "none"})

    def test_cache_can_be_disabled(self):
        from vira.knowledge.cache import NullCache
        from vira.knowledge.factory import build_cache

        self.assertIsInstance(build_cache({"cache": "none"}), NullCache)


if __name__ == "__main__":
    unittest.main()
