"""P2 tests: tool catalog/search, dynamic expansion, run events, agent definitions."""
import tempfile
import unittest
from pathlib import Path

from vira.agent.definitions import load_definitions
from vira.agent.loop import AgentLoop
from vira.agent_runtime.run_store import append, list_events
from vira.auth import auth, database
from vira.memory.manager import MemoryManager
from vira.tools.catalog import ToolCatalog


SPECS = [
    {"name": "mcp_server.web_search", "description": "Search the web for news",
     "parameters": {}},
    {"name": "photoshop.export", "description": "Export Adobe Photoshop layers and images",
     "parameters": {}},
    {"name": "photoshop.actions", "description": "Run Adobe Photoshop actions",
     "parameters": {}},
    {"name": "davinci.render", "description": "Render a DaVinci Resolve timeline",
     "parameters": {}},
    {"name": "insights", "description": "Summarize device usage focus and wellbeing",
     "parameters": {}},
]


class CatalogTests(unittest.TestCase):
    def test_domain_queries_select_relevant_tools(self):
        catalog = ToolCatalog(SPECS)
        self.assertEqual(catalog.search("photoshop export", 2)[0].name,
                         "photoshop.export")
        self.assertEqual(catalog.search("davinci resolve render", 2)[0].name,
                         "davinci.render")
        self.assertEqual(catalog.search("device usage focus", 2)[0].name,
                         "insights")
        self.assertEqual(catalog.search("web search news", 2)[0].name,
                         "mcp_server.web_search")

    def test_fallback_returns_usable_tools(self):
        catalog = ToolCatalog(SPECS)
        result = catalog.search("something unrelated", 3)
        self.assertTrue(result)


class _Runtime:
    pass


class DynamicToolSearchTests(unittest.TestCase):
    def test_tool_search_expands_loop_specs(self):
        catalog = ToolCatalog(SPECS)
        loop = AgentLoop(
            _Runtime(), "agent", "system", catalog.select("web", limit=1),
            catalog=catalog,
        )
        step = __import__("asyncio").run(
            loop._run_tool_inner("tool_search", {"query": "photoshop"}, {}, None)
        )
        self.assertTrue(step.ok)
        self.assertIn("photoshop.export", loop.tool_names)
        self.assertTrue(any("photoshop" in name for name in loop.tool_names))


class SpecialistDefinitionTests(unittest.TestCase):
    def test_specialist_agents_are_loaded(self):
        definitions = load_definitions()
        self.assertIn("insight_coach", definitions)
        self.assertIn("study_coach", definitions)
        self.assertIn("device_doctor", definitions)
        self.assertIn("insights", definitions["insight_coach"].tools or [])


class MemoryRankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "memory.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        database.store_memory(1, "I use Adobe Photoshop for photo editing", memory_type="long_term")
        database.store_memory(1, "I enjoy cooking pasta on weekends", memory_type="long_term")

    def tearDown(self):
        self.tmp.cleanup()

    def test_hybrid_memory_retrieval(self):
        import asyncio
        items = asyncio.run(MemoryManager().retrieve("photoshop editing", user_id=1, limit=1))
        self.assertEqual(len(items), 1)
        self.assertIn("Photoshop", items[0].content)


class RunEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "p2.sqlite3"
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_list_run_events(self):
        append("run-1", "thought", {"text": "thinking"})
        append("run-1", "tool_start", {"tool": "insights"})
        events = list_events("run-1")
        self.assertEqual([event["event_type"] for event in events],
                         ["thought", "tool_start"])
        self.assertEqual(events[0]["seq"], 1)
        self.assertEqual(events[1]["seq"], 2)


if __name__ == "__main__":
    unittest.main()
