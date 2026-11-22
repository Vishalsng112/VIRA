"""Claude-style agent loop built for small local models.

think -> call ONE tool -> observe -> repeat -> answer, with:
  * tolerant tool-call parsing (see toolcalls.py)
  * errors fed back as observations so the model can fix its own call
  * repeated-call and unknown-tool guards, a hard step budget, a forced final answer
  * context compaction (old observations shrink, history is trimmed to a char
    budget) so 4k-8k context models do not overflow
"""
import asyncio
import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import time

from vira.agent.toolcalls import (
    clip,
    extract_tool_call,
    extract_tool_calls,
    render_tool,
    split_reasoning,
)
from vira.tooling.catalog import ToolCatalog
from vira.tooling import context as tool_context

try:
    from loguru import logger
except ImportError:  # keeps the module importable in minimal environments
    import logging
    logger = logging.getLogger(__name__)

ExtraTool = Callable[[Dict[str, Any]], Awaitable[str]]
ProgressCallback = Callable[[Dict[str, Any]], None]


def _preview_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Short, JSON-safe copy of tool params for display."""
    return {str(k): clip(v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False), 300)
            for k, v in list(params.items())[:8]}


@dataclass
class LoopConfig:
    max_steps: int = 6
    max_tool_chars: int = 6000       # one observation, as shown to the model
    old_obs_chars: int = 300         # observations older than the last two
    max_prompt_chars: int = 16000    # ~4k tokens; keep below your model's num_ctx
    tool_timeout: float = 90.0
    tool_timeouts: Dict[str, float] = field(default_factory=dict)  # per-tool overrides
    max_total_tool_chars: int = 30000  # one run's whole observation budget
    max_seconds: float = 240.0         # wall-clock budget for the tool loop
    llm_timeout: float = 300.0         # per LLM call; retried once


@dataclass
class Step:
    kind: str                        # tool | unknown_tool | repeat
    tool: str
    params: Dict[str, Any]
    observation: str
    ok: bool = True


@dataclass
class LoopResult:
    text: str
    steps: List[Step] = field(default_factory=list)
    stopped: str = "final"           # final | max_steps | error

    @property
    def tool_calls(self) -> int:
        return sum(1 for s in self.steps if s.kind == "tool")


def llm_text(response: Any) -> str:
    if hasattr(response, "text"):
        return response.text or ""
    if isinstance(response, dict) and "text" in response:
        return response["text"] or ""
    return str(response)


def tool_result_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if content:
        return " ".join(getattr(item, "text", str(item)) for item in content)
    return str(result)


class AgentLoop:
    def __init__(
        self,
        runtime,
        agent_id: str,
        system_prompt: str,
        tools: List[Dict[str, Any]],
        config: Optional[LoopConfig] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        extra_tools: Optional[Dict[str, ExtraTool]] = None,
        extra_specs: Optional[List[Dict[str, Any]]] = None,
        on_event: Optional[ProgressCallback] = None,
        source: Optional[str] = None,
        catalog: Optional[ToolCatalog] = None,
        resolve_specs: Optional[List[Dict[str, Any]]] = None,
    ):
        self.on_event = on_event
        self.source = source  # e.g. a sub-agent name, shown next to its events
        self._tool_seq = 0
        self.runtime = runtime
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.cfg = config or LoopConfig()
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        self.extra_tools = extra_tools or {}
        self.catalog = catalog
        self.specs = list(tools) + list(extra_specs or [])
        self.tool_names: List[str] = []
        self._props: Dict[str, set] = {}
        # Any permitted tool may be called by name even when it was not in the
        # small prompt selection; the loop resolves its schema on demand.
        self._known_specs: Dict[str, Dict[str, Any]] = {
            spec["name"]: spec for spec in [*self.specs, *(resolve_specs or [])]
            if spec.get("name")
        }
        self.known_names: List[str] = list(self._known_specs)
        if catalog is not None:
            self._add_spec({
                "name": "tool_search",
                "description": (
                    "Search available tools by task, app or domain (for example "
                    "photoshop, davinci resolve, video, web, files, insights). "
                    "Call this when the needed tool is not listed, then use a returned tool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            })
        self.tool_names = [t["name"] for t in self.specs if t.get("name")]
        for name in self.tool_names:
            self._known_specs.setdefault(name, next(
                t for t in self.specs if t.get("name") == name))
        self.known_names = list(self._known_specs)
        self._props = {
            t["name"]: set((t.get("parameters") or {}).get("properties", {}) or {})
            for t in self.specs if t.get("name")
        }

    def _add_spec(self, spec: Dict[str, Any]) -> None:
        name = spec.get("name")
        if not name:
            return
        self.specs = [item for item in self.specs if item.get("name") != name]
        self.specs.append(spec)
        if name not in self.tool_names:
            self.tool_names.append(name)
        self._known_specs[name] = spec
        if name not in self.known_names:
            self.known_names.append(name)
        self._props[name] = set((spec.get("parameters") or {}).get("properties", {}) or {})

    # ---- prompt -----------------------------------------------------------
    def _header(self, lessons: List[str]) -> str:
        lines = [f"System: {self.system_prompt}", f"Today is {datetime.now():%A, %d %B %Y}."]
        if self.specs:
            lines += [
                "",
                "To use a tool, reply with ONLY this JSON (one call per reply):",
                '{"tool": "<name>", "params": {"<arg>": <value>}}',
                "When you have enough information, reply in plain text with no JSON: that is your final answer.",
                "Rules: never invent tool results; call a tool only if it is needed; if a tool returns an ERROR, "
                "fix the params or try a different approach; never repeat an identical call.",
                "",
                "Tools:",
                *[render_tool(t) for t in self.specs],
            ]
            if self.catalog is not None:
                lines.append(
                    "If a needed tool is not listed, call tool_search with a task/app query first."
                )
        else:
            lines.append("\nNo tools are available. Answer in plain text.")
        if lessons:
            lines += ["", "Lessons learned from earlier runs (apply when relevant):"]
            lines += [f"- {clip(l, 300)}" for l in lessons]
        return "\n".join(lines)

    def _history_block(self, history: List[Dict], budget: int) -> str:
        kept: List[str] = []
        used = 0
        for entry in reversed(history or []):  # newest first, drop the oldest
            line = f"{str(entry.get('role', 'user')).capitalize()}: {clip(entry.get('content', ''), 1500)}"
            if used + len(line) > budget:
                break
            kept.append(line)
            used += len(line) + 1
        return "\n".join(reversed(kept))

    def _scratch(self, steps: List[Step]) -> str:
        out = []
        for i, s in enumerate(steps):
            recent = i >= len(steps) - 2
            obs = clip(s.observation, self.cfg.max_tool_chars if recent else self.cfg.old_obs_chars)
            if s.kind == "nudge":
                out.append(f"System: {s.observation}")
                continue
            call = json.dumps({"tool": s.tool, "params": s.params}, ensure_ascii=False, default=str)
            out.append(f"Assistant: {clip(call, 600)}\nObservation ({s.tool}): {obs}")
        return "\n".join(out)

    def _prompt(self, user_message: str, history, lessons, steps, force_final: bool) -> str:
        header = self._header(lessons)
        scratch = self._scratch(steps)
        tail = f"User: {user_message}"
        budget = max(self.cfg.max_prompt_chars - len(header) - len(scratch) - len(tail) - 400, 0)
        parts = [header, self._history_block(history, budget), tail, scratch]
        if force_final:
            parts.append("System: Step limit reached. Do NOT call tools. Write the final answer now "
                         "using the observations above; say what is unknown.")
        parts.append("Assistant:")
        return "\n".join(p for p in parts if p)

    # ---- progress ---------------------------------------------------------
    def _emit(self, type_: str, **fields: Any) -> None:
        if not self.on_event:
            return
        event = {"type": type_, "ts": time.time(), **fields}
        if self.source:
            event["agent"] = self.source
        try:
            self.on_event(event)
        except Exception as exc:  # progress must never break the run
            logger.debug(f"progress callback failed: {exc}")

    # ---- execution --------------------------------------------------------
    async def _generate(self, prompt: str) -> str:
        last_error: Optional[BaseException] = None
        for attempt in range(2):
            try:
                resp = await asyncio.wait_for(
                    self.runtime.call_llm(
                        agent_id=self.agent_id, prompt=prompt, model=self.model,
                        temperature=self.temperature, max_tokens=self.max_tokens,
                        user_id=getattr(self, "_user_id", None),
                        organization_id=getattr(self, "_organization_id", None),
                    ),
                    timeout=max(10.0, float(self.cfg.llm_timeout)),
                )
                text = llm_text(resp)
                if text.strip():
                    return text
                last_error = RuntimeError("the model returned an empty response")
            except asyncio.TimeoutError as exc:
                last_error = exc
            if attempt == 0:
                self._emit("check", level="warn",
                           text="The model did not answer in time; retrying once.")
        if isinstance(last_error, asyncio.TimeoutError):
            raise TimeoutError(
                f"model did not answer within {self.cfg.llm_timeout:.0f}s")
        raise RuntimeError(str(last_error or "the model returned no answer"))

    @staticmethod
    def _looks_like_tool_call(text: str) -> bool:
        value = text or ""
        return (('"tool"' in value or "'tool'" in value)
                and ('"params"' in value or '"arguments"' in value
                     or "'params'" in value or "'arguments'" in value))

    async def _run_tool(self, name: str, params: Dict[str, Any], user_id,
                        device_id=None) -> Step:
        # Reserved framework arguments must never come from the model.
        params = {k: v for k, v in params.items()
                  if k not in {"user_id", "tool_name", "required_action"}}
        # A permitted but not preselected tool: add its schema now so MCP
        # argument filtering and later prompts both see it.
        if name not in self.tool_names and name in self._known_specs:
            self._add_spec(self._known_specs[name])
        ident = {"user_id": user_id}  # local tools read it; MCP tools must not receive it
        if device_id:
            ident["device_id"] = device_id
        if name.startswith("database."):
            # The database MCP server needs the authenticated caller for
            # {{caller_user_id}} substitution and admin checks. Inject it only
            # into tools whose schema declares it, and always override any
            # value the model may have supplied.
            props = self._props.get(name) or set()
            if "vira_caller_user_id" in props:
                params = dict(params)
                params["vira_caller_user_id"] = user_id
        if "." in name:  # MCP tools: send only declared arguments, never framework ids
            props = self._props.get(name)
            if props:
                dropped = [k for k in params if k not in props]
                params = {k: v for k, v in params.items() if k in props}
                if dropped:
                    logger.info(f"[tool] {name}: dropped undeclared params {dropped}")
            ident = {}
        self._tool_seq += 1
        call_id = f"{self.source or 'main'}-{self._tool_seq}"
        started = time.monotonic()
        self._emit("tool_start", id=call_id, tool=name, params=_preview_params(params))
        user_token = tool_context.caller_user_id.set(user_id)
        org_token = tool_context.organization_id.set(
            getattr(self, "_organization_id", None))
        run_token = tool_context.run_id.set(getattr(self, "_run_id", None))
        workspace_token = tool_context.workspace.set(
            getattr(self, "_workspace", None))
        try:
            step = await self._run_tool_inner(name, params, ident, user_id)
        finally:
            tool_context.caller_user_id.reset(user_token)
            tool_context.organization_id.reset(org_token)
            tool_context.run_id.reset(run_token)
            tool_context.workspace.reset(workspace_token)
        self._emit("tool_end", id=call_id, tool=name, ok=step.ok,
                   ms=int((time.monotonic() - started) * 1000), preview=clip(step.observation, 700))
        return step

    def _tool_timeout(self, name: str) -> float:
        short = name.split(".")[-1]
        value = self.cfg.tool_timeouts.get(name)
        if value is None:
            value = self.cfg.tool_timeouts.get(short)
        try:
            return max(1.0, float(value)) if value is not None else self.cfg.tool_timeout
        except (TypeError, ValueError):
            return self.cfg.tool_timeout

    async def _run_tool_inner(self, name: str, params: Dict[str, Any], ident: Dict[str, Any], user_id) -> Step:
        try:
            if name == "tool_search" and self.catalog is not None:
                query = str(params.get("query", "")).strip()
                try:
                    limit = int(params.get("limit", 8))
                except (TypeError, ValueError):
                    limit = 8
                matches = self.catalog.search(query, limit=limit)
                for spec in matches:
                    self._add_spec(spec.as_dict())
                text = json.dumps([
                    {"name": spec.name, "description": spec.description,
                     "category": spec.category, "tags": spec.tags}
                    for spec in matches
                ], ensure_ascii=False)
                return Step("tool", name, params, text, ok=True)
            if name in self.extra_tools:
                coro = self.extra_tools[name](params)
            else:
                coro = self.runtime.use_tool(self.agent_id, name, **ident, **params)
            raw = await asyncio.wait_for(coro, timeout=self._tool_timeout(name))
            text = tool_result_text(raw)
            failed = bool(getattr(raw, "isError", False))
            logger.info(f"[tool] {name} {clip(json.dumps(params, default=str), 200)} -> "
                        f"{'ERROR' if failed else 'ok'}: {clip(text, 300)}")
            return Step("tool", name, params, ("ERROR: " if failed else "") + text, ok=not failed)
        except asyncio.TimeoutError:
            return Step("tool", name, params, f"ERROR: timed out after {self._tool_timeout(name):.0f}s", ok=False)
        except Exception as exc:  # fed back so the model can correct itself
            logger.warning(f"[{self.agent_id}] tool {name} failed: {exc}")
            return Step("tool", name, params, f"ERROR: {type(exc).__name__}: {exc}", ok=False)

    async def run(self, user_message: str, history: Optional[List[Dict]] = None,
                  lessons: Optional[List[str]] = None, user_id=None,
                  device_id=None, organization_id=None,
                  run_id=None, workspace=None) -> LoopResult:
        self._user_id = user_id
        self._organization_id = organization_id
        self._run_id = run_id
        self._workspace = workspace
        steps: List[Step] = []
        seen = set()
        nudged = False
        lessons = lessons or []
        started = time.monotonic()
        total_tool_chars = 0
        budget_exhausted = False
        for n in range(self.cfg.max_steps):
            spent = time.monotonic() - started
            if spent > self.cfg.max_seconds or total_tool_chars > self.cfg.max_total_tool_chars:
                budget_exhausted = True
                self._emit("check", level="warn",
                           text="Tool budget reached; writing the best answer from what I found.")
                break
            last = n == self.cfg.max_steps - 1
            self._emit("status", label="Writing the final answer" if last else "Thinking", step=n + 1)
            raw_text = (await self._generate(self._prompt(user_message, history, lessons, steps, last))).strip()
            calls = extract_tool_calls(raw_text, self.known_names) if self.specs else []
            parts = split_reasoning(raw_text, has_call=bool(calls))
            if parts["thought"]:
                self._emit("thought", text=clip(parts["thought"], 1500))
            if not calls:
                # A truncated or malformed tool call must never be returned as
                # the final answer (common with large write_many payloads).
                if self._looks_like_tool_call(raw_text):
                    self._emit("check", level="warn",
                               text="The tool call was invalid or truncated; retrying with a smaller one.")
                    steps.append(Step(
                        "invalid_tool_call", "system", {},
                        "ERROR: your tool call was not valid, complete JSON, so it "
                        "was not executed. This usually means the payload was too "
                        "large. Retry with a smaller call: write one file per call.",
                        ok=False))
                    continue
                text = parts["answer"] or raw_text
                last_tool = next((step for step in reversed(steps)
                                  if step.kind == "tool"), None)
                verification = {"build", "test", "analyze", "verify"}
                if (last_tool is not None and not last_tool.ok
                        and (last_tool.params or {}).get("operation") in verification
                        and not last and not nudged):
                    nudged = True
                    self._emit("check", level="warn",
                               text=f"The last {last_tool.tool} verification failed; retrying instead of reporting success.")
                    steps.append(Step(
                        "nudge", last_tool.tool, last_tool.params,
                        f"The last {last_tool.tool} operation failed. Fix the reported "
                        "problem, rerun it, and only then write the final answer. "
                        "Do not claim success while verification is failing.",
                        ok=False))
                    continue
                if (self.specs and steps and not last and not nudged
                        and not any(x.kind == "tool" and x.ok for x in steps)):
                    nudged = True  # one retry before accepting "I could not do it"
                    self._emit("check", level="warn",
                               text="No tool has succeeded yet, so I'm trying again instead of giving up.")
                    steps.append(Step("nudge", "system", {}, "No tool call has succeeded yet. Do not give up: "
                                      "try different params or another tool (for web questions call web.search, "
                                      "then open a URL from its results).", ok=False))
                    continue
                return LoopResult(text=text, steps=steps, stopped="final")
            if len(calls) > 1:
                self._emit("check", level="warn",
                           text=f"Processed {len(calls)} tool calls from one reply; send one per reply next time.")
            for call in calls:
                name, params = call["tool"], call["params"]
                if call["unknown"]:
                    self._emit("check", level="warn", text=f"'{name}' is not an available tool; choosing a valid one.")
                    steps.append(Step("unknown_tool", name, params,
                                      f"ERROR: '{name}' is not a tool. Valid tools: "
                                      f"{', '.join(self.known_names[:30])}", ok=False))
                    continue
                sig = (name, json.dumps(params, sort_keys=True, default=str))
                if sig in seen:
                    self._emit("check", level="warn", text=f"Skipped a repeated call to {name}; changing approach.")
                    steps.append(Step("repeat", name, params,
                                      "ERROR: identical call already made. If its result was an error, change the "
                                      "params/URL or use a different tool (for web questions: web.search first); "
                                      "otherwise use that result.", ok=False))
                    continue
                seen.add(sig)
                step = await self._run_tool(name, params, user_id, device_id)
                steps.append(step)
                total_tool_chars += len(step.observation)
        # budget exhausted while still calling tools: one last forced answer
        self._emit("check", level="warn",
                   text="Step limit reached; writing the best answer from what I found.")
        text = (await self._generate(self._prompt(user_message, history, lessons, steps, True))).strip()
        if not extract_tool_call(text, self.known_names):
            text = split_reasoning(text)["answer"] or text
        if extract_tool_call(text, self.known_names):
            good = [s for s in steps if s.kind == "tool" and s.ok]
            text = ("I ran out of steps before finishing. Last result: " + clip(good[-1].observation, 800)) if good \
                else "I could not complete this: the tools I tried did not return usable results."
        return LoopResult(text=text, steps=steps,
                          stopped="budget" if budget_exhausted else "max_steps")
