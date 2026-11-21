"""Focus Coach and Second Brain agent behaviour."""
import unittest
from types import SimpleNamespace

from vira.agent.Agents.focus_coach import FocusCoachAgent
from vira.agent.Agents.second_brain import SecondBrainAgent
from vira.agent.base import TaskRequest
from vira.tools.base import ToolPermission, text_result


class _Tool:
    def __init__(self, name):
        self.name = name
        self.description = f"{name} tool"
        self.permissions = ToolPermission(actions=["read"])
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
    def __init__(self, outputs=None, reply="COACH TEXT", memory=None,
                 fail_llm=False):
        self.outputs = outputs or {}
        self.reply = reply
        self.memory = memory or []
        self.fail_llm = fail_llm
        self.prompts = []
        self.calls = []
        self.tool_executor = _Executor([_Tool("user_context"), _Tool("insights")])

    async def get_context(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)

    async def call_llm(self, agent_id, prompt, **kwargs):
        self.prompts.append(prompt)
        if self.fail_llm:
            raise RuntimeError("model down")
        return SimpleNamespace(text=self.reply)

    async def use_tool(self, agent_id, name, required_action=None, **kwargs):
        self.calls.append((name, kwargs))
        value = self.outputs.get(name)
        if isinstance(value, Exception):
            raise value
        return text_result(value if value is not None else "ERROR: no data",
                           is_error=value is None)

    async def memory_operation(self, agent_id, operation, **kwargs):
        return list(self.memory) if operation == "retrieve" else "id"

    async def send_agent_message(self, sender_agent_id, event_type, data,
                                 target_agent_ids=None, exclude_sender=True):
        return None


class _KnowledgeRuntime(_Runtime):
    def __init__(self, reply="ANSWER", items=None, fail_llm=False):
        super().__init__(reply=reply, fail_llm=fail_llm)
        self.items = list(items or [])
        self.writes = []

    async def knowledge_write(self, agent_id, content, **kwargs):
        item = {
            "id": f"k{len(self.writes) + 1}",
            "content": content,
            "scope": "personal",
            "created_at": "2026-11-20T10:00:00+00:00",
            "updated_at": "2026-11-20T10:00:00+00:00",
            "confidence": 0.8,
            **kwargs,
        }
        self.writes.append(item)
        self.items.append(item)
        return item

    async def knowledge_search(self, agent_id, query, **kwargs):
        query = (query or "").lower()
        return [dict(item) for item in self.items
                if not query or any(word in item["content"].lower()
                                    for word in query.split())]

    async def knowledge_list(self, agent_id, *, scopes=None, **kwargs):
        return [dict(item) for item in self.items]

    async def knowledge_correct(self, agent_id, item_id, content, **kwargs):
        previous = next((item for item in self.items if item["id"] == item_id), None)
        if previous is None:
            raise ValueError("knowledge item not found")
        revision = int(previous.get("revision") or 1) + 1
        corrected = {**previous, "id": f"k{len(self.items) + 1}",
                     "content": content, "revision": revision,
                     "supersedes": item_id}
        self.items.append(corrected)
        return corrected


def _request(message="Update", **input_data):
    return TaskRequest(input={"message": message, **input_data}, user_id=1,
                       conversation_id="c1", run_id="r1", metadata={})


class FocusCoachTests(unittest.IsolatedAsyncioTestCase):
    async def test_evening_mode_uses_daily_insights(self):
        runtime = _Runtime(outputs={
            "user_context": "Battery 50%.",
            "insights": "Focus score: 62/100. Categories: work (120m).",
        })
        agent = FocusCoachAgent(runtime, agent_id="focus-coach")
        await agent.initialize()
        result = await agent.run_task(_request("Evening review"))
        self.assertEqual(result.text, "COACH TEXT")
        self.assertEqual(result.data["focus_coach"]["mode"], "evening")
        insight_calls = [call for call in runtime.calls if call[0] == "insights"]
        self.assertEqual(insight_calls[0][1]["days"], 1)
        self.assertIn("62/100", runtime.prompts[0])
        self.assertIn("Evening review", runtime.prompts[0])

    async def test_weekly_mode_hides_apps(self):
        runtime = _Runtime(outputs={
            "user_context": "Device ok.",
            "insights": "Focus score: 55/100. Top apps: hidden for privacy.",
        })
        agent = FocusCoachAgent(runtime, agent_id="focus-coach")
        await agent.initialize()
        result = await agent.run_task(_request(
            "Weekly report", mode="weekly"))
        self.assertEqual(result.data["focus_coach"]["mode"], "weekly")
        self.assertFalse(result.data["focus_coach"]["include_apps"])
        self.assertNotIn("user_context", result.data["focus_coach"]["sources"])
        insight_calls = [call for call in runtime.calls if call[0] == "insights"]
        self.assertFalse(insight_calls[0][1]["include_apps"])
        self.assertIn("weekly focus report", runtime.prompts[0])
        self.assertIn("Do not name specific apps", runtime.prompts[0])

    async def test_morning_mode_asks_for_measured_numbers(self):
        runtime = _Runtime(outputs={
            "user_context": "Battery 80%.",
            "insights": "Focus score: 70/100.",
        })
        agent = FocusCoachAgent(runtime, agent_id="focus-coach", mode="morning")
        await agent.initialize()
        await agent.run_task(_request("Plan my day"))
        self.assertIn("focus plan", runtime.prompts[0].lower())
        self.assertIn("measured number", runtime.prompts[0].lower())

    async def test_goals_memory_is_included(self):
        runtime = _Runtime(
            outputs={"user_context": "ok", "insights": "Focus 1h."},
            memory=[SimpleNamespace(content="Goal: two deep-work blocks")])
        agent = FocusCoachAgent(runtime, agent_id="focus-coach")
        await agent.initialize()
        result = await agent.run_task(_request("Evening"))
        self.assertIn("goals", result.data["focus_coach"]["sources"])
        self.assertIn("two deep-work blocks", runtime.prompts[0])

    async def test_fallback_when_model_fails(self):
        runtime = _Runtime(
            outputs={"user_context": "Battery 20%.", "insights": "Focus score: 40/100."},
            fail_llm=True)
        agent = FocusCoachAgent(runtime, agent_id="focus-coach")
        await agent.initialize()
        result = await agent.run_task(_request("Evening"))
        self.assertEqual(result.data["focus_coach"]["generated_by"], "fallback")
        self.assertIn("Evening review", result.text)
        self.assertIn("40/100", result.text)


class SecondBrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_writes_personal_knowledge(self):
        runtime = _KnowledgeRuntime()
        agent = SecondBrainAgent(runtime, agent_id="second-brain")
        await agent.initialize()
        result = await agent.run_task(
            _request("Remember that the landlord prefers email"))
        self.assertEqual(result.data["second_brain"]["mode"], "capture")
        self.assertEqual(len(runtime.writes), 1)
        write = runtime.writes[0]
        self.assertEqual(write["content"], "the landlord prefers email")
        self.assertTrue(write["requested_by_user"])
        self.assertIn("Saved to your second brain", result.text)

    async def test_empty_capture_is_rejected(self):
        agent = SecondBrainAgent(_KnowledgeRuntime(), agent_id="second-brain")
        await agent.initialize()
        result = await agent.run_task(_request("Remember", mode="capture"))
        self.assertIn("Nothing to save", result.text)
        self.assertTrue(result.error)

    async def test_ask_cites_stored_items(self):
        runtime = _KnowledgeRuntime(items=[{
            "id": "k1",
            "content": "The vendor contract renews in March.",
            "scope": "personal",
            "created_at": "2026-11-01T09:00:00+00:00",
            "updated_at": "2026-11-01T09:00:00+00:00",
            "confidence": 0.9,
        }], reply="It renews in March [1].")
        agent = SecondBrainAgent(runtime, agent_id="second-brain")
        await agent.initialize()
        result = await agent.run_task(_request("When does the vendor contract renew?"))
        self.assertEqual(result.text, "It renews in March [1].")
        self.assertEqual(result.data["second_brain"]["mode"], "ask")
        self.assertEqual(result.data["second_brain"]["hits"], 1)
        self.assertIn("2026-11-01", runtime.prompts[0])
        self.assertIn("Cite notes inline as [1]", runtime.prompts[0])

    async def test_ask_without_hits_does_not_call_model(self):
        runtime = _KnowledgeRuntime()
        agent = SecondBrainAgent(runtime, agent_id="second-brain")
        await agent.initialize()
        result = await agent.run_task(_request("What did I decide about taxes?"))
        self.assertIn("couldn't find", result.text)
        self.assertEqual(runtime.prompts, [])
        self.assertEqual(result.data["second_brain"]["hits"], 0)

    async def test_correct_supersedes_note(self):
        runtime = _KnowledgeRuntime(items=[{
            "id": "k1", "content": "Old fact", "scope": "personal",
            "created_at": "2026-11-01T09:00:00+00:00",
            "updated_at": "2026-11-01T09:00:00+00:00", "confidence": 0.8,
        }])
        agent = SecondBrainAgent(runtime, agent_id="second-brain")
        await agent.initialize()
        result = await agent.run_task(_request(
            "The new fact", mode="correct", item_id="k1"))
        self.assertEqual(result.data["second_brain"]["mode"], "correct")
        self.assertEqual(result.data["second_brain"]["supersedes"], "k1")
        self.assertEqual(result.data["second_brain"]["revision"], 2)
        self.assertIn("Corrected note", result.text)

    async def test_consolidation_reports_without_deleting(self):
        items = [
            {"id": "a", "content": "Same note", "scope": "personal",
             "created_at": "2025-01-01T00:00:00+00:00",
             "updated_at": "2025-01-01T00:00:00+00:00", "confidence": 0.8},
            {"id": "b", "content": "same   note", "scope": "personal",
             "created_at": "2025-01-01T00:00:00+00:00",
             "updated_at": "2025-01-01T00:00:00+00:00", "confidence": 0.8},
            {"id": "c", "content": "Low confidence item", "scope": "personal",
             "created_at": "2025-01-01T00:00:00+00:00",
             "updated_at": "2025-01-01T00:00:00+00:00", "confidence": 0.1},
        ]
        runtime = _KnowledgeRuntime(items=items)
        agent = SecondBrainAgent(runtime, agent_id="second-brain")
        await agent.initialize()
        result = await agent.run_task(_request("Consolidate my notes", mode="consolidate"))
        data = result.data["second_brain"]
        self.assertEqual(data["mode"], "consolidate")
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["duplicates"], 1)
        self.assertEqual(data["stale"], 3)
        self.assertEqual(data["low_confidence"], 1)
        self.assertEqual(data["deleted"], 0)
        self.assertIn("Nothing was deleted", result.text)


if __name__ == "__main__":
    unittest.main()
