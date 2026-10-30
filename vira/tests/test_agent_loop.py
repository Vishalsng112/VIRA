import unittest
from types import SimpleNamespace

from vira.agent.definitions import load_definitions, parse_definition
from vira.agent.lessons import LessonStore, derive_lessons
from vira.agent.loop import AgentLoop, LoopConfig
from vira.agent.toolcalls import clip, extract_json, extract_tool_call, render_tool

TOOLS = [
    {"name": "web_browse", "description": "Fetch a URL",
     "parameters": {"properties": {"url": {"type": "string"}}, "required": ["url"]}},
]


class FakeRuntime:
    """call_llm pops scripted replies; use_tool runs a scripted function."""

    def __init__(self, replies, tool=None):
        self.replies, self.prompts, self.tool_calls, self.memories = list(replies), [], [], []
        self._tool = tool or (lambda **kw: "page text")
        self.stored = []

    async def call_llm(self, agent_id, prompt, **kw):
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.replies.pop(0))

    async def use_tool(self, agent_id, name, **kw):
        self.tool_calls.append((name, kw))
        out = self._tool(**kw)
        return out

    async def memory_operation(self, agent_id, op, **kw):
        if op == "store":
            self.stored.append(kw)
            return "id"
        return [SimpleNamespace(content=m) for m in self.memories]


class ParsingTests(unittest.TestCase):
    def test_tolerates_fences_prose_quotes_and_commas(self):
        known = ["web_browse"]
        for text in (
            '{"tool": "web_browse", "params": {"url": "https://a.b"}}',
            'Sure!\n```json\n{"tool": "web_browse", "arguments": {"url": "https://a.b"},}\n```',
            "{'tool': 'web_browse', 'params': {'url': 'https://a.b'}}",
            '{"function": {"name": "web_browse", "arguments": "{\\"url\\": \\"https://a.b\\"}"}}',
        ):
            call = extract_tool_call(text, known)
            self.assertEqual(call["tool"], "web_browse", text)
            self.assertEqual(call["params"], {"url": "https://a.b"}, text)
            self.assertFalse(call["unknown"])

    def test_plain_answers_and_unknown_tools(self):
        self.assertIsNone(extract_tool_call("The answer is 42.", ["web_browse"]))
        self.assertIsNone(extract_tool_call('{"name": "Bob", "age": 3}', ["web_browse"]))
        call = extract_tool_call('{"tool": "nope", "params": {}}', ["web_browse"])
        self.assertTrue(call["unknown"])

    def test_helpers(self):
        self.assertEqual(extract_json('x {"a": 1} y'), {"a": 1})
        self.assertLessEqual(len(clip("x" * 5000, 500)), 560)
        self.assertIn("url: string", render_tool(TOOLS[0]))


class LoopTests(unittest.IsolatedAsyncioTestCase):
    def loop(self, rt, **cfg):
        return AgentLoop(rt, "a1", "sys", TOOLS, LoopConfig(**cfg))

    async def test_multi_step_tool_use(self):
        rt = FakeRuntime(['{"tool": "web_browse", "params": {"url": "u1"}}',
                          '{"tool": "web_browse", "params": {"url": "u2"}}', "final answer"])
        res = await self.loop(rt).run("q", user_id=7)
        self.assertEqual(res.text, "final answer")
        self.assertEqual(res.tool_calls, 2)
        self.assertEqual(rt.tool_calls[0][1]["user_id"], 7)
        self.assertIn("Observation (web_browse): page text", rt.prompts[-1])

    async def test_error_is_fed_back_and_model_recovers(self):
        def tool(**kw):
            if not kw["url"].startswith("http"):
                raise ValueError("url must start with http")
            return "ok"
        rt = FakeRuntime(['{"tool": "web_browse", "params": {"url": "a.com"}}',
                          '{"tool": "web_browse", "params": {"url": "http://a.com"}}', "done"], tool)
        res = await self.loop(rt).run("q")
        self.assertIn("ERROR: ValueError: url must start with http", rt.prompts[1])
        self.assertEqual(res.text, "done")
        lessons = derive_lessons("q", res)
        self.assertEqual(len(lessons), 1)
        self.assertIn("it worked with", lessons[0])

    async def test_unknown_tool_and_repeat_guards(self):
        rt = FakeRuntime(['{"tool": "ghost", "params": {}}',
                          '{"tool": "web_browse", "params": {"url": "u"}}',
                          '{"tool": "web_browse", "params": {"url": "u"}}', "fin"])
        res = await self.loop(rt).run("q")
        self.assertEqual(len(rt.tool_calls), 1)  # the repeat was not executed
        self.assertIn("Valid tools: web_browse", rt.prompts[1])
        self.assertEqual([s.kind for s in res.steps], ["unknown_tool", "tool", "repeat"])

    async def test_step_budget_forces_final_answer(self):
        replies = [f'{{"tool": "web_browse", "params": {{"url": "u{i}"}}}}' for i in range(3)] + ["best effort"]
        rt = FakeRuntime(replies)
        res = await self.loop(rt, max_steps=3).run("q")
        self.assertEqual(res.stopped, "max_steps")
        self.assertEqual(res.text, "best effort")
        self.assertIn("Step limit reached", rt.prompts[-1])

    async def test_prompt_respects_budget(self):
        rt = FakeRuntime(["hi"])
        history = [{"role": "user", "content": "x" * 1400} for _ in range(40)]
        await self.loop(rt, max_prompt_chars=6000).run("q", history)
        self.assertLess(len(rt.prompts[0]), 6500)

    async def test_extra_tool_for_delegation(self):
        async def delegate(params):
            return "sub result " + params["task"]
        loop = AgentLoop(FakeRuntime(['{"tool": "delegate", "params": {"task": "t"}}', "ok"]), "a", "s", [],
                         extra_tools={"delegate": delegate},
                         extra_specs=[{"name": "delegate", "description": "d", "parameters": {}}])
        res = await loop.run("q")
        self.assertEqual(res.steps[0].observation, "sub result t")


