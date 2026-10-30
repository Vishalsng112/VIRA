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

from vira.agent.toolcalls import clip, extract_tool_call, render_tool, split_reasoning

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
        self.specs = list(tools) + list(extra_specs or [])
        self.tool_names = [t["name"] for t in self.specs if t.get("name")]
        self._props = {
            t["name"]: set((t.get("parameters") or {}).get("properties", {}) or {})
            for t in self.specs if t.get("name")
        }

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
        resp = await self.runtime.call_llm(
            agent_id=self.agent_id, prompt=prompt, model=self.model,
            temperature=self.temperature, max_tokens=self.max_tokens,
        )
        return llm_text(resp)

    async def _run_tool(self, name: str, params: Dict[str, Any], user_id) -> Step:
        params = {k: v for k, v in params.items() if k != "user_id"}
        ident = {"user_id": user_id}  # local tools read it; MCP tools must not receive it
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
        step = await self._run_tool_inner(name, params, ident, user_id)
        self._emit("tool_end", id=call_id, tool=name, ok=step.ok,
                   ms=int((time.monotonic() - started) * 1000), preview=clip(step.observation, 700))
        return step

    async def _run_tool_inner(self, name: str, params: Dict[str, Any], ident: Dict[str, Any], user_id) -> Step:
        try:
            if name in self.extra_tools:
                coro = self.extra_tools[name](params)
            else:
                coro = self.runtime.use_tool(self.agent_id, name, **ident, **params)
            raw = await asyncio.wait_for(coro, timeout=self.cfg.tool_timeout)
            text = tool_result_text(raw)
            failed = bool(getattr(raw, "isError", False))
            logger.info(f"[tool] {name} {clip(json.dumps(params, default=str), 200)} -> "
                        f"{'ERROR' if failed else 'ok'}: {clip(text, 300)}")
            return Step("tool", name, params, ("ERROR: " if failed else "") + text, ok=not failed)
        except asyncio.TimeoutError:
            return Step("tool", name, params, f"ERROR: timed out after {self.cfg.tool_timeout:.0f}s", ok=False)
        except Exception as exc:  # fed back so the model can correct itself
            logger.warning(f"[{self.agent_id}] tool {name} failed: {exc}")
            return Step("tool", name, params, f"ERROR: {type(exc).__name__}: {exc}", ok=False)

    async def run(self, user_message: str, history: Optional[List[Dict]] = None,
                  lessons: Optional[List[str]] = None, user_id=None) -> LoopResult:
        steps: List[Step] = []
        seen = set()
        nudged = False
        lessons = lessons or []
        for n in range(self.cfg.max_steps):
            last = n == self.cfg.max_steps - 1
            self._emit("status", label="Writing the final answer" if last else "Thinking", step=n + 1)
            raw_text = (await self._generate(self._prompt(user_message, history, lessons, steps, last))).strip()
            call = extract_tool_call(raw_text, self.tool_names) if self.specs else None
            parts = split_reasoning(raw_text, has_call=bool(call))
            if parts["thought"]:
                self._emit("thought", text=clip(parts["thought"], 1500))
            if not call:
                text = parts["answer"] or raw_text
                if (self.specs and steps and not last and not nudged
                        and not any(x.kind == "tool" and x.ok for x in steps)):
                    nudged = True  # one retry before accepting "I could not do it"
                    self._emit("check", level="warn",
                               text="No tool has succeeded yet, so I'm trying again instead of giving up.")
                    steps.append(Step("nudge", "system", {}, "No tool call has succeeded yet. Do not give up: "
                                      "try different params or another tool (for web questions call web_search, "
                                      "then open a URL from its results).", ok=False))
                    continue
                return LoopResult(text=text, steps=steps, stopped="final")
            name, params = call["tool"], call["params"]
            if call["unknown"]:
                self._emit("check", level="warn", text=f"'{name}' is not an available tool; choosing a valid one.")
                steps.append(Step("unknown_tool", name, params,
                                  f"ERROR: '{name}' is not a tool. Valid tools: {', '.join(self.tool_names)}", ok=False))
                continue
            sig = (name, json.dumps(params, sort_keys=True, default=str))
            if sig in seen:
                self._emit("check", level="warn", text=f"Skipped a repeated call to {name}; changing approach.")
                steps.append(Step("repeat", name, params,
                                  "ERROR: identical call already made. If its result was an error, change the "
                                  "params/URL or use a different tool (for web questions: web_search first); "
                                  "otherwise use that result.", ok=False))
                continue
            seen.add(sig)
            steps.append(await self._run_tool(name, params, user_id))
        # budget exhausted while still calling tools: one last forced answer
        self._emit("check", level="warn", text="Step limit reached; writing the best answer from what I found.")
        text = (await self._generate(self._prompt(user_message, history, lessons, steps, True))).strip()
        if not extract_tool_call(text, self.tool_names):
            text = split_reasoning(text)["answer"] or text
        if extract_tool_call(text, self.tool_names):
            good = [s for s in steps if s.kind == "tool" and s.ok]
            text = ("I ran out of steps before finishing. Last result: " + clip(good[-1].observation, 800)) if good \
                else "I could not complete this: the tools I tried did not return usable results."
        return LoopResult(text=text, steps=steps, stopped="max_steps")
