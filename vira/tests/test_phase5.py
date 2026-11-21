"""Phase 5 tests: evaluation, generated artifacts, budgets, memory and runs."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vira.agent import benchmark
from vira.agent.loop import AgentLoop, LoopConfig
from vira.agent.definitions import load_definitions
from vira.auth import auth, database
from vira.evaluation import run_all
from vira.generated import service as generated
from vira.generated import store as generated_store
from vira.llm import usage
from vira.memory.manager import MemoryManager
from vira.tools.registry import ToolRegistry


class _FakeRuntime:
    def __init__(self, replies):
        self.replies = list(replies)
        self.tool_executor = None

    async def call_llm(self, agent_id, prompt, **kwargs):
        if not self.replies:
            return SimpleNamespace(text="done")
        return SimpleNamespace(text=self.replies.pop(0))

    async def use_tool(self, agent_id, name, **kwargs):
        return "ok"


class EvaluationTests(unittest.TestCase):
    def test_evaluation_report_is_deterministic_and_complete(self):
        report = run_all()
        self.assertTrue(report.ok, report.markdown())
        names = {suite.name for suite in report.suites}
        self.assertTrue({
            "tool_selection", "task_completion", "memory_retrieval",
            "failure_recovery", "destructive_guard", "run_recovery",
        } <= names)
        payload = report.as_dict()
        self.assertTrue(payload["repeat_stable"])
        self.assertIn("revision", payload)
        self.assertGreater(payload["summary"]["total"], 20)
        self.assertIn("Research basis", report.markdown())


class GeneratedArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "generated.sqlite3"
        database.init_db()
        auth.create_admin("builder", "builderpass1")
        self.user_id = 1

    def tearDown(self):
        self.tmp.cleanup()

    def _tool(self):
        return generated.create_draft(
            kind="tool", name="weather_lookup", version="1.0.0",
            description="Look up a city forecast",
            spec={
                "type": "http", "method": "GET",
                "url": "https://api.example.com/weather",
                "allowed_hosts": ["api.example.com"],
                "parameters": {"city": {"type": "string", "required": True}},
                "query": {"city": "{city}"},
                "response_format": "json",
            },
            created_by_user_id=self.user_id,
        )

    def test_tool_draft_cannot_run_until_approved_and_enabled(self):
        artifact = self._tool()
        self.assertEqual(artifact["status"], "draft")
        registry = ToolRegistry()
        self.assertEqual(generated.sync_registry(registry), [])
        with self.assertRaises(generated.GeneratedError):
            generated.enable(artifact["id"])

        generated.approve(artifact["id"], self.user_id)
        enabled = generated.enable(artifact["id"])
        self.assertEqual(enabled["status"], "enabled")
        registered = generated.sync_registry(registry)
        self.assertIn("generated.weather_lookup", registered)

        tool = registry.get("generated.weather_lookup")
        generated.disable(artifact["id"])
        result = asyncio.run(tool.execute(city="Berlin"))
        self.assertTrue(result.isError)
        self.assertIn("not approved and enabled", result.content[0].text)

    def test_agent_draft_cannot_run(self):
        artifact = generated.create_draft(
            kind="agent", name="brief_writer", version="1.0.0",
            description="Writes a short brief",
            spec={"system_prompt": "You are a careful briefing agent. Return a short brief.",
                  "tools": [], "max_steps": 2, "temperature": 0.1},
            created_by_user_id=self.user_id,
        )
        runtime = _FakeRuntime(["A short brief."])
        with self.assertRaises(generated.GeneratedError):
            asyncio.run(generated.run_agent(artifact, "brief this", runtime, user_id=self.user_id))
        generated.approve(artifact["id"], self.user_id)
        generated.enable(artifact["id"])
        result = asyncio.run(generated.run_agent(
            generated_store.get(artifact["id"]), "brief this", runtime, user_id=self.user_id))
        self.assertEqual(result["response"], "A short brief.")
        self.assertEqual(result["stopped"], "final")

    def test_validation_rejects_unsafe_specs(self):
        with self.assertRaises(generated.GeneratedError):
            generated.create_draft(
                kind="tool", name="bad_tool", version="1.0.0",
                description="unsafe",
                spec={"type": "http", "method": "POST", "url": "http://127.0.0.1/x"},
                created_by_user_id=self.user_id,
            )
        with self.assertRaises(generated.GeneratedError):
            generated.create_draft(
                kind="agent", name="bad_agent", version="1.0.0",
                description="unsafe", spec={"system_prompt": "short"},
                created_by_user_id=self.user_id,
            )


class BudgetTests(unittest.TestCase):
    def test_total_tool_budget_forces_final_answer(self):
        replies = [
            '{"tool": "web_browse", "params": {"url": "https://a"}}',
            "best effort",
        ]
        runtime = _FakeRuntime(replies)
        tools = [{"name": "web_browse", "description": "fetch",
                  "parameters": {"properties": {"url": {"type": "string"}}}}]
        loop = AgentLoop(runtime, "agent", "sys", tools,
                         LoopConfig(max_steps=5, max_total_tool_chars=1))
        result = asyncio.run(loop.run("q"))
        self.assertEqual(result.stopped, "budget")
        self.assertEqual(result.text, "best effort")

    def test_wall_clock_budget_forces_final_answer(self):
        runtime = _FakeRuntime(["best effort"])
        loop = AgentLoop(runtime, "agent", "sys", [],
                         LoopConfig(max_steps=3, max_seconds=0))
        result = asyncio.run(loop.run("q"))
        self.assertEqual(result.stopped, "budget")


class MemoryAndQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "phase5.sqlite3"
        database.init_db()
        auth.create_admin("memory-user", "memorypass1")
        self.user_id = 1

    def tearDown(self):
        self.tmp.cleanup()

    def test_feedback_and_muting(self):
        useful = database.store_memory(self.user_id, "My preferred terminal is zsh")
        muted = database.store_memory(self.user_id, "My preferred terminal is fish")
        self.assertTrue(database.record_memory_feedback(useful, self.user_id, True))
        self.assertTrue(database.set_memory_muted(muted, self.user_id, True))
        items = asyncio.run(MemoryManager().retrieve("preferred terminal", user_id=self.user_id))
        contents = [item.content for item in items]
        self.assertIn("zsh", contents[0])
        self.assertNotIn("fish", " ".join(contents))

    def test_agent_scope_quota(self):
        usage.record(self.user_id, "chat", "ollama", "qwen3.5:9b", 100, 50, 10)
        usage.set_quota("agent", "chat", "month", token_limit=1)
        with self.assertRaises(usage.QuotaExceeded):
            usage.check_quota(self.user_id, None, "chat")
        totals = usage.usage_for_quota("agent", "chat", "month")
        self.assertGreaterEqual(totals["tokens"], 150)


class RunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "runs.sqlite3"
        database.init_db()
        auth.create_admin("runner", "runnerpass1")
        self.user_id = 1

    def tearDown(self):
        self.tmp.cleanup()

    def test_interrupted_runs_are_visible_and_timeline_redacted(self):
        conversation = database.create_conversation(self.user_id, "Run recovery")
        message = database.append_message(conversation, self.user_id, "user", "recover")
        run_id = database.create_run(conversation, self.user_id, message["id"], None, "c")
        database.update_run(run_id, "running")
        self.assertGreaterEqual(database.mark_interrupted_runs(), 1)
        run = database.get_run(run_id, self.user_id)
        self.assertEqual(run["status"], "failed")
        self.assertIn(run_id, {item["id"] for item in database.list_runs(self.user_id, "failed")})

        from vira.agent_runtime import run_store
        run_store.append(run_id, "tool_end", {
            "tool": "filesystem", "params": {"token": "secret-value"},
            "preview": "Bearer abcdefghijklmnop",
        })
        timeline = run_store.timeline(run_id)
        text = str(timeline)
        self.assertNotIn("secret-value", text)
        self.assertNotIn("abcdefghijklmnop", text)


class TemplateTests(unittest.TestCase):
    def test_phase5_templates_load(self):
        definitions = load_definitions()
        for name in ("incident_triage", "research_brief", "data_steward"):
            self.assertIn(name, definitions)
            self.assertTrue(definitions[name].prompt)


if __name__ == "__main__":
    unittest.main()