class McpToolTests(unittest.IsolatedAsyncioTestCase):
    SPECS = [{"name": "mcp_server.web_browse", "description": "d",
              "parameters": {"properties": {"url": {"type": "string"}}, "required": ["url"]}}]

    async def test_short_name_resolves_and_mcp_gets_only_declared_args(self):
        rt = FakeRuntime(['{"tool": "web_browse", "params": {"url": "https://a.io", "bogus": 1}}', "done"])
        res = await AgentLoop(rt, "a", "s", self.SPECS).run("q", user_id=9)
        name, kwargs = rt.tool_calls[0]
        self.assertEqual(name, "mcp_server.web_browse")
        self.assertEqual(kwargs, {"url": "https://a.io"})  # no user_id, no undeclared params
        self.assertEqual(res.text, "done")

    async def test_local_tools_still_receive_user_id(self):
        rt = FakeRuntime(['{"tool": "web_browse", "params": {"url": "u"}}', "done"])
        await AgentLoop(rt, "a", "s", TOOLS).run("q", user_id=9)
        self.assertEqual(rt.tool_calls[0][1]["user_id"], 9)

    async def test_gives_one_nudge_before_accepting_defeat(self):
        rt = FakeRuntime(['{"tool": "web_browse", "params": {"url": "bad"}}', "I cannot do this.",
                          '{"tool": "web_browse", "params": {"url": "good"}}', "answer"],
                         lambda **kw: "ok" if kw["url"] == "good" else (_ for _ in ()).throw(RuntimeError("404")))
        res = await AgentLoop(rt, "a", "s", TOOLS).run("q")
        self.assertEqual(res.text, "answer")
        self.assertIn("Do not give up", rt.prompts[2])

    async def test_plain_chat_is_not_nudged(self):
        rt = FakeRuntime(["just text"])
        self.assertEqual((await AgentLoop(rt, "a", "s", TOOLS).run("hi")).text, "just text")


class LessonAndDefinitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_lessons_are_recalled_and_stored_once(self):
        rt = FakeRuntime(['{"tool": "web_browse", "params": {"url": "bad"}}', "sorry", "sorry again"],
                         lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        rt.memories = ["Earlier lesson"]
        store = LessonStore(rt, "a1")
        lessons = await store.recall(5, "q")
        self.assertEqual(lessons, ["Earlier lesson"])
        res = await AgentLoop(rt, "a1", "s", TOOLS).run("q", lessons=lessons, user_id=5)
        self.assertIn("Earlier lesson", rt.prompts[0])
        self.assertEqual(await store.learn(5, "c1", "q", res), 1)
        self.assertEqual(rt.stored[0]["memory_type"], "lesson")
        self.assertEqual(await store.learn(None, None, "q", res), 0)  # no user -> nothing stored

    def test_definitions(self):
        defs = load_definitions()
        self.assertIn("researcher", defs)
        self.assertEqual(defs["critic"].tools, [])
        self.assertIsNone(parse_definition("no frontmatter"))
        d = parse_definition("---\nname: x\ndescription: y\n---\nbody")
        self.assertEqual((d.name, d.tools, d.prompt), ("x", None, "body"))


if __name__ == "__main__":
    unittest.main()
