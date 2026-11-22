"""Read-only runtime inspection tools."""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from typing import Union

from pydantic import Field

from ...contract import BaseTool, StrictModel, ToolContext, ToolError, ToolSideEffects

_READ_ONLY_COMMANDS = {
    "cat", "date", "df", "du", "env", "find", "free", "git", "head",
    "id", "ls", "ps", "pwd", "stat", "tail", "uname", "uptime", "whoami", "wc",
}
_SHELL_OPERATORS = {";", "&&", "||", "|", ">", ">>", "<", "$(", "`", "&"}
_MAX_OUTPUT = 12000


class RuntimeRunInput(StrictModel):
    command: Union[str, list[str]] = Field(
        description="A read-only command string or an argv list."
    )
    timeout_seconds: int = Field(default=15, ge=1, le=60)


class RuntimeRunOutput(StrictModel):
    ok: bool
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool = False


class RuntimeRunTool(BaseTool):
    namespace = "runtime"
    name = "run"
    title = "Run a read-only system command"
    description = (
        "Run one approved read-only command without a shell, pipes, redirects "
        "or command chaining."
    )
    when_to_use = (
        "Use for system state: disk usage, processes, uptime, git status, "
        "file metadata and similar read-only inspection."
    )
    when_not_to_use = (
        "Do not use for writes, installs, builds, long-running services or "
        "anything needing shell operators. Use the sandbox or workspace tools."
    )
    category = "runtime"
    tags = ("runtime", "shell", "system", "disk", "process", "git", "read-only")
    side_effects = ToolSideEffects.execute
    idempotent = False
    timeout_seconds = 65
    input_model = RuntimeRunInput
    output_model = RuntimeRunOutput

    async def run(self, params: RuntimeRunInput, context: ToolContext) -> RuntimeRunOutput:
        command = params.command
        raw = command if isinstance(command, str) else " ".join(command)
        try:
            args = shlex.split(command) if isinstance(command, str) else list(command)
        except ValueError as exc:
            raise ToolError("invalid_command", f"Could not parse command: {exc}") from exc
        if not args or any(not isinstance(arg, str) or not arg for arg in args):
            raise ToolError("invalid_command", "command must contain at least one argument.")
        if any(op in raw for op in (";", "&&", "||", "|", ">", "<", "$(", "`")) or any(
            marker in raw for marker in ("$(", ")", "`", "\n", "\r")
        ) or any(token in _SHELL_OPERATORS for token in args):
            raise ToolError(
                "unsafe_command",
                "Shell operators, substitutions and command chaining are not allowed.",
            )
        executable = os.path.basename(args[0])
        if executable not in _READ_ONLY_COMMANDS:
            raise ToolError(
                "command_not_allowed",
                f"Command '{executable}' is not approved.",
                next_steps=["Use one of: " + ", ".join(sorted(_READ_ONLY_COMMANDS))],
            )
        if executable == "git" and (
            len(args) < 2
            or args[1] not in {"branch", "diff", "log", "show", "status", "rev-parse"}
        ):
            raise ToolError("unsafe_command", "Only read-only git subcommands are allowed.")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                args,
                cwd=context.workspace_root or os.getcwd(),
                env={"PATH": os.environ.get("PATH", "")},
                shell=False,
                capture_output=True,
                text=True,
                timeout=params.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(
                "timeout", f"Command timed out after {params.timeout_seconds}s.",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ToolError("command_failed", str(exc)) from exc
        return RuntimeRunOutput(
            ok=result.returncode == 0,
            command=args,
            exit_code=result.returncode,
            stdout=result.stdout[:_MAX_OUTPUT],
            stderr=result.stderr[:_MAX_OUTPUT],
            truncated=len(result.stdout) > _MAX_OUTPUT or len(result.stderr) > _MAX_OUTPUT,
        )


TOOLS = [RuntimeRunTool]
