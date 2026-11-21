"""Agent-facing sandbox tool.

The tool is intentionally a thin, explicit facade over
:class:`vira.sandbox.SandboxManager`.  Agents can create a persistent execution
environment, move whole projects into it, run builds and scripts, stream long
jobs, install dependencies and archive the result.

Design rules:

* one ``operation`` selects a predictable action (no hidden fallbacks);
* every path is relative to the sandbox workspace, never the host;
* commands run inside Bubblewrap; strings use a shell for pipelines and builds;
* destructive operations still pass through VIRA's approval gate;
* the caller's current sandbox is reused automatically, per agent and user.
"""
from __future__ import annotations

import json
import shlex
from typing import Any, Dict

from vira.sandbox import SandboxManager
from vira.tools import context as tool_context
from .base import BaseTool, ToolPermission, text_result

OPERATIONS = [
    "create", "sandboxes", "info", "update", "delete",
    "write", "write_many", "read", "list", "stat", "search",
    "mkdir", "delete_file", "move", "copy",
    "execute", "install", "jobs", "job", "job_logs", "job_kill",
    "archive", "restore", "usage",
]

# Names models commonly guess; mapped to the real operation instead of failing.
ALIASES = {
    "run": "execute", "exec": "execute", "shell": "execute", "bash": "execute",
    "start": "execute", "build": "execute",
    "save": "write", "write_file": "write", "create_file": "write",
    "read_file": "read", "cat": "read",
    "ls": "list", "list_files": "list", "files": "list", "tree": "list",
    "rm": "delete_file", "remove": "delete_file", "unlink": "delete_file",
    "mv": "move", "rename": "move", "cp": "copy",
    "sandbox_list": "sandboxes", "list_sandboxes": "sandboxes",
    "stats": "usage", "quota": "usage",
    "job_status": "job", "logs": "job_logs",
    "kill": "job_kill", "cancel_job": "job_kill",
    "configure": "update", "set_policy": "update",
    "snapshot": "archive", "export": "archive", "import": "restore",
}

def _json(payload: Dict[str, Any], is_error: bool = False):
    return text_result(json.dumps(payload, default=str, ensure_ascii=False), is_error=is_error)


