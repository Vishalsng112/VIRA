"""Domain MCP server manifests."""
from __future__ import annotations

from pydantic import Field

from .contract import StrictModel


class ServerManifest(StrictModel):
    id: str
    title: str
    description: str
    version: str = "1.0.0"
    instructions: str = ""
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
