"""Morning Brief agent: grounding, fallbacks and end-to-end schedule delivery."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from vira import notifications
from vira.agent import schedules
from vira.agent.Agents.morning_brief import MorningBriefAgent
from vira.agent.base import TaskRequest
from vira.agent.proactive import ProactiveScheduler
from vira.agent_orchestration.registry import AgentRegistry
from vira.agent_orchestration.scheduler import RuntimeScheduler
from vira.auth import auth, database
from vira.tools.base import ToolPermission, text_result


class _Tool:
    def __init__(self, name, actions=("read",)):
        self.name = name
        self.description = f"{name} tool"
        self.permissions = ToolPermission(actions=list(actions))
        self.server_name = None

    def get_schema(self):
        return {"type": "object", "properties": {}}


class _Registry:
    version = 1

    def __init__(self, tools):
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name):
        return self._tools.get(name)


class _Executor:
    def __init__(self, tools):
        self._registry = _Registry(tools)

    def list_tools(self):
        return list(self._registry._tools)


class _Runtime:
    def __init__(self, outputs=None, reply="BRIEF TEXT", memory=None,
                 fail_llm=False):
        self.outputs = outputs or {}
        self.reply = reply
        self.memory = memory or []
        self.fail_llm = fail_llm
        self.prompts = []
        self.calls = []
        tools = [_Tool("user_context"), _Tool("insights")]
        self.tool_executor = _Executor(tools)

    async def get_context(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)

    async def call_llm(self, agent_id, prompt, **kwargs):
        self.prompts.append(prompt)
        if self.fail_llm:
            raise RuntimeError("model unavailable")
        return SimpleNamespace(text=self.reply)

    async def use_tool(self, agent_id, name, required_action=None, **kwargs):
        self.calls.append((name, required_action, kwargs))
        value = self.outputs.get(name)
        if isinstance(value, Exception):
            raise value
        if value is None:
            return text_result("ERROR: no data", is_error=True)
        return text_result(value)

    async def memory_operation(self, agent_id, operation, **kwargs):
        return list(self.memory) if operation == "retrieve" else "id"

    async def send_agent_message(self, sender_agent_id, event_type, data,
                                 target_agent_ids=None, exclude_sender=True):
        return None


def _request(message="Generate the morning brief") -> TaskRequest:
    return TaskRequest(input={"message": message}, user_id=1,
                       conversation_id="c1", run_id="r1",
                       metadata={"trigger": "schedule"})


class MorningBriefTests(unittest.IsolatedAsyncioTestCase):
    async def test_brief_uses_collected_sources(self):
        runtime = _Runtime(outputs={
            "user_context": "Battery: 42%. Devices: Pixel.",
            "insights": "Yesterday: 3h focus, top app Editor.",
        })
        agent = MorningBriefAgent(runtime, agent_id="morning-brief")
        await agent.initialize()
        result = await agent.run_task(_request())
        self.assertEqual(result.text, "BRIEF TEXT")
        self.assertEqual(set(result.data["morning_brief"]["sources"]),
                         {"user_context", "insights"})
        self.assertEqual(result.data["morning_brief"]["generated_by"], "llm")
        self.assertEqual(result.data["architecture"], "single")
        prompt = runtime.prompts[0]
        self.assertIn("Yesterday: 3h focus", prompt)
        self.assertIn("ONLY the context", prompt)
        self.assertIn("Do first", prompt)

    async def test_missing_tool_is_labelled_unavailable(self):
        runtime = _Runtime(outputs={
            "user_context": "No linked devices.",
            "insights": "No usage yet.",
        })
        agent = MorningBriefAgent(
            runtime, agent_id="morning-brief",
            context_tools=[
                {"name": "user_context"},
                {"name": "insights", "params": {"days": 1}},
                {"name": "calendar"},
            ])
        await agent.initialize()
        result = await agent.run_task(_request())
        self.assertEqual([item["source"] for item in
                          result.data["morning_brief"]["unavailable"]], ["calendar"])
        self.assertIn("UNAVAILABLE: not installed", runtime.prompts[0])

    async def test_tool_error_is_labelled_unavailable(self):
        runtime = _Runtime(outputs={
            "user_context": RuntimeError("permission denied"),
            "insights": "Usage exists.",
        })
        agent = MorningBriefAgent(runtime, agent_id="morning-brief")
        await agent.initialize()
        result = await agent.run_task(_request())
        unavailable = result.data["morning_brief"]["unavailable"]
        self.assertEqual(unavailable[0]["source"], "user_context")
        self.assertIn("permission denied", unavailable[0]["reason"])

    async def test_disallowed_tool_is_labelled_unavailable(self):
        runtime = _Runtime(outputs={"user_context": "Device ok.",
                                    "insights": "Focus 2h."})
        agent = MorningBriefAgent(
            runtime, agent_id="morning-brief",
            tools={"allow": ["insights"]})
        await agent.initialize()
        result = await agent.run_task(_request())
        unavailable = result.data["morning_brief"]["unavailable"]
        self.assertEqual(unavailable[0]["source"], "user_context")
        self.assertIn("not allowed", unavailable[0]["reason"])

    async def test_memory_is_optional_context(self):
        runtime = _Runtime(
            outputs={"user_context": "Device ok.", "insights": "Focus 2h."},
            memory=[SimpleNamespace(content="Prefers deep work at 09:00")])
        agent = MorningBriefAgent(runtime, agent_id="morning-brief")
        await agent.initialize()
        result = await agent.run_task(_request())
        self.assertIn("memory", result.data["morning_brief"]["sources"])
        self.assertIn("Prefers deep work at 09:00", runtime.prompts[0])

    async def test_fallback_when_model_fails(self):
        runtime = _Runtime(
            outputs={"user_context": "Battery 20%.", "insights": "Focus 1h."},
            fail_llm=True)
        agent = MorningBriefAgent(runtime, agent_id="morning-brief")
        await agent.initialize()
        result = await agent.run_task(_request())
        self.assertEqual(result.data["morning_brief"]["generated_by"], "fallback")
        self.assertIn("Morning brief", result.text)
        self.assertIn("Battery 20%", result.text)
        self.assertIn("Do first", result.text)

    async def test_empty_message_still_produces_brief(self):
        runtime = _Runtime(outputs={"user_context": "ok", "insights": "ok"})
        agent = MorningBriefAgent(runtime, agent_id="morning-brief")
        await agent.initialize()
        result = await agent.run_task(_request(""))
        self.assertEqual(result.text, "BRIEF TEXT")


class MorningBriefScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "morning.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")

    def tearDown(self):
        self.tmp.cleanup()

    async def test_schedule_delivers_one_brief_notification(self):
        runtime = _Runtime(outputs={"user_context": "Device ok.",
                                    "insights": "Focus 3h."},
                           reply="Today: one priority.")
        agent = MorningBriefAgent(runtime, agent_id="morning-brief")
        await agent.initialize()
        await agent.start()
        registry = AgentRegistry()
        await registry.register(agent)
        scheduler = ProactiveScheduler(
            registry, RuntimeScheduler(registry),
            config={"max_concurrent": 1, "run_timeout_seconds": 30})

        item = schedules.create_schedule(
            1, "morning-brief", "Morning brief", "Generate today's brief",
            schedule_type="interval", interval_minutes=60)
        with database.transaction() as conn:
            conn.execute("UPDATE agent_schedules SET next_run_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                          item["id"]))

        await scheduler.run_due()
        await scheduler.drain()

        notes = notifications.list_for_user(1)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["body"], "Today: one priority.")
        self.assertEqual(notes[0]["kind"], "agent_schedule")
        runs = schedules.list_runs(item["id"], 1)
        self.assertEqual(runs[0]["status"], "ok")
        # A second tick must not duplicate the notification.
        await scheduler.run_due()
        await scheduler.drain()
        self.assertEqual(len(notifications.list_for_user(1)), 1)


if __name__ == "__main__":
    unittest.main()
