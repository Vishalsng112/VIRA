"""Per-agent tool policy using explicit allow/deny/pinned globs."""
from __future__ import annotations

from fnmatch import fnmatch
from typing import Optional, Sequence

from pydantic import Field

from .contract import StrictModel


class ToolPolicy(StrictModel):
    allow: Optional[list[str]] = None
    deny: list[str] = Field(default_factory=list)
    pinned: list[str] = Field(default_factory=list)
    actions: Optional[list[str]] = None

    @classmethod
    def from_config(cls, config: dict | None = None) -> "ToolPolicy":
        config = config or {}
        raw = config.get("tools")
        if isinstance(raw, dict):
            allow = raw.get("allow")
            deny = raw.get("deny")
            pinned = raw.get("pinned")
        elif isinstance(raw, (list, tuple)):
            allow, deny, pinned = raw, None, None
        else:
            allow = config.get("allowed_tools")
            deny = config.get("denied_tools")
            pinned = config.get("pinned_tools")
        return cls(
            allow=[str(item) for item in allow] if isinstance(allow, (list, tuple)) and allow else None,
            deny=[str(item) for item in deny] if isinstance(deny, (list, tuple)) else [],
            pinned=[str(item) for item in pinned] if isinstance(pinned, (list, tuple)) else [],
        )

    @staticmethod
    def _matches(name: str, patterns: Sequence[str]) -> bool:
        short = name.split(".")[-1]
        return any(fnmatch(name, pattern) or fnmatch(short, pattern) for pattern in patterns)

    def allows(self, name: str) -> bool:
        if self._matches(name, self.deny):
            return False
        if self.allow is None:
            return True
        return self._matches(name, self.allow)

    def is_pinned(self, name: str) -> bool:
        return self._matches(name, self.pinned)

    def visible(self, names: Sequence[str]) -> list[str]:
        return [name for name in names if self.allows(name)]
