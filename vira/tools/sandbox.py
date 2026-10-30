import json
import shlex
from typing import Any

from vira.sandbox import SandboxManager
from .base import BaseTool, ToolPermission, text_result


OPERATIONS = ["write", "read", "list", "execute", "install", "create", "archive", "restore", "delete"]
# Names models commonly guess; mapped to the real operation instead of failing.
ALIASES = {"run": "execute", "exec": "execute", "shell": "execute", "bash": "execute",
           "save": "write", "write_file": "write", "create_file": "write",
           "read_file": "read", "cat": "read", "ls": "list", "list_files": "list"}


class SandboxTool(BaseTool):
    def __init__(self, manager: SandboxManager):
        super().__init__(
            name="sandbox",
            description=(
                "Isolated workspace for writing and running code. Operations: "
                "write(path, content) saves a file; execute(command) runs a command, e.g. "
                "command='python3 max.py'; read(path); list(); install(packages). "
                "Typical flow: write the file, then execute it. Files and the sandbox are "
                "reused automatically within a conversation, so sandbox_id is optional."
            ),
            permissions=ToolPermission(actions=["execute"]),
            input_schema={"type": "object", "properties": {
                "operation": {"type": "string", "enum": OPERATIONS},
                "sandbox_id": {"type": "string"},
                "path": {"type": "string", "description": "file path inside the workspace, e.g. max.py"},
                "content": {"type": "string", "description": "file text for write"},
                "command": {"anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]},
                "packages": {"type": "array", "items": {"type": "string"}},
                "archive_path": {"type": "string"}, "run_id": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            }, "required": ["operation"]},
        )
        self.manager = manager
        self._current: dict = {}  # (agent_id, user_id) -> sandbox_id

    async def _sandbox_id(self, agent_id: str, kwargs: dict) -> str:
        """Explicit id, else this user's current sandbox, else a fresh one."""
        explicit = kwargs.get("sandbox_id")
        key = (agent_id, kwargs.get("user_id"))
        if explicit:
            self._current[key] = explicit
            return explicit
        current = self._current.get(key)
        if current:
            try:
                await self.manager.get(current, agent_id)
                return current
            except Exception:
                self._current.pop(key, None)
        created = await self.manager.create(agent_id, kwargs.get("run_id"))
        self._current[key] = created["sandbox_id"]
        return created["sandbox_id"]

    @staticmethod
    def _normalize_command(command: Any, use_venv: bool) -> list[str]:
        if isinstance(command, str):
            normalized = shlex.split(command)
        elif isinstance(command, list):
            if len(command) == 1 and " " in command[0]:
                normalized = shlex.split(command[0])
            else:
                normalized = command
        else:
            raise ValueError("command must be a command string or an argument list")
        if not normalized or any(not isinstance(part, str) or not part for part in normalized):
            raise ValueError("command must contain at least one non-empty argument")
        if use_venv and normalized[0] in {"python", "python3"}:
            normalized[0] = "/workspace/.venv/bin/python"
        return normalized

    async def execute(self, operation: str, agent_id: str, **kwargs: Any):
        if not agent_id:
            return text_result("Sandbox operations require an agent identity", is_error=True)
        operation = ALIASES.get(str(operation).strip().lower(), str(operation).strip().lower())
        if operation in ("write", "read", "list"):
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            path = next((kwargs[k] for k in ("path", "file", "filename") if isinstance(kwargs.get(k), str)),
                        kwargs.get("command") if isinstance(kwargs.get("command"), str) else "")
            try:
                if operation == "write":
                    result = await self.manager.write_file(sandbox_id, agent_id, path, kwargs.get("content", ""))
                elif operation == "read":
                    result = await self.manager.read_file(sandbox_id, agent_id, path)
                else:
                    result = await self.manager.list_files(sandbox_id, agent_id, path)
            except (ValueError, FileNotFoundError) as exc:
                return text_result(f"{exc}", is_error=True)
            result = {**result, "sandbox_id": sandbox_id}
        elif operation == "create":
            result = await self.manager.create(agent_id, kwargs.get("run_id"))
            self._current[(agent_id, kwargs.get("user_id"))] = result["sandbox_id"]
        elif operation == "execute":
            if "command" not in kwargs:
                return text_result("execute needs 'command', e.g. command='python3 max.py'", is_error=True)
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            packages = kwargs.get("packages") or []
            if packages:
                install_result = await self.manager.install(sandbox_id, packages, agent_id)
                if install_result.get("exit_code") != 0:
                    result = {
                        **install_result,
                        "sandbox_id": sandbox_id,
                        "workspace": (await self.manager.get(sandbox_id, agent_id))["workspace"],
                    }
                    return text_result(json.dumps(result, default=str), is_error=True)
            command = self._normalize_command(kwargs["command"], bool(packages))
            result = await self.manager.execute(
                sandbox_id, command, agent_id,
                kwargs.get("timeout_seconds"),
            )
            result = {
                **result,
                "sandbox_id": sandbox_id,
                "workspace": (await self.manager.get(sandbox_id, agent_id))["workspace"],
            }
        elif operation == "install":
            sandbox_id = await self._sandbox_id(agent_id, kwargs)
            result = await self.manager.install(
                sandbox_id, kwargs["packages"], agent_id,
            )
            result = {
                **result,
                "sandbox_id": sandbox_id,
                "workspace": (await self.manager.get(sandbox_id, agent_id))["workspace"],
            }
        elif operation == "archive":
            result = {"archive_path": await self.manager.archive(kwargs["sandbox_id"], agent_id)}
        elif operation == "restore":
            result = await self.manager.restore(kwargs["archive_path"], agent_id, kwargs.get("run_id"))
        elif operation == "delete":
            await self.manager.delete(kwargs["sandbox_id"], agent_id)
            result = {"deleted": True}
        else:
            return text_result(
                f"Unsupported sandbox operation: {operation}. Valid operations: {', '.join(OPERATIONS)}. "
                "To save a file use operation='write' with path and content; to run it use "
                "operation='execute' with command='python3 <file>'.", is_error=True)
        return text_result(json.dumps(result, default=str))
