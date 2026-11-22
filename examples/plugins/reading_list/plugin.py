"""Example VIRA plugin: a private reading list."""
from fastapi import APIRouter
from pydantic import Field

from vira.agent.definitions import AgentDefinition
from vira.plugins.api import Plugin
from vira.tooling import BaseTool, StrictModel, ToolContext, ToolError


def _items(ctx) -> list:
    value = ctx.get_state("items", [])
    return value if isinstance(value, list) else []


class TextOut(StrictModel):
    text: str


class ListInput(StrictModel):
    limit: int = Field(default=20, ge=1, le=100)


class AddInput(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    url: str = ""


class ReadingListTool(BaseTool):
    namespace = "example"
    name = "reading_list"
    title = "Show reading list"
    description = "List the user's private reading list entries."
    when_to_use = "Use when the user asks what is on their reading list."
    when_not_to_use = "Do not use to add entries."
    category = "productivity"
    tags = ("reading", "list", "books", "articles")
    input_model = ListInput
    output_model = TextOut

    def __init__(self, ctx):
        self.ctx = ctx

    async def run(self, params: ListInput, context: ToolContext) -> TextOut:
        items = _items(self.ctx)
        if not items:
            return TextOut(text="The reading list is empty.")
        lines = [
            f"{index + 1}. {entry.get('title', 'Untitled')}"
            + (f" — {entry['url']}" if entry.get("url") else "")
            for index, entry in enumerate(items[:params.limit])
        ]
        return TextOut(text="\n".join(lines))


class ReadingAddTool(BaseTool):
    namespace = "example"
    name = "reading_add"
    title = "Add to reading list"
    description = "Add a title and optional URL to the user's private reading list."
    when_to_use = "Use when the user asks to save something to read later."
    when_not_to_use = "Do not use to edit unrelated notes."
    category = "productivity"
    tags = ("reading", "add", "bookmark", "articles")
    side_effects = "write"
    idempotent = False
    input_model = AddInput
    output_model = TextOut

    def __init__(self, ctx):
        self.ctx = ctx

    async def run(self, params: AddInput, context: ToolContext) -> TextOut:
        title = " ".join(params.title.split())[:300]
        if not title:
            raise ToolError("title_required", "title is required")
        items = _items(self.ctx)
        max_items = int(self.ctx.config.get("max_items", 200))
        if len(items) >= max_items:
            raise ToolError(
                "reading_list_full",
                f"The reading list is full ({max_items} entries). Remove one first.",
            )
        entry = {"title": title}
        if params.url:
            entry["url"] = params.url[:2000]
        items.append(entry)
        self.ctx.set_state("items", items)
        return TextOut(text=f"Added '{title}' ({len(items)} total).")


class ReadingListPlugin(Plugin):
    async def setup(self, ctx):
        self.ctx = ctx
        ctx.register_tool(ReadingListTool(ctx))
        ctx.register_tool(ReadingAddTool(ctx))

        router = APIRouter()

        @router.get("/items")
        async def items():
            return {"items": _items(ctx)}

        @router.post("/items")
        async def add_item(payload: dict):
            tool = ReadingAddTool(ctx)
            result = await tool.execute(
                title=str(payload.get("title") or ""),
                url=str(payload.get("url") or ""),
            )
            return {
                "ok": not result.isError,
                "message": result.content[0].text,
                "items": _items(ctx),
            }

        ctx.register_router(router)
        ctx.register_agent_definition(AgentDefinition(
            name="reading_coach",
            description="Use when the user asks what to read next or wants their reading list reviewed.",
            prompt=(
                "You are VIRA's reading coach. Use example.reading_list before answering. "
                "Never invent entries. Suggest at most three next reads and explain "
                "why in one sentence each."
            ),
            tools=["example.reading_list"],
            max_steps=3,
            version="1.0.0",
        ))

    async def start(self):
        pass

    async def stop(self):
        pass