class SandboxTool(BaseTool):
    def __init__(self, manager: SandboxManager):
        super().__init__(
            name="sandbox",
            description=(
                "Create and use an isolated Linux execution environment for real work: "
                "write whole projects, run builds, scripts and tests, install pip/npm "
                "packages, start long-running jobs and archive results. The workspace is "
                "a user-visible project directory shared by agents; pass workspace='name' "
                "or an absolute host path to choose it, otherwise the user's default "
                "workspace is used. Paths are always relative to the workspace. "
                "Typical flow: operation='write' (or 'write_many') -> operation='execute' "
                "with command='python3 main.py' (strings run through a shell, so pipes, "
                "'&&' and multi-line scripts work) -> operation='read'/'list' the output. "
                "Use operation='execute' with background=true for servers/builds, then "
                "operation='job'/'job_logs'/'job_kill'. Install dependencies with "
                "operation='install', packages=['numpy'] (pip) or package_manager='npm'. "
                "Other operations: create, sandboxes, info, update, list, stat, search, "
                "mkdir, delete_file, move, copy, usage, archive, restore."
            ),
            permissions=ToolPermission(actions=["read", "write", "execute"]),
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": OPERATIONS,
                        "description": "Action to perform. Defaults to reusing the current sandbox.",
                    },
                    "sandbox_id": {
                        "type": "string",
                        "description": "Target sandbox. Omit to use the current sandbox for this agent/user.",
                    },
                    "name": {"type": "string", "description": "Human label for create."},
                    "workspace": {
                        "type": "string",
                        "description": (
                            "Shared project workspace: a name (e.g. 'coffee-shop') "
                            "under the workspace root, or an absolute host path "
                            "when workspace.allow_user_paths is enabled. Omit to "
                            "use the user's default workspace, which all agents share."
                        ),
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Alias for workspace when passing an absolute path.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path, e.g. 'src/main.py' or '.'.",
                    },
                    "destination": {"type": "string", "description": "Destination path for move/copy."},
                    "source": {"type": "string", "description": "Source path for move/copy."},
                    "content": {"type": "string", "description": "Text content for write."},
                    "files": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Map of path -> content for write_many.",
                    },
                    "append": {"type": "boolean", "description": "Append instead of replacing (write)."},
                    "command": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": (
                            "Command to run. A string runs through /bin/bash -lc inside the "
                            "sandbox; an array runs without a shell."
                        ),
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Packages to install (or install before execute).",
                    },
                    "package_manager": {
                        "type": "string",
                        "enum": ["auto", "pip", "npm"],
                        "description": "Dependency ecosystem for install. Defaults to auto/pip.",
                    },
                    "cwd": {"type": "string", "description": "Working directory inside the sandbox."},
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Extra environment variables for execute.",
                    },
                    "shell": {
                        "type": "boolean",
                        "description": "Set false to execute a string as an argv list with no shell.",
                    },
                    "stdin": {"type": "string", "description": "Text piped to the command's stdin."},
                    "background": {
                        "type": "boolean",
                        "description": "Start a background job and return its job_id.",
                    },
                    "job_id": {"type": "string", "description": "Background job identifier."},
                    "timeout_seconds": {"type": "integer", "description": "Command timeout (bounded by policy)."},
                    "offset": {"type": "integer", "description": "Character offset for read."},
                    "limit": {"type": "integer", "description": "Maximum chars/entries to return."},
                    "recursive": {"type": "boolean", "description": "Recurse for list; allow directories for delete_file."},
                    "overwrite": {"type": "boolean", "description": "Replace an existing destination."},
                    "pattern": {"type": "string", "description": "Text to search for (search)."},
                    "glob": {"type": "string", "description": "File glob filter for search, e.g. '*.py'."},
                    "case_sensitive": {"type": "boolean", "description": "Case-sensitive search."},
                    "max_results": {"type": "integer", "description": "Maximum results for list/search."},
                    "policy": {
                        "type": "object",
                        "description": (
                            "Policy overrides for create/update: network_enabled, "
                            "timeout_seconds, max_processes, cpu_seconds, memory_mb, "
                            "allow_package_install, allow_shell, workspace_quota_mb, "
                            "max_output_bytes."
                        ),
                    },
                    "archive_path": {"type": "string", "description": "Archive returned by operation='archive'."},
                    "include_dependencies": {
                        "type": "boolean",
                        "description": "Include .venv/node_modules in an archive (default false).",
                    },
                    "run_id": {"type": "string", "description": "Optional run correlation id."},
                },
                "required": ["operation"],
            },
        )
        self.manager = manager
        self._current: Dict[tuple, str] = {}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _identity(agent_id: str, kwargs: Dict[str, Any]) -> tuple:
        return (agent_id, kwargs.get("user_id"),
                kwargs.get("workspace") or kwargs.get("workspace_path"))

    def _owner_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if getattr(self.manager, "supports_user_ownership", False):
            user_id = kwargs.get("user_id")
            return {"user_id": user_id} if user_id is not None else {}
        return {}

    @staticmethod
    def _safe_policy(policy: Any) -> Optional[Dict[str, Any]]:
        """Strip server-only fields from a model-supplied policy."""
        if not isinstance(policy, dict):
            return None
        blocked = {"execution_mode", "extra_path", "readonly_mounts"}
        return {key: value for key, value in policy.items() if key not in blocked}

    async def _create(self, agent_id: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        policy = self._safe_policy(kwargs.get("policy"))
        user_id = kwargs.get("user_id")
        workspace = kwargs.get("workspace") or kwargs.get("workspace_path")
        if hasattr(self.manager, "find_or_create"):
            return await self.manager.find_or_create(
                agent_id,
                user_id,
                workspace=workspace,
                name=kwargs.get("name"),
                policy=policy,
            )
        if hasattr(self.manager, "create_for"):
            return await self.manager.create_for(
                agent_id,
                user_id,
                kwargs.get("run_id"),
                name=kwargs.get("name"),
                policy=policy,
                workspace=workspace,
            )
        return await self.manager.create(
            agent_id, kwargs.get("run_id"), **(policy or {}))

    async def _sandbox_id(self, agent_id: str, kwargs: Dict[str, Any]) -> str:
        """Explicit id, else this user's current sandbox, else a fresh one."""
        explicit = kwargs.get("sandbox_id")
        if isinstance(explicit, str) and explicit.strip().lower() in {
                "", "default", "current", "latest", "none", "auto"}:
            explicit = None
        key = self._identity(agent_id, kwargs)
        if explicit:
            try:
                await self.manager.get(explicit, agent_id,
                                       **self._owner_kwargs(kwargs))
            except Exception as exc:
                current = self._current.get(key)
                hint = (f" Use sandbox_id='{current}' or omit sandbox_id to reuse it."
                        if current else
                        " Omit sandbox_id (or call operation='create') to get one.")
                raise ValueError(f"Sandbox '{explicit}' does not exist.{hint}") from exc
            self._current[key] = explicit
            return explicit
        current = self._current.get(key)
        if current:
            try:
                await self.manager.get(current, agent_id, **self._owner_kwargs(kwargs))
                return current
            except Exception:
                self._current.pop(key, None)
        created = await self._create(agent_id, kwargs)
        self._current[key] = created["sandbox_id"]
        return created["sandbox_id"]

    async def _meta(self, sandbox_id: str, agent_id: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await self.manager.get(
                sandbox_id, agent_id, **self._owner_kwargs(kwargs))
        except Exception:
            return {"sandbox_id": sandbox_id}

    async def _install(self, sandbox_id: str, agent_id: str, packages: list,
                       package_manager: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if not getattr(self.manager, "supports_user_ownership", False):
            return await self.manager.install(sandbox_id, packages, agent_id)
        return await self.manager.install(
            sandbox_id, packages, agent_id,
            manager=package_manager or "auto",
            **self._owner_kwargs(kwargs))

    @staticmethod
    def _normalize_command(command: Any, use_venv: bool) -> list[str]:
        if isinstance(command, str):
            normalized = shlex.split(command)
        elif isinstance(command, list):
            if len(command) == 1 and " " in command[0]:
                normalized = shlex.split(command[0])
            else:
                normalized = list(command)
        else:
            raise ValueError("command must be a command string or an argument list")
        if not normalized or any(not isinstance(part, str) or not part for part in normalized):
            raise ValueError("command must contain at least one non-empty argument")
        if use_venv and normalized[0] in {"python", "python3"}:
            normalized[0] = "/workspace/.venv/bin/python"
        return normalized

    # ------------------------------------------------------------------ dispatch
    async def execute(self, operation: str = "", agent_id: str = "", **kwargs: Any):
        if not agent_id:
            return _json({"error": "Sandbox operations require an agent identity"}, is_error=True)
        pinned = tool_context.workspace.get()
        if pinned:
            # The workspace chosen by the user/API for this run is authoritative.
            kwargs["workspace"] = pinned
            kwargs.pop("workspace_path", None)
            kwargs.pop("workspace_id", None)
        raw = str(operation or "").strip().lower()
        operation = ALIASES.get(raw, raw)
        if operation not in OPERATIONS:
            return _json({
                "error": (
                    f"Unsupported sandbox operation: {operation}. "
                    f"Valid operations: {', '.join(OPERATIONS)}"
                ),
                "valid_operations": OPERATIONS,
                "tip": (
                    "Write a file with operation='write' (path, content), then run it with "
                    "operation='execute' (command='python3 <file>')."
                ),
            }, is_error=True)
        try:
            return await self._dispatch(operation, agent_id, kwargs)
        except (ValueError, PermissionError, FileNotFoundError, TimeoutError,
                RuntimeError, OSError) as exc:
            return _json({
                "error": str(exc),
                "operation": operation,
                "error_type": type(exc).__name__,
            }, is_error=True)

    async def _dispatch(self, operation: str, agent_id: str, kwargs: Dict[str, Any]):
        owner = self._owner_kwargs(kwargs)

        # -- sandbox lifecycle ------------------------------------------------
        if operation == "create":
            created = await self._create(agent_id, kwargs)
            self._current[self._identity(agent_id, kwargs)] = created["sandbox_id"]
            return _json({"ok": True, **created})

        if operation == "sandboxes":
            if hasattr(self.manager, "list"):
                listed = await self.manager.list(agent_id, **owner)
                return _json({"ok": True, **listed})
            return _json({"ok": True, "sandboxes": [], "count": 0})

        if operation == "info":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            meta = await self.manager.get(sandbox_id, agent_id, **owner)
            if hasattr(self.manager, "usage"):
                try:
                    meta = {**meta, "usage": await self.manager.usage(
                        sandbox_id, agent_id, **owner)}
                except Exception:
                    pass
            return _json({"ok": True, **meta})

        if operation == "update":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            policy = kwargs.get("policy")
            if not isinstance(policy, dict) or not policy:
                return _json({"error": "update requires a non-empty 'policy' object"}, is_error=True)
            if not hasattr(self.manager, "update_policy"):
                return _json({"error": "This sandbox backend cannot update policy"}, is_error=True)
            updated = await self.manager.update_policy(
                sandbox_id, agent_id, self._safe_policy(policy), **owner)
            return _json({"ok": True, **updated})

        if operation == "delete":
            explicit = kwargs.get("sandbox_id") or self._current.get(
                self._identity(agent_id, kwargs))
            if not explicit:
                return _json({"error": "delete requires sandbox_id"}, is_error=True)
            await self.manager.delete(explicit, agent_id, **owner)
            self._current.pop(self._identity(agent_id, kwargs), None)
            return _json({"ok": True, "deleted": True, "sandbox_id": explicit})

        # -- file operations --------------------------------------------------
        if operation == "write":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            path = self._path(kwargs)
            result = await self.manager.write_file(
                sandbox_id, agent_id, path,
                kwargs.get("content", ""), append=bool(kwargs.get("append")),
                **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "write_many":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            files = kwargs.get("files")
            if not isinstance(files, dict) or not files:
                return _json({"error": "write_many requires 'files' as an object of path -> content"}, is_error=True)
            result = await self.manager.write_files(
                sandbox_id, agent_id, files, **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "read":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.read_file(
                sandbox_id, agent_id, self._path(kwargs),
                offset=int(kwargs.get("offset") or 0),
                limit=kwargs.get("limit"), **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "list":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.list_files(
                sandbox_id, agent_id, kwargs.get("path", ""),
                recursive=bool(kwargs.get("recursive", True)),
                max_results=int(kwargs.get("max_results") or kwargs.get("limit") or 500),
                **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "stat":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.stat_file(
                sandbox_id, agent_id, self._path(kwargs), **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "search":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.search_files(
                sandbox_id, agent_id, str(kwargs.get("pattern") or ""),
                kwargs.get("path", ""), glob=str(kwargs.get("glob") or "*"),
                case_sensitive=bool(kwargs.get("case_sensitive")),
                max_results=int(kwargs.get("max_results") or kwargs.get("limit") or 100),
                **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "mkdir":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.make_dir(
                sandbox_id, agent_id, self._path(kwargs), **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "delete_file":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.delete_path(
                sandbox_id, agent_id, self._path(kwargs),
                recursive=bool(kwargs.get("recursive")), **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "move":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            source = kwargs.get("source") or self._path(kwargs)
            destination = kwargs.get("destination") or kwargs.get("path")
            if not destination:
                return _json({"error": "move requires 'destination'"}, is_error=True)
            result = await self.manager.move_path(
                sandbox_id, agent_id, source, destination,
                overwrite=bool(kwargs.get("overwrite")), **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation == "copy":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            source = kwargs.get("source") or self._path(kwargs)
            destination = kwargs.get("destination") or kwargs.get("path")
            if not destination:
                return _json({"error": "copy requires 'destination'"}, is_error=True)
            result = await self.manager.copy_path(
                sandbox_id, agent_id, source, destination,
                overwrite=bool(kwargs.get("overwrite")), **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        # -- execution --------------------------------------------------------
        if operation == "execute":
            return await self._execute(agent_id, kwargs)

        if operation == "install":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            packages = kwargs.get("packages")
            if not isinstance(packages, list) or not packages:
                return _json({"error": "install requires 'packages' as a list"}, is_error=True)
            package_manager = str(kwargs.get("package_manager") or "auto").lower()
            result = await self._install(
                sandbox_id, agent_id, packages, package_manager, kwargs)
            meta = await self._meta(sandbox_id, agent_id, kwargs)
            return _json({"ok": result.get("exit_code") == 0, "sandbox_id": sandbox_id,
                          "workspace": meta.get("workspace"), **result},
                         is_error=result.get("exit_code") != 0)

        # -- jobs -------------------------------------------------------------
        if operation == "jobs":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.list_jobs(sandbox_id, agent_id, **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id, **result})

        if operation in ("job", "job_logs", "job_kill"):
            job_id = kwargs.get("job_id")
            if not job_id:
                return _json({"error": f"{operation} requires 'job_id'"}, is_error=True)
            if operation == "job":
                result = await self.manager.job(job_id, agent_id, **owner)
            elif operation == "job_logs":
                result = await self.manager.job_logs(job_id, agent_id, **owner)
            else:
                result = await self.manager.kill_job(job_id, agent_id, **owner)
            return _json({"ok": True, **result})

        # -- persistence and usage -------------------------------------------
        if operation == "archive":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            archive_path = await self.manager.archive(
                sandbox_id, agent_id, **owner,
                include_dependencies=bool(kwargs.get("include_dependencies")))
            return _json({"ok": True, "sandbox_id": sandbox_id,
                          "archive_path": archive_path})

        if operation == "restore":
            archive_path = kwargs.get("archive_path")
            if not archive_path:
                return _json({"error": "restore requires 'archive_path'"}, is_error=True)
            policy = kwargs.get("policy") if isinstance(kwargs.get("policy"), dict) else None
            result = await self.manager.restore(
                archive_path, agent_id, kwargs.get("run_id"),
                user_id=kwargs.get("user_id") if owner else None,
                policy=policy, name=kwargs.get("name"))
            self._current[self._identity(agent_id, kwargs)] = result["sandbox_id"]
            return _json({"ok": True, **result})

        if operation == "usage":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            meta = await self._meta(sandbox_id, agent_id, kwargs)
            result = await self.manager.usage(sandbox_id, agent_id, **owner)
            return _json({"ok": True, "sandbox_id": sandbox_id,
                          "status": meta.get("status"), **result})

        return _json({"error": f"Unhandled sandbox operation: {operation}"}, is_error=True)

    async def _execute(self, agent_id: str, kwargs: Dict[str, Any]):
        if "command" not in kwargs:
            return _json({
                "error": "execute needs 'command', e.g. command='python3 main.py'",
                "tip": "Use a shell string for pipelines and &&, or an array for raw argv.",
            }, is_error=True)
        sandbox_id = await self._sandbox_id(agent_id, kwargs)
        packages = kwargs.get("packages") or []
        if packages and not isinstance(packages, list):
            return _json({"error": "'packages' must be a list"}, is_error=True)

        if packages:
            install_result = await self._install(
                sandbox_id, agent_id, packages, "auto", kwargs)
            if install_result.get("exit_code") != 0:
                meta = await self._meta(sandbox_id, agent_id, kwargs)
                return _json({
                    "ok": False, "stage": "install", "sandbox_id": sandbox_id,
                    "workspace": meta.get("workspace"), **install_result,
                }, is_error=True)
            command = self._normalize_command(kwargs["command"], True)
            shell = False
        else:
            command = kwargs["command"]
            shell = bool(kwargs.get("shell", isinstance(command, str)))
            if not shell:
                command = self._normalize_command(command, False)

        if kwargs.get("background"):
            if not getattr(self.manager, "supports_jobs", False):
                return _json({"error": "This sandbox backend does not support background jobs"}, is_error=True)
            job = await self.manager.start(
                sandbox_id, command, agent_id,
                shell=shell,
                cwd=kwargs.get("cwd"),
                env=kwargs.get("env"),
                stdin=kwargs.get("stdin"),
                **self._owner_kwargs(kwargs))
            meta = await self._meta(sandbox_id, agent_id, kwargs)
            return _json({"ok": True, "sandbox_id": sandbox_id,
                          "workspace": meta.get("workspace"), "job": job})

        extra: Dict[str, Any] = {}
        if shell and getattr(self.manager, "supports_user_ownership", False):
            extra["shell"] = True
        if getattr(self.manager, "supports_user_ownership", False):
            for key in ("cwd", "env", "stdin"):
                if kwargs.get(key) is not None:
                    extra[key] = kwargs[key]
            extra.update(self._owner_kwargs(kwargs))
        result = await self.manager.execute(
            sandbox_id, command, agent_id,
            kwargs.get("timeout_seconds"), **extra)
        meta = await self._meta(sandbox_id, agent_id, kwargs)
        return _json({"ok": result.get("exit_code") == 0, "sandbox_id": sandbox_id,
                      "workspace": meta.get("workspace"), **result},
                     is_error=result.get("exit_code") != 0)

    @staticmethod
    def _path(kwargs: Dict[str, Any]) -> str:
        for key in ("path", "file", "filename", "source"):
            value = kwargs.get(key)
            if isinstance(value, str) and value:
                return value
        if isinstance(kwargs.get("command"), str):
            return kwargs["command"]
        raise ValueError("path is required, e.g. path='src/main.py'")
