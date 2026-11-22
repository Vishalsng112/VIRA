"""Chief of Staff and Household agents."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from vira.agent.Agents.chief_of_staff import ChiefOfStaffAgent
from vira.agent.Agents.household import HouseholdAgent
from vira.agent.base import TaskRequest
from vira.auth import auth, database
from vira.family import store as family_store
from vira.tooling import ToolPermission, text_result


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
    def __init__(self, outputs=None, handler=None, fail_llm=False, memory=None):
        self.outputs = outputs or {}
        self.handler = handler
        self.fail_llm = fail_llm
        self.memory = memory or []
        self.prompts = []
        self.calls = []
        names = list(self.outputs) or ["email", "calendar", "tasks"]
        self.tool_executor = _Executor([_Tool(name) for name in names])

    async def get_context(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)

    async def call_llm(self, agent_id, prompt, **kwargs):
        self.prompts.append(prompt)
        if self.fail_llm:
            raise RuntimeError("model down")
        if self.handler:
            return SimpleNamespace(text=self.handler(prompt))
        return SimpleNamespace(text="OK")

    async def use_tool(self, agent_id, name, required_action=None, **kwargs):
        self.calls.append(name)
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


def _request(message="Update", user_id=1, **input_data):
    return TaskRequest(input={"message": message, **input_data}, user_id=user_id,
                       conversation_id="c1", run_id="r1", metadata={})


class ChiefOfStaffTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def handler(prompt):
        if "SOURCE NAME: email" in prompt:
            return ('{"summary": "One thread needs a reply.",'
                    '"action_items": [{"text": "Reply to Sam", "due": "today",'
                    '"link": "https://mail.example/1"}],'
                    '"drafts": [{"to": "sam@example.com", "subject": "Re: plan",'
                    '"body": "Thanks, I will review today."}]}')
        if "SOURCE NAME: calendar" in prompt:
            return ('{"summary": "Standup at nine.",'
                    '"action_items": [{"text": "Join standup", "due": "09:00"}],'
                    '"drafts": []}')
        if "SOURCE NAME: tasks" in prompt:
            return ('{"summary": "One task due.",'
                    '"action_items": [{"text": "Pay invoice", "due": "Friday"}],'
                    '"drafts": []}')
        return '{"summary": "", "action_items": [], "drafts": []}'

    async def test_centralized_triage_extracts_items_and_drafts(self):
        runtime = _Runtime(outputs={
            "email": "From Sam: can you review the plan? https://mail.example/1",
            "calendar": "09:00 Standup",
            "tasks": "Pay invoice Friday",
        }, handler=self.handler)
        agent = ChiefOfStaffAgent(
            runtime, agent_id="chief-of-staff",
            context_tools=[
                {"name": "email", "role": "email"},
                {"name": "calendar", "role": "calendar"},
                {"name": "tasks", "role": "tasks"},
            ])
        await agent.initialize()
        result = await agent.run_task(_request("Morning triage"))
        self.assertEqual(result.data["architecture"], "centralized")
        self.assertEqual(len(result.data["chief_of_staff"]["action_items"]), 3)
        self.assertEqual(len(result.data["chief_of_staff"]["drafts"]), 1)
        self.assertEqual(result.data["chief_of_staff"]["sent"], 0)
        self.assertIn("Priority actions", result.text)
        self.assertIn("Drafts (not sent", result.text)
        self.assertIn("Nothing was sent automatically", result.text)
        self.assertEqual(sorted(runtime.calls), ["calendar", "email", "tasks"])

    async def test_missing_connector_degrades_gracefully(self):
        runtime = _Runtime(outputs={"email": "One message"}, handler=self.handler)
        agent = ChiefOfStaffAgent(
            runtime, agent_id="chief-of-staff",
            context_tools=[
                {"name": "email", "role": "email"},
                {"name": "calendar", "role": "calendar"},
            ])
        await agent.initialize()
        result = await agent.run_task(_request("Morning"))
        unavailable = result.data["chief_of_staff"]["unavailable"]
        self.assertEqual(unavailable[0]["source"], "calendar")
        self.assertIn("not installed", unavailable[0]["reason"])
        self.assertIn("Unavailable: calendar", result.text)

    async def test_no_connectors_explains_configuration(self):
        agent = ChiefOfStaffAgent(
            _Runtime(), agent_id="chief-of-staff", context_tools=[])
        await agent.initialize()
        result = await agent.run_task(_request("Morning"))
        self.assertIn("No email, calendar or task connector", result.text)
        self.assertEqual(result.data["chief_of_staff"]["action_items"], [])

    async def test_preferences_are_used_for_tone(self):
        runtime = _Runtime(
            outputs={"email": "One message"}, handler=self.handler,
            memory=[SimpleNamespace(content="Keep replies short and formal.")])
        agent = ChiefOfStaffAgent(
            runtime, agent_id="chief-of-staff",
            context_tools=[{"name": "email", "role": "email"}])
        await agent.initialize()
        result = await agent.run_task(_request("Morning"))
        self.assertTrue(result.data["chief_of_staff"]["preferences_used"])
        self.assertIn("Keep replies short and formal.", runtime.prompts[0])

    async def test_evening_mode_header(self):
        runtime = _Runtime(outputs={"tasks": "Loose end"}, handler=self.handler)
        agent = ChiefOfStaffAgent(
            runtime, agent_id="chief-of-staff",
            context_tools=[{"name": "tasks", "role": "tasks"}])
        await agent.initialize()
        result = await agent.run_task(_request("Evening follow-up", mode="evening"))
        self.assertIn("evening triage", result.text)


class HouseholdTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "household.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        self.other_id = database.create_user("other", "x", "y", role="user")
        self.outside_id = database.create_user("outside", "x", "y", role="user")
        family_store.ensure_schema()
        self.household_id = family_store.ensure_household(1)["id"]
        family_store.add_member(1, self.household_id, self.other_id, "adult")
        family_store.push(1, self.household_id, [
            {"entity_type": "note", "entity_id": "note1",
             "data": {"title": "Meal plan", "body_md": "Pasta Monday, soup Tuesday"}},
            {"entity_type": "checklist_item", "entity_id": "chore1",
             "data": {"note_id": "note1", "text": "Buy milk"}},
            {"entity_type": "reminder", "entity_id": "rem1",
             "data": {"title": "Pay electricity bill",
                      "due_at": "2026-11-22T09:00:00+00:00"}},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def handler(prompt):
        if "Focus only on meals" in prompt:
            return "Meals: pasta plan."
        if "Focus only on bills" in prompt:
            return "Budget: electricity bill due."
        if "Focus only on chores" in prompt:
            return "Chores: buy milk."
        return "HOUSEHOLD TEXT"

    async def test_morning_uses_shared_household_data(self):
        runtime = _Runtime(handler=self.handler)
        agent = HouseholdAgent(
            runtime, agent_id="household", household_id=self.household_id)
        await agent.initialize()
        result = await agent.run_task(_request("Morning household plan"))
        self.assertEqual(result.text, "HOUSEHOLD TEXT")
        self.assertEqual(result.data["household"]["household_id"], self.household_id)
        self.assertEqual(result.data["household"]["reminders"], 1)
        self.assertEqual(result.data["household"]["open_chores"], 1)
        prompt = runtime.prompts[0]
        self.assertIn("Pay electricity bill", prompt)
        self.assertIn("Buy milk", prompt)
        self.assertIn("Pasta Monday", prompt)

    async def test_weekly_fans_out_to_three_workers(self):
        runtime = _Runtime(handler=self.handler)
        agent = HouseholdAgent(
            runtime, agent_id="household", household_id=self.household_id)
        await agent.initialize()
        result = await agent.run_task(
            _request("Weekly household review", mode="weekly"))
        self.assertEqual(result.data["architecture"], "centralized")
        self.assertEqual(result.data["coordination"]["workers"], 3)
        self.assertEqual(len(runtime.prompts), 3)
        self.assertIn("Meals", result.text)
        self.assertIn("Budget", result.text)
        self.assertIn("Chores", result.text)

    async def test_non_member_cannot_read_household(self):
        runtime = _Runtime(handler=self.handler)
        agent = HouseholdAgent(
            runtime, agent_id="household", household_id=self.household_id)
        await agent.initialize()
        result = await agent.run_task(
            _request("Morning", user_id=self.outside_id))
        self.assertIn("access denied", result.text.lower())
        self.assertEqual(result.data["household"]["error"], "permission_denied")

    async def test_fallback_when_model_fails(self):
        runtime = _Runtime(handler=self.handler, fail_llm=True)
        agent = HouseholdAgent(
            runtime, agent_id="household", household_id=self.household_id)
        await agent.initialize()
        result = await agent.run_task(_request("Morning"))
        self.assertEqual(result.data["household"]["generated_by"], "fallback")
        self.assertIn("Household plan", result.text)
        self.assertIn("Pay electricity bill", result.text)


if __name__ == "__main__":
    unittest.main()
