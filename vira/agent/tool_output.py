"""Helpers for reading tool results inside agent implementations."""
from typing import Any


def tool_text(value: Any) -> str:
    """Extract text from a local/MCP CallToolResult or a plain value."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        parts = []
        for item in getattr(value, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        if parts:
            return "\n".join(parts)
    if hasattr(value, "text"):
        return str(value.text or "")
    if isinstance(value, dict):
        return str(value.get("text") or value.get("result") or value)
    return str(value)


def tool_error(value: Any) -> bool:
    """True when a tool result is an error (MCP naming varies by SDK version)."""
    flag = getattr(value, "isError", None)
    if flag is None:
        flag = getattr(value, "is_error", None)
    if flag:
        return True
    text = tool_text(value).strip().lower()
    return text.startswith("error:") or "\nerror:" in text
