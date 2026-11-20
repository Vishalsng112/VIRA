"""Per-task caller identity for tool execution (context-local)."""
from contextvars import ContextVar
from typing import Optional

caller_user_id: ContextVar[Optional[int]] = ContextVar("vira_caller_user_id", default=None)
organization_id: ContextVar[Optional[str]] = ContextVar("vira_organization_id", default=None)
