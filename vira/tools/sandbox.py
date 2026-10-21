import json
from typing import Any

from vira.sandbox import SandboxManager
from .base import BaseTool, ToolPermission, text_result


class SandboxTool(BaseTool):
    def __init__(self, manager: SandboxManager):
        super().__init__(
            name="sandbox",
            description="Create and operate an isolated Bubblewrap agent workspace.",
            permissions=ToolPermission(actions=["execute"]),
            input_schema={"type": "object", "properties": {
                "operation": {"type": "string", "enum": ["create", "execute", "install", "archive", "restore", "delete"]},
                "sandbox_id": {"type": "string"}, "command": {"type": "array", "items": {"type": "string"}},
                "packages": {"type": "array", "items": {"type": "string"}},
                "archive_path": {"type": "string"}, "run_id": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            }, "required": ["operation"]},
        )
        self.manager = manager

    async def execute(self, operation: str, agent_id: str, **kwargs: Any):
        if not agent_id:
            return text_result("Sandbox operations require an agent identity", is_error=True)
        if operation == "create":
            result = await self.manager.create(agent_id, kwargs.get("run_id"))
        elif operation == "execute":
            sandbox_id = kwargs.get("sandbox_id")
            if not sandbox_id:
                created = await self.manager.create(agent_id, kwargs.get("run_id"))
                sandbox_id = created["sandbox_id"]
            result = await self.manager.execute(
                sandbox_id, kwargs["command"], agent_id,
                kwargs.get("timeout_seconds"),
            )
            result = {
                **result,
                "sandbox_id": sandbox_id,
                "workspace": (await self.manager.get(sandbox_id, agent_id))["workspace"],
            }
        elif operation == "install":
            sandbox_id = kwargs.get("sandbox_id")
            if not sandbox_id:
                created = await self.manager.create(agent_id, kwargs.get("run_id"))
                sandbox_id = created["sandbox_id"]
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
            return text_result(f"Unsupported sandbox operation: {operation}", is_error=True)
        return text_result(json.dumps(result, default=str))
