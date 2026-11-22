"""Shared output types for domain tools."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from ..contract import StrictModel


class TextOutput(StrictModel):
    text: str
    truncated: bool = False
    next_cursor: Optional[str] = None


class JsonOutput(StrictModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    truncated: bool = False
    next_cursor: Optional[str] = None
