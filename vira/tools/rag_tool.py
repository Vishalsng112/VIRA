"""Agent tool: search the user's local RAG documents."""
import json
from typing import Any

from vira.rag import service
from vira.tools.base import BaseTool, ToolPermission, text_result


class RagSearchTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="rag_search",
            description=(
                "Search the user's uploaded/local knowledge documents using the "
                "persistent vector index. Use for notes, docs and reference material "
                "that are not in the conversation history."
            ),
            permissions=ToolPermission(actions=["read"]),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        )

    async def execute(self, user_id: Any = None, query: str = "", limit: int = 8,
                      **kwargs) -> Any:
        try:
            numeric = int(user_id)
        except (TypeError, ValueError):
            return text_result("ERROR: authenticated user required.", is_error=True)
        results = await service.search(numeric, query, limit)
        return text_result(json.dumps([
            {
                "title": item["title"],
                "source": item["source"],
                "score": item["score"],
                "content": item["content"],
            }
            for item in results
        ], ensure_ascii=False))
