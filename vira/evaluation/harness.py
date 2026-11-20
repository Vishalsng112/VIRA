"""Evaluation result model and Markdown/JSON rendering.

The harness is deliberately deterministic and model-free so results are
comparable across commits. Live model quality remains the job of
``scripts/benchmark.py``. Metrics follow the published agent-evaluation pattern
of reporting per-case pass/fail plus aggregate rates, and pass^k style repeat
stability is represented by running the deterministic suite twice.
"""
from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from vira import __version__


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "metrics": self.metrics,
        }


@dataclass
class SuiteResult:
    name: str
    description: str
    cases: List[CaseResult]

    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "passed": self.passed,
            "total": self.total,
            "rate": round(self.rate, 4),
            "ok": self.ok,
            "cases": [case.as_dict() for case in self.cases],
        }


@dataclass
class Report:
    suites: List[SuiteResult]
    repeat_ok: bool = True
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def total_passed(self) -> int:
        return sum(suite.passed for suite in self.suites)

    @property
    def total_cases(self) -> int:
        return sum(suite.total for suite in self.suites)

    @property
    def ok(self) -> bool:
        return bool(self.suites) and all(suite.ok for suite in self.suites) and self.repeat_ok

    def as_dict(self) -> Dict[str, Any]:
        return {
            "vira_version": __version__,
            "revision": revision(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "generated_at": self.generated_at,
            "repeat_stable": self.repeat_ok,
            "ok": self.ok,
            "summary": {
                "passed": self.total_passed,
                "total": self.total_cases,
                "rate": round(self.total_passed / self.total_cases, 4)
                if self.total_cases else 0.0,
            },
            "suites": [suite.as_dict() for suite in self.suites],
        }

    def markdown(self) -> str:
        payload = self.as_dict()
        lines = [
            "# Agent platform evaluation",
            "",
            f"Generated: {payload['generated_at']} · revision `{payload['revision']}` "
            f"· VIRA `{payload['vira_version']}` · Python {payload['python']}",
            "",
            "This report is deterministic and model-free. It is the comparable",
            "baseline for tool selection, task completion, memory retrieval, failure",
            "recovery, destructive-action guards and run recovery. Live model quality",
            "is measured separately by `scripts/benchmark.py`.",
            "",
            "## Summary",
            "",
            "| Suite | Passed | Rate | Status |",
            "|---|---|---|---|",
        ]
        for suite in self.suites:
            lines.append(
                f"| {suite.name} | {suite.passed}/{suite.total} "
                f"| {suite.rate:.0%} | {'PASS' if suite.ok else 'FAIL'} |"
            )
        lines += [
            "",
            f"Overall: **{self.total_passed}/{self.total_cases} cases passed**; "
            f"repeat stability: **{'PASS' if self.repeat_ok else 'FAIL'}**.",
            "",
        ]
        for suite in self.suites:
            lines += [f"## {suite.name}", "", suite.description, "", "| Case | Result | Detail |", "|---|---|---|"]
            for case in suite.cases:
                detail = case.detail.replace("|", "\\|")
                lines.append(f"| `{case.name}` | {'PASS' if case.passed else 'FAIL'} | {detail} |")
            lines.append("")
        lines += [
            "## Research basis",
            "",
            "The suite design follows published agent and memory evaluations:",
            "",
            "- ReAct (Yao et al., 2022) — interleaved reasoning and tool actions.",
            "- Toolformer (Schick et al., 2023) — tool selection and argument quality.",
            "- ToolBench / ToolLLM (Qin et al., 2023) — API selection and argument correctness.",
            "- AgentBench (Liu et al., 2023) — task completion across environments.",
            "- τ-bench (Yao et al., 2024) — pass^k reliability and tool-agent-user interaction.",
            "- LongMemEval (Wu et al., 2024/2025) — temporal reasoning, knowledge updates and abstention.",
            "- RAGAS (Es et al., 2023) — context precision and faithfulness for RAG answers.",
            "",
            "See `docs/dev/evaluations/research-basis.md` for the mapping.",
            "",
        ]
        return "\n".join(lines)

    def write(self, json_path: str, markdown_path: str) -> None:
        json_target = Path(json_path)
        markdown_target = Path(markdown_path)
        json_target.parent.mkdir(parents=True, exist_ok=True)
        markdown_target.parent.mkdir(parents=True, exist_ok=True)
        json_target.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        markdown_target.write_text(self.markdown() + "\n", encoding="utf-8")


def revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_all() -> Report:
    from .suites import SUITES

    suites = [suite() for suite in SUITES]
    # Run the deterministic suites twice to catch order/state leaks (pass^k).
    repeat = [suite() for suite in SUITES]
    repeat_ok = all(
        first.passed == second.passed and first.total == second.total
        for first, second in zip(suites, repeat)
    )
    return Report(suites=suites, repeat_ok=repeat_ok)
