"""Small-model-tolerant parsing helpers for the agent loop.

Local LLMs often wrap JSON in prose or code fences, use single quotes, add
trailing commas or pick a different key name.  Everything here is pure Python
so it can be unit-tested without the rest of VIRA.
"""
import ast
import json
import re
from typing import Any, Dict, Iterator, List, Optional

_NAME_KEYS = ("tool", "tool_name", "name", "function", "action")
_ARG_KEYS = ("params", "arguments", "args", "parameters", "input")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _balanced_objects(text: str) -> Iterator[str]:
    """Yield every top-level {...} substring (string-aware)."""
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth > 0:
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]
                start = None


def loads_lenient(raw: str) -> Any:
    """json.loads with the usual local-model repairs; returns None on failure."""
    for candidate in (raw, _TRAILING_COMMA.sub(r"\1", raw)):
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            pass
    try:  # python-dict style: {'tool': 'x', 'params': {...}}
        return ast.literal_eval(_TRAILING_COMMA.sub(r"\1", raw))
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """First JSON object found anywhere in text (fenced or not)."""
    for chunk in _balanced_objects(text or ""):
        obj = loads_lenient(chunk)
        if isinstance(obj, dict):
            return obj
    return None


def _resolve(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fn = obj.get("function")
    if isinstance(fn, dict):  # OpenAI style {"function": {"name":..,"arguments":..}}
        obj = {"tool": fn.get("name"), "params": fn.get("arguments", {})}
    name = next((obj[k] for k in _NAME_KEYS if isinstance(obj.get(k), str)), None)
    if not name:
        return None
    key = next((k for k in _ARG_KEYS if k in obj), None)
    params = obj.get(key, {}) if key else {}
    if isinstance(params, str):
        params = loads_lenient(params) or {}
    if not isinstance(params, dict):
        params = {}
    return {"tool": name.strip(), "params": params, "explicit": "tool" in obj and key is not None}


def resolve_name(name: str, known: List[str]) -> str:
    """Map 'web_browse' to 'mcp_server.web_browse' when that match is unique."""
    if name in known:
        return name
    matches = [k for k in known if k.split(".")[-1] == name]
    return matches[0] if len(matches) == 1 else name


def extract_tool_call(text: str, known: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Return {"tool", "params", "unknown"} for the first tool call in text.

    A candidate counts when its name is a known tool, or when it is explicitly
    shaped like {"tool": ..., "params": ...} (then flagged unknown=True so the
    loop can tell the model which tools really exist).
    """
    known_set = set(known or [])
    fallback = None
    for chunk in _balanced_objects(text or ""):
        obj = loads_lenient(chunk)
        if not isinstance(obj, dict):
            continue
        call = _resolve(obj)
        if not call:
            continue
        call["tool"] = resolve_name(call["tool"], list(known_set))
        if call["tool"] in known_set:
            return {"tool": call["tool"], "params": call["params"], "unknown": False}
        if call["explicit"] and fallback is None:
            fallback = {"tool": call["tool"], "params": call["params"], "unknown": True}
    return fallback


def clip(text: Any, limit: int) -> str:
    """Shorten to ~limit chars keeping head and tail (errors are often last)."""
    text = text if isinstance(text, str) else str(text)
    if limit <= 0 or len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = max(limit - head, 0)
    omitted = len(text) - head - tail
    return f"{text[:head]}\n...[{omitted} chars omitted]...\n{text[len(text) - tail:]}" if tail else text[:head]


def trim(text: str, limit: int) -> str:
    """Head-only truncation (for descriptions, where the start matters)."""
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def render_tool(tool: Dict[str, Any]) -> str:
    """One compact line per tool: name(arg: type, opt?: type) - description."""
    schema = tool.get("parameters") or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
    args = []
    for pname, spec in (props or {}).items():
        ptype = spec.get("type", "any") if isinstance(spec, dict) else "any"
        if isinstance(spec, dict) and isinstance(spec.get("enum"), list) and spec["enum"]:
            ptype = "|".join(str(v) for v in spec["enum"])
        args.append(f"{pname}{'' if pname in required else '?'}: {ptype}")
    desc = " ".join(str(tool.get("description") or "").split())
    return f"- {tool.get('name', 'unknown')}({', '.join(args)}) - {trim(desc, 500)}"


_THINK = re.compile(r"<(think|thinking|reasoning)>(.*?)(?:</\1>|\Z)", re.S | re.I)
_FENCE = re.compile(r"```[a-zA-Z]*")


def split_reasoning(text: str, has_call: bool = False) -> Dict[str, str]:
    """Separate a model reply into {"thought", "answer"}.

    * <think>...</think> blocks (reasoning models) are the thought.
    * When the reply is a tool call, any prose before the JSON is the thought
      (the call itself is shown separately by the UI).
    * Otherwise the remaining text is the final answer, free of think tags.
    """
    text = text or ""
    thoughts = [m.group(2).strip() for m in _THINK.finditer(text)]
    rest = _THINK.sub("", text).strip()
    if has_call:
        brace = rest.find("{")
        prose = _FENCE.sub("", rest[:brace] if brace >= 0 else rest).strip()
        if prose:
            thoughts.append(prose)
        rest = ""
    return {"thought": "\n\n".join(t for t in thoughts if t), "answer": rest}
