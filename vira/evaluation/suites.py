"""Deterministic evaluation suites for the Phase 5 agent platform."""
from __future__ import annotations

import asyncio
import contextlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List

from vira.agent import benchmark
from vira.agent.loop import AgentLoop, LoopConfig
from vira.auth import auth, database
from vira.memory.manager import MemoryManager
from vira.security import approvals
from vira.tooling.servers.workspace.tools import WriteFileTool
from vira.tooling.catalog import ToolCatalog
from vira.tooling.executor import ToolExecutor
from vira.tooling.registry import ToolRegistry

from .harness import CaseResult, SuiteResult


@contextlib.contextmanager
def _temp_database() -> Iterator[int]:
    old_path = database.DB_PATH
    old_url = database.DATABASE_URL
    with tempfile.TemporaryDirectory() as tmp:
        database.DATABASE_URL = ""
        database.DB_PATH = Path(tmp) / "evaluation.sqlite3"
        database.init_db()
        auth.create_admin("evaluator", "evalpass1")
        try:
            yield 1
        finally:
            database.DB_PATH = old_path
            database.DATABASE_URL = old_url


def _tool_selection() -> SuiteResult:
    specs = [
        {"name": "web.search", "description": "Search the web for news, prices and current facts"},
        {"name": "web.browse", "description": "Open a URL and read the page", "tags": ["open", "url", "page", "read", "link"]},
        {"name": "vira.insights", "description": "Summarise app usage, screen time, focus and device health", "tags": ["social", "apps", "time", "screen", "usage", "activity", "device"]},
        {"name": "database.query", "description": "Run one read-only SQL query against the VIRA database"},
        {"name": "database.schema", "description": "Describe database tables and columns", "tags": ["columns", "table", "tables", "devices", "schema", "database"]},
        {"name": "vira.rag_search", "description": "Search the user's knowledge base and documents"},
        {"name": "workspace.read_file", "description": "Read files in the workspace"},
        {"name": "workspace.write_file", "description": "Write files in the workspace"},
        {"name": "runtime.run", "description": "Run an approved read-only system command"},
        {"name": "workspace.sandbox", "description": "Write files and execute Python code in an isolated workspace", "tags": ["write", "run", "script", "python", "execute", "build", "test"]},
        {"name": "vira.context", "description": "Return devices, consent, battery and health context"},
    ]
    catalog = ToolCatalog(specs)
    cases = [
        ("web_search", "search the web for today's news", "web.search"),
        ("web_browse", "open this URL and read it", "web.browse"),
        ("insights", "how much time did I spend on social apps this week", "vira.insights"),
        ("database", "count devices in the database with a read-only SQL query", "database.query"),
        ("schema", "what columns does the devices table have", "database.schema"),
        ("rag", "search my saved documents for the project deadline", "vira.rag_search"),
        ("read_file", "read a file in my workspace folder", "workspace.read_file"),
        ("write_file", "write a file in my workspace folder", "workspace.write_file"),
        ("runtime", "run a read-only system command", "runtime.run"),
        ("workspace.sandbox", "write and run a Python script to calculate primes", "workspace.sandbox"),
        ("context", "which of my devices are low on battery", "vira.context"),
    ]
    results = []
    top1 = top3 = 0
    for name, query, expected in cases:
        matches = [spec.name for spec in catalog.search(query, limit=3)]
        hit1 = bool(matches) and matches[0] == expected
        hit3 = expected in matches
        top1 += 1 if hit1 else 0
        top3 += 1 if hit3 else 0
        results.append(CaseResult(
            name, hit1,
            f"expected {expected}; got {', '.join(matches) or 'none'}",
            {"top1": hit1, "top3": hit3},
        ))
    return SuiteResult(
        "tool_selection",
        "Read-only tool routing over a representative catalogue. Primary metric: top-1 accuracy; top-3 is reported for recovery.",
        results,
    )


