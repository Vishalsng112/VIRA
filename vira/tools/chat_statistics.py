import json
from typing import Any

from mcp.types import CallToolResult

from vira.auth import database
from vira.tools.base import BaseTool, ToolPermission, text_result


class ChatStatisticsTool(BaseTool):
    """Read aggregate chat statistics for the authenticated user."""

    def __init__(self):
        super().__init__(
            name="get_chat_statistics",
            description=(
                "Get the authenticated user's total number of chats and messages. "
                "Use this when the user asks how many chats or messages they have."
            ),
            permissions=ToolPermission(actions=["execute"]),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

    async def execute(self, **kwargs: Any) -> CallToolResult:
        user_id = kwargs.get("user_id")
        if not isinstance(user_id, int):
            return text_result("A valid authenticated user is required.", is_error=True)
        return text_result(json.dumps(database.get_chat_statistics(user_id)))
