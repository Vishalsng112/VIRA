"""Reference VIRA plugin.

Copy this directory into a configured plugin directory (or add
``examples/plugins`` to ``plugins.directories``) and reload plugins.
"""
from fastapi import APIRouter

from vira.plugins.api import Plugin
from vira.tools.base import BaseTool, ToolPermission, text_result


class WordCountTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="example_word_count",
            description="Count words and characters in a short piece of text.",
            permissions=ToolPermission(actions=["read"]),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )

    async def execute(self, text: str = "", **kwargs):
        words = text.split()
        return text_result(f"words={len(words)} characters={len(text)}")


class HelloWorldPlugin(Plugin):
    async def setup(self, ctx):
        self.ctx = ctx
        ctx.register_tool(WordCountTool())
        # Every plugin router is mounted at /api/v1/ext/<plugin-id>.
        router = APIRouter()

        @router.get("/hello")
        async def hello():
            count = int(self.ctx.get_state("requests", 0)) + 1
            self.ctx.set_state("requests", count)
            return {
                "message": self.ctx.config.get("greeting", "Hello"),
                "plugin": self.ctx.id,
                "requests": count,
            }

        ctx.register_router(router)

    async def start(self):
        # Optional background work is tied to the plugin lifecycle.
        pass

    async def stop(self):
        pass