def _benchmark_cases(names: List[str]) -> List[CaseResult]:
    results = benchmark.run_offline()
    selected = [item for item in results if item.name in names]
    return [
        CaseResult(item.name, item.passed, item.detail,
                   {"category": item.category, "tool_calls": item.tool_calls, "steps": item.steps})
        for item in selected
    ]


def _task_completion() -> SuiteResult:
    return SuiteResult(
        "task_completion",
        "End-to-end agent-loop tasks for device, database, RAG and web questions.",
        _benchmark_cases({
            "device_question", "database_question", "rag_question", "web_failure_recovery",
        }),
    )


def _failure_recovery() -> SuiteResult:
    return SuiteResult(
        "failure_recovery",
        "Recovery from tool errors, repeated calls, malformed JSON and invented tools.",
        _benchmark_cases({
            "web_failure_recovery", "repeated_call_guard", "malformed_json",
            "unknown_tool_recovery",
        }),
    )


def _memory_retrieval() -> SuiteResult:
    with _temp_database() as user_id:
        manager = MemoryManager()

        async def scenario() -> List[CaseResult]:
            async def store(content: str, importance: float = 0.5) -> str:
                return await manager.store(
                    content, user_id=user_id, importance=importance,
                    memory_type="long_term",
                )

            photoshop = await store("I use Adobe Photoshop for photo editing", 0.7)
            await store("I enjoy cooking pasta on weekends", 0.2)
            await store("My project deadline is 12 December", 0.9)
            await store("The project budget is five thousand dollars", 0.4)
            await store("My current operating system is Windows", 0.3)
            await store("My current operating system is Linux", 0.9)
            await store("My favourite editor is Vim", 0.6)
            emacs = await store("My favourite editor is Emacs", 0.6)
            bash = await store("My preferred terminal is bash", 0.5)
            zsh = await store("My preferred terminal is zsh", 0.5)

            # Make the Emacs memory old so recency must break the tie.
            old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
            with database.transaction() as conn:
                conn.execute("UPDATE memories SET created_at = ? WHERE id = ?", (old, emacs))
            database.record_memory_feedback(bash, user_id, False, "outdated")
            database.record_memory_feedback(zsh, user_id, True, "current")

            async def top(query: str) -> List[str]:
                items = await manager.retrieve(query, user_id=user_id, limit=3)
                return [item.content for item in items]

            results = []
            photo = await top("photo editing software")
            results.append(CaseResult(
                "single_session", bool(photo) and "Photoshop" in photo[0],
                f"top: {photo[:1]}", {"precision_at_1": bool(photo) and "Photoshop" in photo[0]},
            ))
            deadline = await top("project deadline")
            results.append(CaseResult(
                "multi_session", bool(deadline) and "12 December" in deadline[0],
                f"top: {deadline[:1]}", {"precision_at_1": bool(deadline) and "12 December" in deadline[0]},
            ))
            os_items = await top("current operating system")
            results.append(CaseResult(
                "knowledge_update", bool(os_items) and "Linux" in os_items[0],
                f"top: {os_items[:2]}", {"precision_at_1": bool(os_items) and "Linux" in os_items[0]},
            ))
            editor = await top("favourite editor")
            results.append(CaseResult(
                "recency", bool(editor) and "Vim" in editor[0],
                f"top: {editor[:2]}", {"precision_at_1": bool(editor) and "Vim" in editor[0]},
            ))
            empty = await top("quantum chromodynamics gluon scattering")
            results.append(CaseResult(
                "abstention", len(empty) == 0,
                f"returned {len(empty)} unrelated memories", {"abstained": len(empty) == 0},
            ))
            terminal = await top("preferred terminal")
            results.append(CaseResult(
                "feedback", bool(terminal) and "zsh" in terminal[0],
                f"top: {terminal[:2]}", {"precision_at_1": bool(terminal) and "zsh" in terminal[0]},
            ))
            return results

        return SuiteResult(
            "memory_retrieval",
            "LongMemEval-inspired checks: single/multi-session recall, knowledge updates, recency, abstention and feedback.",
            asyncio.run(scenario()),
        )


