from pathlib import Path
from typing import Optional, Sequence

from .bubblewrap import BubblewrapBackend
from .models import SandboxPolicy


class SandboxManager:
    def __init__(self, root: str = "/AgentWorkspace", bwrap_binary: str = "bwrap",
                 default_policy: Optional[SandboxPolicy] = None):
        self.backend = BubblewrapBackend(root=root, bwrap_binary=bwrap_binary)
        self.default_policy = default_policy or SandboxPolicy()

    async def create(self, agent_id: str, run_id: Optional[str] = None, **policy) -> dict:
        sandbox = await self.backend.create(
            agent_id=agent_id, run_id=run_id,
            policy=SandboxPolicy(**{**self.default_policy.__dict__, **policy}),
        )
        return self._serialize(sandbox)

    async def execute(self, sandbox_id: str, command: Sequence[str], agent_id: str,
                      timeout_seconds: Optional[int] = None) -> dict:
        return await self.backend.execute(sandbox_id, command, agent_id, timeout_seconds)

    async def install(self, sandbox_id: str, packages: Sequence[str], agent_id: str) -> dict:
        return await self.backend.install(sandbox_id, packages, agent_id)

    async def get(self, sandbox_id: str, agent_id: str) -> dict:
        return self._serialize(self.backend.get(sandbox_id, agent_id))

    # ---- files inside the sandbox workspace ------------------------------
    MAX_WRITE_BYTES = 1_000_000
    MAX_READ_CHARS = 20_000

    def _resolve(self, sandbox_id: str, agent_id: str, path: str) -> tuple:
        workspace = self.backend.get(sandbox_id, agent_id).workspace.resolve()
        relative = str(path or "").strip()
        if relative.startswith("/workspace"):
            relative = relative[len("/workspace"):]
        relative = relative.lstrip("/")
        if not relative:
            raise ValueError("path is required, e.g. 'max.py'")
        target = (workspace / relative).resolve()  # also resolves symlinks
        if target != workspace and workspace not in target.parents:
            raise ValueError("path must stay inside the sandbox workspace")
        return workspace, target

    async def write_file(self, sandbox_id: str, agent_id: str, path: str, content: str) -> dict:
        _, target = self._resolve(sandbox_id, agent_id, path)
        data = str(content if content is not None else "").encode("utf-8")
        if len(data) > self.MAX_WRITE_BYTES:
            raise ValueError(f"content exceeds {self.MAX_WRITE_BYTES} bytes")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"path": str(target.relative_to(self.backend.get(sandbox_id, agent_id).workspace.resolve())),
                "bytes": len(data)}

    async def read_file(self, sandbox_id: str, agent_id: str, path: str) -> dict:
        _, target = self._resolve(sandbox_id, agent_id, path)
        if not target.is_file():
            raise FileNotFoundError(f"No such file in the sandbox: {path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": text[: self.MAX_READ_CHARS], "truncated": len(text) > self.MAX_READ_CHARS}

    async def list_files(self, sandbox_id: str, agent_id: str, path: str = "") -> dict:
        workspace = self.backend.get(sandbox_id, agent_id).workspace.resolve()
        base = workspace if not str(path or "").strip("/ ") else self._resolve(sandbox_id, agent_id, path)[1]
        files = sorted(
            str(item.relative_to(workspace)) for item in base.rglob("*")
            if item.is_file() and ".venv" not in item.relative_to(workspace).parts
        )
        return {"files": files[:200], "truncated": len(files) > 200}

    async def archive(self, sandbox_id: str, agent_id: str) -> str:
        return str(await self.backend.archive(sandbox_id, agent_id))

    async def restore(self, archive_path: str, agent_id: str, run_id: Optional[str] = None) -> dict:
        return self._serialize(await self.backend.restore(archive_path, agent_id, run_id))

    async def delete(self, sandbox_id: str, agent_id: str) -> None:
        await self.backend.delete(sandbox_id, agent_id)

    @staticmethod
    def _serialize(sandbox) -> dict:
        return {
            "sandbox_id": sandbox.sandbox_id, "agent_id": sandbox.agent_id,
            "run_id": sandbox.run_id, "workspace": str(sandbox.workspace),
            "status": sandbox.status.value,
        }
