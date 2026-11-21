"""Per-task identity propagated to agent helpers and tools.

The scheduler may run many conversations concurrently.  Identity therefore lives
in context variables, never on the agent instance, so one request cannot leak
its user, organisation or run into another.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .base import TaskRequest

current_request: ContextVar[Optional["TaskRequest"]] = ContextVar(
    "vira_agent_task", default=None)


def current() -> Optional["TaskRequest"]:
    return current_request.get()
