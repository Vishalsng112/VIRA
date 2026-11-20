"""Tool catalog and query-based tool selection.

The goal is to stop putting every tool in every prompt.  Tools carry a category
and tags; the agent gets a small relevant set plus a ``tool_search`` meta-tool.
A tool-search call expands the available specs for the next step.
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

_WORD = re.compile(r"[a-z0-9]{2,}")
_STOP = {
    "the", "and", "for", "with", "that", "this", "what", "how", "can", "you",
    "are", "was", "from", "have", "has", "not", "use", "tool", "tools", "get",
    "please", "into", "about", "help", "need", "want", "make", "using", "via",
}

_DOMAIN_KEYWORDS = {
    "adobe": "adobe",
    "photoshop": "adobe",
    "illustrator": "adobe",
    "premiere": "adobe",
    "aftereffects": "adobe",
    "after effects": "adobe",
    "lightroom": "adobe",
    "davinci": "davinci-resolve",
    "resolve": "davinci-resolve",
    "fusion": "davinci-resolve",
    "blender": "blender",
    "figma": "figma",
    "canva": "canva",
    "obs": "streaming",
    "ffmpeg": "media",
    "video": "media",
    "image": "media",
    "audio": "media",
    "3d": "media",
    "web": "web",
    "search": "web",
    "browse": "web",
    "research": "web",
    "file": "workspace",
    "filesystem": "workspace",
    "shell": "runtime",
    "git": "runtime",
    "insight": "insights",
    "usage": "insights",
    "focus": "insights",
    "wellbeing": "insights",
    "device": "insights",
    "health": "insights",
    "memory": "memory",
    "chat": "chat",
    "sandbox": "sandbox",
    "code": "coding",
    "python": "coding",
    "test": "coding",
}

_CATEGORY_HINTS = {
    "filesystem": "workspace",
    "shell": "runtime",
    "git": "runtime",
    "utility": "utility",
    "web": "web",
    "insights": "insights",
    "get_chat_statistics": "insights",
    "sandbox": "sandbox",
}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    category: str
    tags: List[str]
    provider: str = "local"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "tags": self.tags,
            "provider": self.provider,
        }


def _tokens(text: str) -> List[str]:
    words = [word for word in _WORD.findall((text or "").lower()) if word not in _STOP]
    expanded = list(words)
    for word in words:
        if len(word) >= 4 and word.endswith("s"):
            expanded.append(word[:-1])
    return expanded


def _infer_category(name: str, description: str) -> str:
    lower = f"{name} {description}".lower()
    for keyword, category in _CATEGORY_HINTS.items():
        if keyword in lower:
            return category
    return "general"


def _infer_tags(name: str, description: str, category: str) -> List[str]:
    lower = f"{name} {description}".lower()
    tags = {category}
    for keyword, tag in _DOMAIN_KEYWORDS.items():
        if keyword in lower:
            tags.add(tag)
    for token in _tokens(lower)[:30]:
        if len(token) >= 3:
            tags.add(token)
    return sorted(tags)


class ToolCatalog:
    def __init__(self, specs: Iterable[Dict[str, Any]]):
        self._specs: Dict[str, ToolSpec] = {}
        for raw in specs:
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            description = " ".join(str(raw.get("description") or "").split())
            category = str(raw.get("category") or "").strip() or _infer_category(name, description)
            tags = raw.get("tags")
            if not isinstance(tags, list) or not tags:
                tags = _infer_tags(name, description, category)
            self._specs[name] = ToolSpec(
                name=name,
                description=description,
                parameters=raw.get("parameters") or {},
                category=category,
                tags=[str(tag) for tag in tags],
                provider=str(raw.get("provider") or "local"),
            )

    def all(self) -> List[ToolSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def search(self, query: str, limit: int = 8,
               category: Optional[str] = None) -> List[ToolSpec]:
        query_tokens = set(_tokens(query))
        scored = []
        for spec in self._specs.values():
            if category and spec.category != category:
                continue
            haystack = (
                f"{spec.name} {spec.description} {spec.category} "
                + " ".join(spec.tags)
            ).lower()
            score = 0
            phrase = (query or "").strip().lower()
            if phrase and phrase in spec.name.lower():
                score += 20
            for tag in spec.tags:
                if tag in query_tokens:
                    score += 5
            for token in query_tokens:
                if token in spec.name.lower():
                    score += 6
                elif token in haystack:
                    score += 2
            if category and spec.category == category:
                score += 8
            if score == 0 and not query_tokens:
                score = 1 if spec.category in ("web", "insights", "workspace") else 0
            if score:
                scored.append((score, spec))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        if not scored and query_tokens:
            # Fallback: return general/web tools so the model can still act.
            scored = [
                (1, spec) for spec in self._specs.values()
                if spec.category in ("web", "workspace", "runtime", "insights")
            ][:limit]
        return [spec for _, spec in scored[:max(1, limit)]]

    def select(self, query: str, limit: int = 8,
               required: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        chosen: List[ToolSpec] = []
        seen = set()
        for name in required or []:
            spec = self._specs.get(name)
            if spec and name not in seen:
                chosen.append(spec)
                seen.add(name)
        for spec in self.search(query, limit=limit):
            if spec.name not in seen:
                chosen.append(spec)
                seen.add(spec.name)
        return [spec.as_dict() for spec in chosen[:max(1, limit)]]
