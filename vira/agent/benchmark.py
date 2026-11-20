"""Deterministic, dependency-free tool-use benchmark scenarios.

The scenarios exercise the agent loop rather than a particular model: scripted
replies stand in for an LLM, and scripted tools stand in for the device,
database, RAG and web backends. This makes the benchmark reproducible in CI and
lets ``scripts/benchmark.py`` compare loop behaviour across releases. The same
script also supports live runs against a real model.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from vira.agent.loop import AgentLoop, LoopConfig


def _spec(name: str, description: str, props: Optional[Dict[str, Any]] = None,
          required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": props or {},
            "required": required or [],
        },
    }


TOOLS = [
    _spec("insights", "Summarize device usage, focus and wellbeing.",
          {"days": {"type": "integer"}}),
    _spec("database_query.database_query", "Run one read-only SELECT against the VIRA database.",
          {"sql": {"type": "string"}}, ["sql"]),
    _spec("rag_search", "Search the user's knowledge base and documents.",
          {"query": {"type": "string"}}, ["query"]),
    _spec("mcp_server.web_search", "Search the web for current information.",
          {"query": {"type": "string"}}, ["query"]),
    _spec("mcp_server.web_browse", "Open a URL and read its text.",
          {"url": {"type": "string"}}, ["url"]),
]


class ScriptedRuntime:
    """Minimal AgentRuntime stand-in: replies and tools are pre-scripted."""

    def __init__(self, replies: List[str],
                 tool: Optional[Callable[[str, Dict[str, Any]], str]] = None):
        self.replies = list(replies)
        self.tool = tool or (lambda name, params: "ok")
        self.calls: List[tuple] = []
        self.prompts: List[str] = []

    async def call_llm(self, agent_id: str, prompt: str, **kwargs):
        self.prompts.append(prompt)
        if not self.replies:
            raise RuntimeError("scripted replies exhausted")
        return SimpleNamespace(text=self.replies.pop(0))

    async def use_tool(self, agent_id: str, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return self.tool(name, kwargs)


@dataclass
class ScenarioResult:
    name: str
    category: str
    passed: bool
    detail: str
    tool_calls: List[str] = field(default_factory=list)
    steps: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "passed": self.passed,
            "detail": self.detail,
            "tool_calls": self.tool_calls,
            "steps": self.steps,
        }


def _run_loop(replies: List[str], tool=None) -> "tuple[Any, ScriptedRuntime]":
    runtime = ScriptedRuntime(replies, tool)
    loop = AgentLoop(runtime, "benchmark", "You are a benchmark agent.", TOOLS,
                     LoopConfig(max_steps=6))
    result = asyncio.run(loop.run("benchmark question", user_id=1))
    return result, runtime


def _result(name: str, category: str, passed: bool, detail: str,
            runtime: ScriptedRuntime, result: Any) -> ScenarioResult:
    return ScenarioResult(
        name=name,
        category=category,
        passed=passed,
        detail=detail,
        tool_calls=[call[0] for call in runtime.calls],
        steps=len(getattr(result, "steps", []) or []),
    )


def scenario_device_question() -> ScenarioResult:
    result, runtime = _run_loop([
        '{"tool": "insights", "params": {"days": 7}}',
        "You used 3.5 hours per day across 2 devices this week.",
    ], lambda name, params: "weekly focus: 3.5h/day across 2 devices")
    ok = ("insights" in [call[0] for call in runtime.calls]
          and "3.5 hours" in result.text)
    return _result("device_question", "device", ok,
                   "Asked for a device summary and answered from the insights tool.",
                   runtime, result)


def scenario_database_question() -> ScenarioResult:
    result, runtime = _run_loop([
        '{"tool": "database_query.database_query", "params": {"sql": "SELECT COUNT(*) AS n FROM devices"}}',
        "There are 4 devices connected to the server.",
    ], lambda name, params: '[{"n": 4}]')
    ok = ("database_query.database_query" in [call[0] for call in runtime.calls]
          and "4 devices" in result.text)
    return _result("database_question", "database", ok,
                   "Used the read-only SQL tool and answered from its row set.",
                   runtime, result)


def scenario_rag_question() -> ScenarioResult:
    result, runtime = _run_loop([
        '{"tool": "rag_search", "params": {"query": "project deadline"}}',
        "The project deadline in your notes is 12 December.",
    ], lambda name, params: "Note: project deadline is 12 December.")
    ok = ("rag_search" in [call[0] for call in runtime.calls]
          and "12 December" in result.text)
    return _result("rag_question", "rag", ok,
                   "Retrieved a note with RAG before answering.",
                   runtime, result)


def scenario_web_failure_recovery() -> ScenarioResult:
    def tool(name: str, params: Dict[str, Any]) -> str:
        if name == "mcp_server.web_search":
            raise RuntimeError("search backend timed out")
        if name == "mcp_server.web_browse" and params.get("url") == "https://example.com":
            return "Example page: today is a benchmark day."
        return "ok"

    result, runtime = _run_loop([
        '{"tool": "web_search", "params": {"query": "today"}}',
        '{"tool": "web_browse", "params": {"url": "https://example.com"}}',
        "According to example.com, today is a benchmark day.",
    ], tool)
    calls = [call[0] for call in runtime.calls]
    ok = ("mcp_server.web_search" in calls
          and "mcp_server.web_browse" in calls
          and "benchmark day" in result.text)
    return _result("web_failure_recovery", "web", ok,
                   "Recovered from a failed search by browsing a result.",
                   runtime, result)


def scenario_repeated_call() -> ScenarioResult:
    result, runtime = _run_loop([
        '{"tool": "insights", "params": {"days": 7}}',
        '{"tool": "insights", "params": {"days": 7}}',
        '{"tool": "insights", "params": {"days": 30}}',
        "Thirty-day summary: focus is stable.",
    ], lambda name, params: f"summary for {params.get('days')} days")
    calls = [call[0] for call in runtime.calls]
    # The identical second call must be blocked; the changed call is allowed.
    ok = (calls.count("insights") == 2
          and runtime.calls[-1][1].get("days") == 30
          and result.stopped == "final")
    return _result("repeated_call_guard", "robustness", ok,
                   "Blocked an identical repeat and accepted a changed call.",
                   runtime, result)


def scenario_malformed_json() -> ScenarioResult:
    result, runtime = _run_loop([
        'Sure, calling the tool:\n```json\n{"tool": "database_query.database_query", '
        '"params": {"sql": "SELECT COUNT(*) FROM devices",},}\n```',
        "There are 4 devices.",
    ], lambda name, params: '[{"COUNT(*)": 4}]')
    calls = [call[0] for call in runtime.calls]
    ok = (bool(calls) and calls[0] == "database_query.database_query"
          and result.text == "There are 4 devices.")
    return _result("malformed_json", "robustness", ok,
                   "Repaired fenced JSON with trailing commas.",
                   runtime, result)


def scenario_unknown_tool() -> ScenarioResult:
    result, runtime = _run_loop([
        '{"tool": "ghost_tool", "params": {}}',
        '{"tool": "insights", "params": {"days": 1}}',
        "Today's summary is ready.",
    ], lambda name, params: "today: 2 devices")
    kinds = [step.kind for step in result.steps]
    ok = ("unknown_tool" in kinds
          and "insights" in [call[0] for call in runtime.calls]
          and result.stopped == "final")
    return _result("unknown_tool_recovery", "robustness", ok,
                   "Rejected an invented tool and picked a real one.",
                   runtime, result)


SCENARIOS = [
    scenario_device_question,
    scenario_database_question,
    scenario_rag_question,
    scenario_web_failure_recovery,
    scenario_repeated_call,
    scenario_malformed_json,
    scenario_unknown_tool,
]


def run_offline() -> List[ScenarioResult]:
    """Run every deterministic scenario and return its result."""
    return [scenario() for scenario in SCENARIOS]


if __name__ == "__main__":
    results = run_offline()
    for item in results:
        print(f"{'PASS' if item.passed else 'FAIL'} {item.category:<12} {item.name}: {item.detail}")
    raise SystemExit(0 if all(item.passed for item in results) else 1)
