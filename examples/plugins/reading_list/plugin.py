"""Example VIRA plugin: a private reading list.

Demonstrates the complete plugin surface used by the SDK examples:

* a read-only tool and a write tool;
* an authenticated HTTP route (the host authenticates before mounting);
* namespaced persisted state;
* a prompt-defined specialist that can only use this plugin's tools.

Copy the directory into ``plugins.directories`` and reload plugins.
"""
from fastapi import APIRouter

from vira.agent.definitions import AgentDefinition
from vira.plugins.api import Plugin
from vira.tools.base import BaseTool, ToolPermission, text_result


def _items(ctx) -> list:
    value = ctx.get_state("items", [])
    return value if isinstance(value, list) else []


class ReadingListTool(BaseTool):
    def __init__(self, ctx):
        super().__init__(
            name="reading_list",
            description="List the user's private reading list entries.",
            permissions=ToolPermission(actions=["read"]),
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        )
        self.ctx = ctx

    async def execute(self, limit: int = 20, **kwargs):
        items = _items(self.ctx)
        limit = max(1, min(int(limit or 20), 100))
        if not items:
            return text_result("The reading list is empty.")
        lines = [
            f"{index + 1}. {entry.get('title', 'Untitled')}"
            + (f" — {entry['url']}" if entry.get("url") else "")
            for index, entry in enumerate(items[:limit])
        ]
        return text_result("\n".join(lines))


class ReadingAddTool(BaseTool):
    def __init__(self, ctx):
        super().__init__(
            name="reading_add",
            description="Add a title and optional URL to the user's private reading list.",
            permissions=ToolPermission(actions=["write"]),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["title"],
            },
        )
        self.ctx = ctx

    async def execute(self, title: str = "", url: str = "", **kwargs):
        title = " ".join(str(title).split())[:300]
        if not title:
            return text_result("title is required", is_error=True)
        items = _items(self.ctx)
        max_items = int(self.ctx.config.get("max_items", 200))
        if len(items) >= max_items:
            return text_result(
                f"The reading list is full ({max_items} entries). Remove one first.",
                is_error=True,
            )
        entry = {"title": title}
        if url:
            entry["url"] = str(url)[:2000]
        items.append(entry)
        self.ctx.set_state("items", items)
        return text_result(f"Added '{title}' ({len(items)} total).")


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
                "You are VIRA's reading coach. Use reading_list before answering. "
                "Never invent entries. Suggest at most three next reads and explain "
                "why in one sentence each."
            ),
            tools=["reading_list"],
            max_steps=3,
            version="1.0.0",
        ))

    async def start(self):
        pass

    async def stop(self):
        pass
