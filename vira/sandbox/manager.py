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
