"""ChatAgent integration: tool loop, MCP tools, permissions and responses."""
import unittest
from types import SimpleNamespace

from vira.agent.Agents.chat_agent import ChatAgent
from vira.agent.base import TaskRequest, TaskResult
from vira.tools.base import ToolPermission, text_result


class _Tool:
    def __init__(self, name, actions=("read",), description=None, provider=None):
        self.name = name
        self.description = description or f"{name} tool"
        self.permissions = ToolPermission(actions=list(actions))
        self.server_name = provider

    def get_schema(self):
        return {"type": "object", "properties": {"query": {"type": "string"}}}


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
    def __init__(self, replies, tools=None):
        self.replies = list(replies)
        self.tool_executor = _Executor(tools or [
            _Tool("rag_search"),
            _Tool("mcp_server.database_query", ("read", "execute"),
                  provider="mcp_server"),
        ])
        self.prompts = []
        self.tool_calls = []
        self.messages = []
        self.memories = []

    async def get_context(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)

    async def call_llm(self, agent_id, prompt, **kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.replies.pop(0))

    async def use_tool(self, agent_id, tool_name, required_action=None, **kwargs):
        if required_action is None:
            tool = self.tool_executor._registry.get(tool_name)
            actions = list(tool.permissions.actions) if tool else []
            required_action = next(
                (a for a in ("execute", "write", "read") if a in actions), None)
        self.tool_calls.append((tool_name, required_action, kwargs))
        return text_result("stored knowledge")

    async def memory_operation(self, agent_id, operation, **kwargs):
        if operation == "store":
            self.memories.append(kwargs)
            return "id"
        return []

    async def send_agent_message(self, sender_agent_id, event_type, data,
                                 target_agent_ids=None, exclude_sender=True):
        self.messages.append((sender_agent_id, event_type, data))


class ChatAgentTests(unittest.IsolatedAsyncioTestCase):
    def event(self, message="hello", **extra):
        data = {
            "message": message,
            "conversation_id": "conv-1",
            "user_id": 3,
            "run_id": "run-1",
            "history": [],
        }
        data.update(extra)
        return {"type": "user.message", "data": data}

    async def test_chat_runs_tool_loop_and_emits_response(self):
        runtime = _Runtime([
            '{"tool": "rag_search", "params": {"query": "deploy"}}',
            "The runbook says rotate keys.",
        ])
        agent = ChatAgent(runtime, {"delegation": False, "learn_lessons": False})

        result = await agent.handle(self.event("what is the deploy runbook?"))

        self.assertIsInstance(result, TaskResult)
        self.assertTrue(result.ok)
        self.assertIn("rotate keys", result.text)
        self.assertEqual(runtime.tool_calls[0][0], "rag_search")
        self.assertEqual(runtime.tool_calls[0][1], "read")  # not "execute"
        sender, event_type, data = runtime.messages[-1]
        self.assertEqual(event_type, "agent.response")
        self.assertEqual(data["conversation_id"], "conv-1")
        self.assertEqual(data["response"], result.text)
        self.assertEqual(data["user_id"], 3)
        self.assertEqual(data["run_id"], "run-1")

    async def test_mcp_qualified_tools_are_offered_and_called(self):
        runtime = _Runtime([
            '{"tool": "mcp_server.database_query", "params": {"query": "select 1"}}',
            "one row",
        ])
        agent = ChatAgent(runtime, {"delegation": False, "learn_lessons": False})
        result = await agent.handle(self.event("query the database"))
        self.assertIn("mcp_server.database_query",
                      [tool["name"] for tool in agent.available_tools])
        self.assertEqual(runtime.tool_calls[0][0], "mcp_server.database_query")
        self.assertEqual(result.text, "one row")

    async def test_tool_policy_restricts_tools(self):
        runtime = _Runtime(["plain answer"])
        agent = ChatAgent(runtime, {
            "delegation": False,
            "tools": {"allow": ["mcp_server.*"], "pinned": []},
        })
        self.assertEqual([tool["name"] for tool in agent.available_tools],
                         ["mcp_server.database_query"])

    async def test_history_is_used_and_remembered_per_instance(self):
        runtime = _Runtime(["first", "second"])
        agent = ChatAgent(runtime, {"delegation": False, "learn_lessons": False})
        await agent.handle(self.event("one"))
        await agent.handle(self.event("two"))

        self.assertIn("User: one", runtime.prompts[0])
        self.assertIn("User: one", runtime.prompts[1])
        self.assertIn("Assistant: first", runtime.prompts[1])
        self.assertEqual(len(agent._history_fallback[(3, "conv-1")]), 4)

        # A different instance cannot see this conversation.
        other = ChatAgent(_Runtime(["x"]), {"delegation": False,
                                            "learn_lessons": False})
        self.assertEqual(other._history_fallback, {})

    async def test_workspace_is_propagated_to_tool_context(self):
        from vira.tools import context as tool_context
        runtime = _Runtime([
            '{"tool": "rag_search", "params": {"query": "deploy"}}',
            "done",
        ])
        seen = {}

        original = runtime.use_tool

        async def capture(agent_id, tool_name, required_action=None, **kwargs):
            seen["workspace"] = tool_context.workspace.get()
            return await original(agent_id, tool_name,
                                  required_action=required_action, **kwargs)

        runtime.use_tool = capture
        agent = ChatAgent(runtime, {"delegation": False, "learn_lessons": False})
        await agent.handle(self.event("deploy?", workspace="/tmp/project-x"))
        self.assertEqual(seen["workspace"], "/tmp/project-x")

    async def test_empty_message_produces_a_response_instead_of_hanging(self):
        runtime = _Runtime([])
        agent = ChatAgent(runtime, {"delegation": False, "learn_lessons": False})
        result = await agent.handle(self.event(""))
        self.assertTrue(result.text)
        self.assertIn("couldn't complete", result.text)
        self.assertEqual(runtime.messages[-1][1], "agent.response")

    async def test_context_and_capabilities_are_exposed(self):
        agent = ChatAgent(_Runtime(["ok"]), {"delegation": False})
        self.assertEqual(agent.subscribed_events, ["user.message"])
        self.assertEqual([cap.name for cap in agent.capabilities], ["chat"])
        described = agent.describe()
        self.assertTrue(described["reentrant"])
        self.assertTrue(described["tools"]["count"] >= 2)


if __name__ == "__main__":
    unittest.main()
