"""Provider-neutral tools commonly needed by coding agents.

These tools intentionally expose narrow operations instead of an unrestricted
host API.  Destructive or privileged work remains the responsibility of the
existing sandbox and MCP permission policies.
"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import json
import operator
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Iterable

from mcp.types import CallToolResult

from .base import BaseTool, ToolPermission, text_result


def _json(value: Any) -> CallToolResult:
    return text_result(json.dumps(value, ensure_ascii=False, default=str))


def _error(message: str) -> CallToolResult:
    return text_result(message, is_error=True)


class FilesystemTool(BaseTool):
    """Read and modify files below an explicitly configured workspace root."""

    def __init__(self, root: str | os.PathLike[str] = "."):
        super().__init__(
            name="filesystem",
            description="Read, write, list, search, and create directories inside the workspace root.",
            permissions=ToolPermission(actions=["read", "write", "execute"]),
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["read", "write", "list", "search", "mkdir"]},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "pattern": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["operation"],
                "additionalProperties": False,
            },
        )
        self.root = Path(root).expanduser().resolve()

    def _path(self, value: str | None = "") -> Path:
        candidate = (self.root / (value or ".")).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escapes the configured workspace root") from exc
        return candidate

    async def execute(self, operation: str, path: str = "", content: str = "",
                      pattern: str = "", max_results: int = 100, **_: Any) -> CallToolResult:
        try:
            target = self._path(path)
            if operation == "read":
                if not target.is_file():
                    return _error(f"Not a file: {path or '.'}")
                return _json({"path": str(target.relative_to(self.root)), "content": target.read_text(encoding="utf-8")})
            if operation == "write":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return _json({"written": True, "path": str(target.relative_to(self.root)), "bytes": target.stat().st_size})
            if operation == "mkdir":
                target.mkdir(parents=True, exist_ok=True)
                return _json({"created": True, "path": str(target.relative_to(self.root))})
            if operation == "list":
                if not target.is_dir():
                    return _error(f"Not a directory: {path or '.'}")
                entries = sorted(
                    {"path": str(item.relative_to(self.root)), "type": "directory" if item.is_dir() else "file"}
                    for item in target.iterdir()
                )
                return _json({"entries": entries[: max(1, min(int(max_results), 1000))]})
            if operation == "search":
                if not pattern:
                    return _error("search requires 'pattern'")
                matches = []
                for item in target.rglob("*"):
                    if len(matches) >= max(1, min(int(max_results), 1000)) or not item.is_file():
                        continue
                    try:
                        resolved_item = item.resolve()
                        resolved_item.relative_to(self.root)
                        for line_no, line in enumerate(item.read_text(encoding="utf-8").splitlines(), 1):
                            if pattern in line:
                                matches.append({"path": str(item.relative_to(self.root)), "line": line_no, "text": line})
                                if len(matches) >= max_results:
                                    break
                    except (UnicodeDecodeError, OSError, ValueError):
                        continue
                return _json({"matches": matches})
            return _error(f"Unsupported filesystem operation: {operation}")
        except (OSError, UnicodeError, ValueError) as exc:
            return _error(str(exc))


_READ_ONLY_COMMANDS = {"cat", "date", "df", "du", "env", "find", "free", "git", "head",
                       "id", "ls", "ps", "pwd", "stat", "tail", "uname", "uptime", "whoami", "wc"}
_SHELL_OPERATORS = {";", "&&", "||", "|", ">", ">>", "<", "$(", "`", "&"}


class ShellTool(BaseTool):
    """Run a bounded, tokenized, read-only command in a selected directory."""

    def __init__(self, cwd: str | os.PathLike[str] = "."):
        super().__init__(
            name="shell",
            description="Run an approved read-only command without shell expansion, pipes, redirects, or chaining.",
            permissions=ToolPermission(actions=["execute"]),
            input_schema={"type": "object", "properties": {
                "command": {"type": ["string", "array"], "items": {"type": "string"}},
                "timeout_seconds": {"type": "integer"},
            }, "required": ["command"], "additionalProperties": False},
        )
        self.cwd = Path(cwd).expanduser().resolve()

    async def execute(self, command: str | list[str], timeout_seconds: int = 15, **_: Any) -> CallToolResult:
        try:
            args = shlex.split(command) if isinstance(command, str) else list(command)
            if not args or any(not isinstance(arg, str) or not arg for arg in args):
                return _error("command must contain at least one non-empty argument")
            if any(token in _SHELL_OPERATORS for token in args) or any(x in (command if isinstance(command, str) else " ")
                                                                     for x in ("$(", "`", "\n", "\r")):
                return _error("Shell operators and command chaining are not allowed")
            executable = os.path.basename(args[0])
            if executable not in _READ_ONLY_COMMANDS:
                return _error(f"Command '{executable}' is not approved")
            if executable == "git" and (len(args) < 2 or args[1] not in
                                        {"branch", "diff", "log", "show", "status", "rev-parse"}):
                return _error("Only read-only git subcommands are allowed")
            result = await asyncio.to_thread(
                subprocess.run, args, cwd=self.cwd, env={"PATH": os.environ.get("PATH", "")},
                shell=False, capture_output=True, text=True, timeout=max(1, min(int(timeout_seconds), 60)),
                check=False,
            )
            return _json({"ok": result.returncode == 0, "command": args, "exit_code": result.returncode,
                          "stdout": result.stdout[:12000], "stderr": result.stderr[:12000],
                          "truncated": len(result.stdout) > 12000 or len(result.stderr) > 12000})
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return _error(str(exc))


class GitTool(ShellTool):
    """Structured read-only Git operations for agents."""

    def __init__(self, cwd: str | os.PathLike[str] = "."):
        super().__init__(cwd)
        self.name = "git"
        self.description = "Inspect repository status, history, branches, diffs, and commits without changing Git state."

    async def execute(self, operation: str = "status", ref: str = "", **_: Any) -> CallToolResult:
        allowed = {"status": ["status", "--short"], "log": ["log", "--oneline", "-20"],
                   "diff": ["diff", "--stat"], "branches": ["branch", "--no-color"],
                   "show": ["show", "--stat", "--oneline"]}
        args = allowed.get(operation)
        if args is None:
            return _error(f"Unsupported git operation: {operation}")
        if operation == "show" and ref:
            args = args + [ref]
        return await super().execute(["git", *args])


class UtilityTool(BaseTool):
    """Small deterministic utilities that should not require an LLM or network."""

    def __init__(self):
        super().__init__(
            name="utility",
            description="Get UTC time or evaluate a safe arithmetic expression.",
            permissions=ToolPermission(actions=["read", "execute"]),
            input_schema={"type": "object", "properties": {
                "operation": {"type": "string", "enum": ["time", "calculate"]},
                "expression": {"type": "string"},
            }, "required": ["operation"], "additionalProperties": False},
        )

    async def execute(self, operation: str, expression: str = "", **_: Any) -> CallToolResult:
        if operation == "time":
            now = dt.datetime.now(dt.timezone.utc)
            return _json({"utc": now.isoformat(), "unix": now.timestamp()})
        if operation != "calculate":
            return _error(f"Unsupported utility operation: {operation}")
        try:
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree.body)
            if not isinstance(result, (int, float)) or isinstance(result, bool):
                raise ValueError("expression did not produce a number")
            return _json({"expression": expression, "result": result})
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            return _error(f"Invalid arithmetic expression: {exc}")


class WebTool(BaseTool):
    """Expose the existing SSRF-checked web implementation through the registry."""

    def __init__(self):
        super().__init__(
            name="web",
            description="Search the public web, read a public page, or research a question with source text.",
            permissions=ToolPermission(actions=["read", "execute"]),
            input_schema={"type": "object", "properties": {
                "operation": {"type": "string", "enum": ["search", "browse", "research"]},
                "query": {"type": "string"},
                "url": {"type": "string"},
                "max_results": {"type": "integer"},
                "max_chars": {"type": "integer"},
                "offset": {"type": "integer"},
                "pages": {"type": "integer"},
            }, "required": ["operation"], "additionalProperties": False},
        )

    async def execute(self, operation: str, query: str = "", url: str = "",
                      max_results: int = 8, max_chars: int = 6000, offset: int = 0,
                      pages: int = 2, **_: Any) -> CallToolResult:
        try:
            from . import webtools
            if operation == "search":
                result = await webtools.search(query, max_results)
            elif operation == "browse":
                result = await webtools.fetch_page(url, max_chars, offset)
            elif operation == "research":
                result = await webtools.research(query, pages)
            else:
                return _error(f"Unsupported web operation: {operation}")
            return text_result(result)
        except (OSError, RuntimeError, ValueError) as exc:
            return _error(str(exc))


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent is too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("only numeric arithmetic is allowed")


def create_builtin_tools(root: str | os.PathLike[str] = ".") -> Iterable[BaseTool]:
    """Return the standard local tool pack for a registry."""
    return (FilesystemTool(root), ShellTool(root), GitTool(root), UtilityTool(), WebTool())
