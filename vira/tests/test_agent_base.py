"""BaseAgent contract: lifecycle, tasks, identity, tools and responses."""
import unittest
from types import SimpleNamespace

from vira.agent import runtime_context
from vira.agent.base import BaseAgent, TaskRequest, TaskResult
from vira.agent.toolbox import ToolPolicy, Toolbox
from vira.tools.base import ToolPermission, text_result


class _Tool:
    def __init__(self, name, actions, description=None, provider=None):
        self.name = name
        self.description = description or name
        self.permissions = ToolPermission(actions=actions)
        self.server_name = provider

    def get_schema(self):
        return {"type": "object", "properties": {"q": {"type": "string"}}}


class _Registry:
    def __init__(self, tools):
        self.version = 1
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name):
        return self._tools.get(name)


class _Executor:
    def __init__(self, tools):
        self._registry = _Registry(tools)

    def list_tools(self):
        return list(self._registry._tools)


class _Runtime:
    def __init__(self, tools=None):
        self.tool_executor = _Executor(tools or [])
        self.tool_calls = []
        self.messages = []
        self.stored = []

    async def get_context(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)

    async def call_llm(self, agent_id, prompt, **kwargs):
        return SimpleNamespace(text=f"answer:{prompt}")

    async def use_tool(self, agent_id, name, required_action=None, **kwargs):
        self.tool_calls.append((name, required_action, kwargs))
        return text_result("tool-ok")

    async def memory_operation(self, agent_id, operation, **kwargs):
        if operation == "store":
            self.stored.append(kwargs)
            return "memory-id"
        return []

    async def send_agent_message(self, sender_agent_id, event_type, data,
                                 target_agent_ids=None, exclude_sender=True):
        self.messages.append((sender_agent_id, event_type, data))


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_style_agent_runs_and_reports_state(self):
        class Echo(BaseAgent):
            def __init__(self, runtime=None):
                super().__init__("echo", runtime=runtime)
                self.hooks = []

            async def setup(self):
                self.hooks.append("setup")

            async def on_start(self):
                self.hooks.append("start")

            async def on_stop(self):
                self.hooks.append("stop")

            async def execute(self, request):
                return {"response": f"echo:{request.message}",
                        "user_id": request.user_id}

        runtime = _Runtime()
        agent = Echo(runtime)
        await agent.initialize()
        await agent.initialize()  # idempotent
        await agent.start()
        self.assertEqual(agent.hooks, ["setup", "start"])
        self.assertEqual(agent.state.value, "ready")

        request = TaskRequest(input={"message": "hi"}, user_id=7, run_id="r1")
        result = await agent.run_task(request)
        self.assertIsInstance(result, TaskResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.text, "echo:hi")
        self.assertEqual(result.data["user_id"], 7)
        self.assertEqual(agent.state.value, "ready")

        await agent.stop()
        self.assertEqual(agent.state.value, "terminated")
        self.assertEqual(agent.hooks, ["setup", "start", "stop"])

    async def test_run_returns_raw_value_for_workflows(self):
        class Doubler(BaseAgent):
            async def execute(self, request):
                return {"value": request.input * 2}

        agent = Doubler("doubler")
        self.assertEqual(await agent.run(21), {"value": 42})

    async def test_task_identity_is_scoped_and_reset(self):
        seen = {}

        class Identity(BaseAgent):
            async def execute(self, request):
                current = runtime_context.current()
                seen["user"] = current.user_id
                seen["run"] = current.run_id
                return "ok"

        agent = Identity("identity")
        await agent.run_task(TaskRequest(input="x", user_id=11, run_id="run-1"))
        self.assertEqual(seen, {"user": 11, "run": "run-1"})
        self.assertIsNone(runtime_context.current())

    async def test_error_is_normalised_and_hook_runs(self):
        errors = []

        class Broken(BaseAgent):
            async def on_error(self, request, error):
                errors.append(str(error))

            async def execute(self, request):
                raise ValueError("boom")

        agent = Broken("broken")
        result = await agent.run_task(TaskRequest(input="x"))
        self.assertFalse(result.ok)
        self.assertIn("ValueError: boom", result.error)
        self.assertEqual(errors, ["boom"])
        self.assertEqual(agent.state.value, "failed")

    async def test_missing_execute_is_rejected_at_initialise(self):
        class Incomplete(BaseAgent):
            pass

        with self.assertRaises(NotImplementedError):
            await Incomplete("incomplete").initialize()

    async def test_can_handle_supports_wildcard_and_custom_filter(self):
        class Custom(BaseAgent):
            async def accepts(self, event):
                return event.get("data", {}).get("ok") is True

        agent = Custom("custom")
        agent._subscribed_events = ["*"]
        self.assertTrue(await agent.can_handle({"type": "anything", "data": {"ok": True}}))
        agent._subscribed_events = ["sensor.state"]
        self.assertTrue(await agent.can_handle({"type": "sensor.state", "data": {"ok": True}}))
        self.assertFalse(await agent.can_handle({"type": "sensor.state", "data": {"ok": False}}))
        self.assertFalse(await agent.can_handle({"type": "other", "data": {"ok": True}}))


class ToolboxTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self):
        return _Runtime([
            _Tool("sandbox", ["read", "write", "execute"]),
            _Tool("rag_search", ["read"]),
            _Tool("mcp_server.database_query", ["read", "execute"], provider="mcp_server"),
        ])

    def test_policy_allow_deny_pinned(self):
        policy = ToolPolicy.from_config({
            "tools": {"allow": ["sandbox", "mcp_server.*"],
                      "deny": ["web"], "pinned": ["sandbox"]}})
        self.assertTrue(policy.allows("sandbox"))
        self.assertTrue(policy.allows("mcp_server.database_query"))
        self.assertFalse(policy.allows("rag_search"))
        self.assertTrue(policy.is_pinned("sandbox"))

    def test_empty_allow_means_every_tool(self):
        policy = ToolPolicy.from_config({"tools": {"allow": []}})
        self.assertTrue(policy.allows("anything"))

    def test_toolbox_discovers_and_selects(self):
        toolbox = Toolbox(self.runtime(), ToolPolicy.from_config({
            "tools": {"allow": [], "pinned": ["sandbox"]}}))
        self.assertEqual(set(toolbox.names),
                         {"sandbox", "rag_search", "mcp_server.database_query"})
        self.assertEqual(toolbox.pinned, ["sandbox"])
        selected = toolbox.select("query the database", limit=2)
        self.assertTrue(selected)
        self.assertIn("sandbox", [spec["name"] for spec in toolbox.select("x", limit=8)])

    async def test_toolbox_passes_the_right_permission_action(self):
        runtime = self.runtime()
        toolbox = Toolbox(runtime)
        await toolbox.call("agent-1", "rag_search", q="x")
        await toolbox.call("agent-1", "sandbox", operation="read")
        self.assertEqual(runtime.tool_calls[0][1], "read")
        self.assertEqual(runtime.tool_calls[1][1], "execute")


class HelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_tool_injects_identity_for_local_tools_only(self):
        runtime = _Runtime([_Tool("rag_search", ["read"]),
                            _Tool("mcp_server.database_query", ["read", "execute"])])
        agent = BaseAgent("helper", runtime=runtime)

        async def task():
            await agent.call_tool("rag_search", q="x")
            await agent.call_tool("mcp_server.database_query", q="y")

        token = runtime_context.current_request.set(
            TaskRequest(input="x", user_id=9, device_id="dev-1"))
        try:
            await task()
        finally:
            runtime_context.current_request.reset(token)

        local = runtime.tool_calls[0]
        mcp = runtime.tool_calls[1]
        self.assertEqual(local[2]["user_id"], 9)
        self.assertEqual(local[2]["device_id"], "dev-1")
        self.assertNotIn("user_id", mcp[2])

    async def test_respond_includes_task_identity(self):
        runtime = _Runtime()
        agent = BaseAgent("responder", runtime=runtime)
        token = runtime_context.current_request.set(
            TaskRequest(input="x", user_id=4, run_id="run-4",
                        conversation_id="conv-4"))
        try:
            await agent.respond(response="hello")
        finally:
            runtime_context.current_request.reset(token)
        sender, event_type, data = runtime.messages[0]
        self.assertEqual(sender, agent.agent_id)
        self.assertEqual(event_type, "agent.response")
        self.assertEqual(data["response"], "hello")
        self.assertEqual(data["user_id"], 4)
        self.assertEqual(data["run_id"], "run-4")
        self.assertEqual(data["conversation_id"], "conv-4")

    async def test_describe_and_health(self):
        runtime = _Runtime([_Tool("sandbox", ["read", "write", "execute"])])
        agent = BaseAgent("inspect", runtime=runtime)
        described = agent.describe()
        self.assertEqual(described["name"], "inspect")
        self.assertEqual(described["tools"]["names"], ["sandbox"])
        self.assertFalse(agent.health()["initialised"])


if __name__ == "__main__":
    unittest.main()
