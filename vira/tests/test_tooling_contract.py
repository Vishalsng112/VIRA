"""Tests for the Pydantic-first tool foundation."""
import asyncio
import unittest

from vira.tooling import (
    BaseTool,
    EchoInput,
    EchoTool,
    Toolbox,
    ToolCatalog,
    ToolContext,
    ToolEnvelope,
    ToolPolicy,
    ToolRegistry,
    StrictModel,
    ToolError,
)
from vira.tooling.catalog import CatalogEntry


class _FailInput(StrictModel):
    message: str


class _FailTool(BaseTool):
    namespace = "test"
    name = "fail"
    title = "Fail"
    description = "Raise a typed tool error."
    when_to_use = "Tests."
    category = "test"
    tags = ("failure", "error")
    input_model = _FailInput
    output_model = EchoInput

    async def run(self, params: _FailInput, context: ToolContext) -> EchoInput:
        raise ToolError("expected", params.message, retryable=True)


class ToolContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_input_and_output_round_trip(self):
        envelope = await EchoTool().invoke({"text": "hello"}, ToolContext())
        self.assertTrue(envelope.ok)
        self.assertEqual(envelope.data.text, "hello")
        self.assertIsNone(envelope.error)

    async def test_invalid_arguments_are_structured(self):
        envelope = await EchoTool().invoke({"text": "x", "extra": 1})
        self.assertFalse(envelope.ok)
        self.assertEqual(envelope.error.code, "invalid_arguments")
        self.assertTrue(envelope.error.details["errors"])

    async def test_tool_errors_are_structured(self):
        envelope = await _FailTool().invoke({"message": "nope"})
        self.assertFalse(envelope.ok)
        self.assertEqual(envelope.error.code, "expected")
        self.assertTrue(envelope.error.retryable)

    def test_pydantic_models_generate_mcp_schemas(self):
        tool = EchoTool.as_mcp_tool()
        self.assertEqual(tool.name, "echo")
        self.assertIn("text", tool.inputSchema["properties"])
        self.assertIn("EchoOutput", tool.outputSchema["$defs"])
        self.assertIn("data", tool.outputSchema["properties"])


class MetaToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_toolbox_meta_tools(self):
        registry = ToolRegistry([EchoTool, _FailTool])
        toolbox = Toolbox(registry, ToolPolicy(allow=["example.*", "test.*"]))
        search_cls, describe_cls = toolbox.meta_tools()
        search = await search_cls().invoke({"query": "echo"})
        self.assertTrue(search.ok)
        self.assertEqual(search.data.entries[0].qualified_name, "example.echo")
        described = await describe_cls().invoke({"name": "example.echo"})
        self.assertTrue(described.ok)
        self.assertEqual(described.data.entry.name, "example.echo")


class CatalogTests(unittest.TestCase):
    def test_duck_typed_tools_are_catalogued_with_their_registry_name(self):
        class Duck:
            name = "search"
            description = "Search a remote service."
            server_name = "external"
            input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}
            permissions = ["read"]

        registry = ToolRegistry()
        registry.register(Duck(), qualified_name="external.search")
        metadata = registry.metadata()
        self.assertEqual(metadata[0]["name"], "external.search")
        self.assertEqual(metadata[0]["provider"], "external")
        self.assertEqual(registry.catalog.search("remote")[0].qualified_name, "external.search")

    def test_search_uses_when_to_use_and_tags(self):
        catalog = ToolCatalog([EchoTool, _FailTool])
        self.assertEqual(catalog.search("echo")[0].qualified_name, "example.echo")
        self.assertEqual(catalog.search("failure")[0].qualified_name, "test.fail")
        self.assertEqual(catalog.search("nothing-matches")[0].qualified_name is not None, True)

    def test_select_puts_required_tools_first(self):
        catalog = ToolCatalog([EchoTool, _FailTool])
        selected = catalog.select(
            "echo", limit=2, required=["test.fail"], allowed=["test.fail", "example.echo"]
        )
        self.assertEqual(selected[0]["name"], "test.fail")

    def test_policy_allow_deny_and_pinned(self):
        policy = ToolPolicy(allow=["web.*", "workspace.*"], deny=["web.browse"], pinned=["workspace.read_file"])
        self.assertTrue(policy.allows("web.search"))
        self.assertFalse(policy.allows("web.browse"))
        self.assertTrue(policy.is_pinned("workspace.read_file"))
        self.assertEqual(
            policy.visible(["web.search", "web.browse", "database.query"]),
            ["web.search"],
        )

    def test_toolbox_raises_for_unknown_tool(self):
        registry = ToolRegistry([EchoTool])
        envelope = asyncio.run(Toolbox(registry).invoke("missing.tool", {}))
        self.assertFalse(envelope.ok)
        self.assertEqual(envelope.error.code, "not_found")
