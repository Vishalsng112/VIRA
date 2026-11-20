"""Claude-style agent definitions: one markdown file per sub-agent.

    ---
    name: researcher
    description: when the main agent should delegate to this one
    tools: [web_browse]        # omit = all tools, [] = no tools
    max_steps: 5
    ---
    System prompt body...

Definitions are loaded from vira/agent/definitions/ plus any extra directory
configured via `definitions_dir` (later directories override earlier ones).
Delegation gives the sub-agent a fresh, small context, which is what makes
this pattern work well with small local models.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

BUILTIN_DIR = Path(__file__).parent / "definitions"
_REGISTERED: Dict[str, AgentDefinition] = {}
_OWNERS: Dict[str, str] = {}
_VERSION = 0


def definitions_version() -> int:
    return _VERSION


@dataclass
class AgentDefinition:
    name: str
    description: str
    prompt: str
    tools: Optional[List[str]] = None  # None = inherit all
    max_steps: int = 5
    model: Optional[str] = None
    temperature: Optional[float] = None
    version: str = "1.0.0"
    source: str = field(default="", repr=False)


def parse_definition(text: str, source: str = "") -> Optional[AgentDefinition]:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    name, description = meta.get("name"), meta.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        return None
    tools = meta.get("tools")
    if tools is not None and not isinstance(tools, list):
        tools = [t.strip() for t in str(tools).split(",") if t.strip()]
    try:
        max_steps = max(1, min(int(meta.get("max_steps", 5)), 12))
    except (TypeError, ValueError):
        max_steps = 5
    temperature = meta.get("temperature")
    return AgentDefinition(
        name=name.strip(), description=" ".join(description.split()),
        prompt=parts[2].strip(), tools=tools, max_steps=max_steps,
        model=meta.get("model"),
        temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
        version=str(meta.get("version", "1.0.0")),
        source=source,
    )


def register_definition(definition: AgentDefinition, owner: str = "") -> None:
    """Register a runtime (plugin-contributed) agent definition."""
    global _VERSION
    _VERSION += 1
    _REGISTERED[definition.name] = definition
    if owner:
        _OWNERS[definition.name] = owner


def unregister_definitions(owner: str) -> int:
    global _VERSION
    names = [name for name, value in _OWNERS.items() if value == owner]
    if names:
        _VERSION += 1
    for name in names:
        _REGISTERED.pop(name, None)
        _OWNERS.pop(name, None)
    return len(names)


def load_definitions(extra_dirs: Iterable[str] = ()) -> Dict[str, AgentDefinition]:
    found: Dict[str, AgentDefinition] = dict(_REGISTERED)
    for directory in [BUILTIN_DIR, *(Path(d).expanduser() for d in extra_dirs if d)]:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                definition = parse_definition(path.read_text(encoding="utf-8"), str(path))
            except OSError:
                continue
            if definition:
                found[definition.name] = definition
    return found
