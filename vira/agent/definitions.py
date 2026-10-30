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


@dataclass
class AgentDefinition:
    name: str
    description: str
    prompt: str
    tools: Optional[List[str]] = None  # None = inherit all
    max_steps: int = 5
    model: Optional[str] = None
    temperature: Optional[float] = None
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
        source=source,
    )


def load_definitions(extra_dirs: Iterable[str] = ()) -> Dict[str, AgentDefinition]:
    found: Dict[str, AgentDefinition] = {}
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
