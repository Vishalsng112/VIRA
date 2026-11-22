"""Tool catalog and LLM-oriented retrieval.

Server boundaries are for isolation and ownership.  This catalog is the single
discovery surface the model sees, across every local or MCP domain.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Sequence

from pydantic import Field

from .contract import BaseTool, StrictModel, ToolMetadata

_WORD = re.compile(r"[a-z0-9]{2,}")
_STOP = {
    "the", "and", "for", "with", "that", "this", "what", "how", "can", "you",
    "are", "was", "from", "have", "has", "not", "use", "tool", "tools", "get",
    "please", "into", "about", "help", "need", "want", "make", "using", "via",
}


def _tokens(value: str) -> set[str]:
    words = {word for word in _WORD.findall((value or "").lower()) if word not in _STOP}
    expanded = set(words)
    for word in words:
        if len(word) >= 4 and word.endswith("s"):
            expanded.add(word[:-1])
    return expanded


class CatalogEntry(StrictModel):
    qualified_name: str
    namespace: str
    name: str
    title: str
    description: str
    when_to_use: str
    when_not_to_use: str = ""
    category: str
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    version: str
    side_effects: str
    idempotent: bool
    permissions: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)

    @classmethod
    def from_spec(cls, raw: dict) -> "CatalogEntry":
        name = str(raw.get("name") or "").strip()
        description = " ".join(str(raw.get("description") or "").split())
        category = str(raw.get("category") or "").strip() or "general"
        tags = raw.get("tags")
        if not isinstance(tags, list):
            tags = []
        provider = str(raw.get("provider") or "local")
        namespace = name.split(".", 1)[0] if "." in name else provider
        local = name.split(".")[-1]
        return cls(
            qualified_name=name,
            namespace=namespace,
            name=name,
            title=str(raw.get("title") or local.replace("_", " ").title()),
            description=description,
            when_to_use=str(raw.get("when_to_use") or description),
            when_not_to_use=str(raw.get("when_not_to_use") or ""),
            category=category,
            tags=[str(item) for item in tags],
            aliases=[str(item) for item in (raw.get("aliases") or [])],
            version=str(raw.get("version") or "1.0.0"),
            side_effects=str(raw.get("side_effects") or "none"),
            idempotent=bool(raw.get("idempotent", True)),
            permissions=[str(item) for item in (raw.get("permissions") or ["read"])],
            input_schema=raw.get("parameters") or raw.get("input_schema") or {},
            output_schema=raw.get("output_schema") or {},
        )

    @classmethod
    def from_tool(cls, tool: type[BaseTool], qualified_name: Optional[str] = None) -> "CatalogEntry":
        meta = tool.metadata()
        name = qualified_name or meta.qualified_name
        return cls(
            qualified_name=name,
            namespace=name.split(".", 1)[0] if "." in name else meta.namespace,
            name=name,
            title=meta.title,
            description=meta.description,
            when_to_use=meta.when_to_use,
            when_not_to_use=meta.when_not_to_use,
            category=meta.category,
            tags=meta.tags,
            aliases=meta.aliases,
            version=meta.version,
            side_effects=meta.side_effects.value,
            idempotent=meta.idempotent,
            permissions=meta.permissions.actions,
            input_schema=tool.input_schema(),
            output_schema=tool.output_schema(),
        )

    @classmethod
    def from_duck_tool(cls, tool: Any, qualified_name: Optional[str] = None) -> "CatalogEntry":
        """Build an entry for a tool that implements the registry protocol.

        External MCP tools have runtime schemas instead of static Pydantic
        models, so they cannot go through ``from_tool``.
        """
        name = qualified_name or str(getattr(tool, "name", "")).strip()
        local = name.split(".")[-1]
        namespace = name.split(".", 1)[0] if "." in name else str(
            getattr(tool, "server_name", "") or getattr(tool, "provider", "") or "external"
        )
        description = " ".join(str(getattr(tool, "description", "") or "").split())
        permissions = getattr(tool, "permissions", None)
        if isinstance(permissions, (list, tuple)):
            actions = [str(item) for item in permissions]
        elif permissions is not None:
            actions = [str(item) for item in getattr(permissions, "actions", [])]
        else:
            actions = ["read"]
        get_schema = getattr(tool, "get_schema", None)
        input_schema = (
            get_schema() if callable(get_schema)
            else getattr(tool, "input_schema", {}) or {}
        )
        output_schema = getattr(tool, "output_schema", {}) or {}
        tags = getattr(tool, "tags", ()) or ()
        aliases = getattr(tool, "aliases", ()) or ()
        side_effects = getattr(tool, "side_effects", "none")
        side_effects = getattr(side_effects, "value", side_effects)
        return cls(
            qualified_name=name,
            namespace=namespace,
            name=name,
            title=str(getattr(tool, "title", "") or local.replace("_", " ").title()),
            description=description,
            when_to_use=str(getattr(tool, "when_to_use", "") or description),
            when_not_to_use=str(getattr(tool, "when_not_to_use", "") or ""),
            category=str(getattr(tool, "category", "") or namespace),
            tags=[str(item) for item in tags],
            aliases=[str(item) for item in aliases],
            version=str(getattr(tool, "version", "1.0.0")),
            side_effects=str(side_effects),
            idempotent=bool(getattr(tool, "idempotent", True)),
            permissions=actions,
            input_schema=input_schema,
            output_schema=output_schema,
        )

    def prompt_line(self) -> str:
        return f"{self.qualified_name}: {self.title} — {self.description}"

    def as_dict(self) -> dict:
        return {
            "name": self.qualified_name,
            "description": self.description,
            "parameters": self.input_schema,
            "category": self.category,
            "tags": self.tags,
            "provider": self.namespace if "." not in self.qualified_name else self.qualified_name.split(".", 1)[0],
            "when_to_use": self.when_to_use,
            "when_not_to_use": self.when_not_to_use,
            "aliases": self.aliases,
            "permissions": self.permissions,
            "side_effects": self.side_effects,
            "idempotent": self.idempotent,
            "version": self.version,
            "output_schema": self.output_schema,
        }


class ToolCatalog:
    def __init__(self, tools: Iterable[Any] = ()) -> None:
        self._tools: dict[str, type[BaseTool]] = {}
        self._entries: dict[str, CatalogEntry] = {}
        for tool in tools:
            self.add(tool)

    def add(self, item: Any, qualified_name: Optional[str] = None) -> None:
        if isinstance(item, dict):
            entry = CatalogEntry.from_spec(item)
            self._entries[entry.qualified_name] = entry
            return
        if isinstance(item, type):
            if issubclass(item, BaseTool):
                name = qualified_name or item.qualified_name()
                self._tools[name] = item
                self._entries[name] = CatalogEntry.from_tool(item, name)
                return
            item = item()
        if isinstance(item, BaseTool):
            name = qualified_name or item.qualified_name()
            self._tools[name] = type(item)
            self._entries[name] = CatalogEntry.from_tool(type(item), name)
            return
        name = qualified_name or str(getattr(item, "name", "")).strip()
        if not name:
            raise ValueError("tool must expose a name or be registered with qualified_name")
        self._entries[name] = CatalogEntry.from_duck_tool(item, name)

    def get(self, name: str) -> Optional[CatalogEntry]:
        return self._entries.get(name)

    def tool(self, name: str) -> Optional[type[BaseTool]]:
        return self._tools.get(name)

    def all(self) -> list[CatalogEntry]:
        return list(self._entries.values())

    def names(self) -> list[str]:
        return sorted(self._entries)

    def search(
        self,
        query: str,
        limit: int = 8,
        *,
        category: Optional[str] = None,
        allowed: Optional[Sequence[str]] = None,
    ) -> list[CatalogEntry]:
        allowed_set = set(allowed) if allowed is not None else None
        query_tokens = _tokens(query)
        phrase = (query or "").strip().lower()
        scored: list[tuple[float, CatalogEntry]] = []
        for entry in self._entries.values():
            if allowed_set is not None and entry.qualified_name not in allowed_set:
                continue
            if category and entry.category != category:
                continue
            name = f"{entry.namespace} {entry.name} {entry.title}".lower()
            text = " ".join([
                entry.title, entry.description, entry.when_to_use,
                entry.when_not_to_use, entry.category,
                " ".join(entry.tags), " ".join(entry.aliases),
            ]).lower()
            score = 0.0
            if phrase and phrase in name:
                score += 30
            elif phrase and phrase in text:
                score += 14
            for tag in entry.tags + entry.aliases:
                if tag.lower() in query_tokens:
                    score += 8
            for token in query_tokens:
                if token in entry.name.lower():
                    score += 10
                elif token in entry.title.lower():
                    score += 6
                elif token in text:
                    score += 3
            if category and entry.category == category:
                score += 5
            if score:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].qualified_name))
        if not scored and query_tokens:
            scored = [
                (1.0, entry) for entry in self._entries.values()
                if allowed_set is None or entry.qualified_name in allowed_set
            ]
        return [entry for _, entry in scored[: max(1, min(int(limit), 50))]]

    def select(
        self,
        query: str,
        limit: int = 8,
        *,
        required: Optional[Sequence[str]] = None,
        allowed: Optional[Sequence[str]] = None,
    ) -> list[dict]:
        chosen: list[CatalogEntry] = []
        seen: set[str] = set()
        allowed_set = set(allowed) if allowed is not None else None
        for name in required or []:
            entry = self._entries.get(name)
            if entry and name not in seen and (allowed_set is None or name in allowed_set):
                chosen.append(entry)
                seen.add(name)
        for entry in self.search(query, limit=limit, allowed=allowed):
            if entry.qualified_name not in seen:
                chosen.append(entry)
                seen.add(entry.qualified_name)
        return [entry.as_dict() for entry in chosen[: max(1, min(int(limit), 50))]]

    def describe(self, name: str) -> Optional[CatalogEntry]:
        return self._entries.get(name)

    def prompt_summary(self, limit: int = 8, **kwargs) -> list[str]:
        return [entry.prompt_line() for entry in self.search(limit=limit, **kwargs)]
