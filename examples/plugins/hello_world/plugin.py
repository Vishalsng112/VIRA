"""Reference VIRA plugin using the Pydantic-first tool contract."""
from fastapi import APIRouter
from pydantic import Field

from vira.plugins.api import Plugin
from vira.tooling import BaseTool, StrictModel, ToolContext


class WordCountInput(StrictModel):
    text: str = Field(min_length=0, max_length=20000)


class WordCountOutput(StrictModel):
    text: str


class WordCountTool(BaseTool):
    namespace = "example"
    name = "word_count"
    title = "Count words"
    description = "Count words and characters in a short piece of text."
    when_to_use = "Use for deterministic word or character counts."
    when_not_to_use = "Do not use for semantic analysis."
    category = "utility"
    tags = ("text", "count", "words", "characters")
    input_model = WordCountInput
    output_model = WordCountOutput

    async def run(self, params: WordCountInput, context: ToolContext) -> WordCountOutput:
        words = params.text.split()
        return WordCountOutput(
            text=f"words={len(words)} characters={len(params.text)}")


class HelloWorldPlugin(Plugin):
    async def setup(self, ctx):
        self.ctx = ctx
        ctx.register_tool(WordCountTool())
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
        pass

    async def stop(self):
        pass