def _destructive_guard() -> SuiteResult:
    results = []
    checks = [
        ("runtime", approvals.approval_reason("runtime.run", "execute", {}), True),
        ("workspace_write", approvals.approval_reason("workspace.write_file", "write", {"path": "x"}), True),
        ("sandbox_execute", approvals.approval_reason("workspace.sandbox", "execute", {"operation": "execute"}), True),
        ("workspace_read", approvals.approval_reason("workspace.read_file", "read", {"path": "x"}), False),
        ("database_read", approvals.approval_reason("database.query", "execute", {"sql": "SELECT 1"}), False),
    ]
    for name, reason, expected in checks:
        results.append(CaseResult(
            name, bool(reason) == expected,
            "approval required" if reason else "allowed without approval",
            {"approval_required": bool(reason)},
        ))

    with _temp_database() as user_id, tempfile.TemporaryDirectory() as workspace:
        registry = ToolRegistry()
        registry.register(WriteFileTool())

        class _AllowAll:
            def authorize(self, permission: str) -> bool:
                return True

        executor = ToolExecutor(registry, _AllowAll(), approval_config={"enabled": True})
        kwargs = {"agent_id": "eval", "caller_user_id": user_id,
                  "path": "eval.txt", "content": "ok"}
        import vira.tooling.context as tool_context
        token = tool_context.workspace.set(workspace)
        try:
            blocked = asyncio.run(executor.execute("workspace.write_file", **kwargs))
            results.append(CaseResult(
                "executor_blocks",
                blocked.isError and "APPROVAL_REQUIRED" in blocked.content[0].text,
                blocked.content[0].text[:120], {"blocked": blocked.isError},
            ))
            pending = approvals.list_requests(user_id, "pending")
            if pending:
                approvals.decide(pending[0]["id"], True, user_id)
            allowed = asyncio.run(executor.execute("workspace.write_file", **kwargs))
            results.append(CaseResult(
                "executor_after_approval", not allowed.isError,
                allowed.content[0].text[:120], {"executed": not allowed.isError},
            ))
        finally:
            tool_context.workspace.reset(token)
    return SuiteResult(
        "destructive_guard",
        "Destructive calls must stop at an approval gate and execute only after a single-use approval.",
        results,
    )


def _run_recovery() -> SuiteResult:
    results = []
    with _temp_database() as user_id:
        conversation = database.create_conversation(user_id, "Evaluation run")
        message = database.append_message(conversation, user_id, "user", "recover me")
        run_id = database.create_run(conversation, user_id, message["id"], None, "eval-corr")
        database.update_run(run_id, "running")
        recovered = database.mark_interrupted_runs()
        run = database.get_run(run_id, user_id)
        results.append(CaseResult(
            "interrupted_marked_failed",
            recovered >= 1 and run and run["status"] == "failed",
            f"status={run['status'] if run else 'missing'}; recovered={recovered}",
            {"recovered": recovered},
        ))
        listed = database.list_runs(user_id, "failed")
        results.append(CaseResult(
            "failed_run_listed", any(item["id"] == run_id for item in listed),
            f"{len(listed)} failed run(s)", {"listed": len(listed)},
        ))
        from vira.agent_runtime import run_store
        run_store.append(run_id, "tool_end", {
            "tool": "filesystem",
            "params": {"token": "supersecret"},
            "preview": "Bearer abcdefghijklmnop",
        })
        timeline = run_store.timeline(run_id)
        serialized = str(timeline)
        results.append(CaseResult(
            "timeline_redacted",
            bool(timeline) and "supersecret" not in serialized and "abcdefghijklmnop" not in serialized,
            f"{len(timeline)} event(s) redacted", {"events": len(timeline)},
        ))
    return SuiteResult(
        "run_recovery",
        "Interrupted runs are marked failed and visible, and the stored timeline is redacted.",
        results,
    )


SUITES: List[Callable[[], SuiteResult]] = [
    _tool_selection,
    _task_completion,
    _memory_retrieval,
    _failure_recovery,
    _destructive_guard,
    _run_recovery,
]
