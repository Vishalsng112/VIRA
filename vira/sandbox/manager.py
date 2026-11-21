"""Sandbox manager: lifecycle, file operations, jobs and safe serialization."""
from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .bubblewrap import BubblewrapBackend
from .models import SandboxPolicy, SandboxRef, SandboxStatus


class SandboxManager:
    """Public facade used by tools and API routes.

    The manager adds file operations and per-user ownership checks on top of the
    Bubblewrap backend.  It never accepts a host path: every path is resolved
    inside the sandbox workspace (or the read-only-by-convention ``artifacts``
    mount, which is not writable through this API).
    """

    # Capability flags let the tool remain compatible with lightweight test
    # doubles and alternative backends.
    supports_user_ownership = True
    supports_jobs = True
    MAX_WRITE_BYTES = 1_000_000
    MAX_TOTAL_WRITE_BYTES = 5_000_000
    MAX_READ_CHARS = 40_000
    MAX_READ_SOURCE_BYTES = 10_000_000
    MAX_LIST_RESULTS = 1_000

    def __init__(self, root: str = "/AgentWorkspace", bwrap_binary: str = "bwrap",
                 default_policy: Optional[SandboxPolicy] = None,
                 readonly_mounts: Optional[Sequence[str]] = None,
                 workspace_service=None, workspace_root: Optional[str] = None):
        self.backend = BubblewrapBackend(
            root=root, bwrap_binary=bwrap_binary,
            readonly_mounts=readonly_mounts)
        self.default_policy = default_policy or SandboxPolicy()
        self._workspace_service = workspace_service
        self._workspace_root = workspace_root

    def _workspaces(self):
        if self._workspace_service is None:
            from vira.workspace.service import WorkspaceService, get_service
            if self._workspace_root:
                self._workspace_service = WorkspaceService(
                    root=self._workspace_root)
            elif str(self.backend.root) != "/AgentWorkspace":
                # Tests and custom sandbox roots keep workspaces beside them.
                self._workspace_service = WorkspaceService(
                    root=str(self.backend.root / "workspaces"))
            else:
                self._workspace_service = get_service()
        return self._workspace_service

    # ------------------------------------------------------------------ lifecycle
    async def create(self, agent_id: str, run_id: Optional[str] = None, **policy) -> dict:
        overrides = {key: value for key, value in policy.items()
                     if key in SandboxPolicy.__dataclass_fields__}
        sandbox = await self.backend.create(
            agent_id=agent_id, run_id=run_id,
            policy=SandboxPolicy.from_dict({**self.default_policy.as_dict(), **overrides}),
        )
        return self._serialize(sandbox)

    async def create_for(
        self,
        agent_id: str,
        user_id: Optional[int] = None,
        run_id: Optional[str] = None,
        *,
        name: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, str]] = None,
        workspace: Optional[str] = None,
        workspace_path: Optional[str] = None,
        execution_mode: Optional[str] = None,
    ) -> dict:
        """Create a sandbox attached to a shared workspace.

        Several agents may attach to the same workspace; each gets its own
        sandbox namespace.  With no workspace argument, the user's default
        workspace is used, so all their agents share files by default.
        """
        record = self._workspaces().resolve(
            workspace or workspace_path, user_id,
            execution_mode=execution_mode)
        merged = {**self.default_policy.as_dict(), **(policy or {})}
        merged["execution_mode"] = record["execution_mode"]
        sandbox = await self.backend.create(
            agent_id=agent_id,
            run_id=run_id,
            policy=SandboxPolicy.from_dict(merged),
            user_id=user_id,
            name=name or record["name"],
            metadata={**(metadata or {}), "workspace_name": record["name"]},
            workspace_path=record["path"],
            workspace_id=record["id"],
        )
        return self._serialize(sandbox)

    @staticmethod
    def _policy_raises(current: Dict[str, Any],
                       wanted: Dict[str, Any]) -> Dict[str, Any]:
        """Only raise limits; never lower an existing sandbox's policy."""
        updates: Dict[str, Any] = {}
        for key in ("timeout_seconds", "cpu_seconds", "memory_mb",
                    "workspace_quota_mb", "max_processes", "max_output_bytes"):
            try:
                if key in wanted and float(wanted[key]) > float(current.get(key) or 0):
                    updates[key] = wanted[key]
            except (TypeError, ValueError):
                continue
        for key in ("network_enabled", "allow_shell", "allow_package_install"):
            if wanted.get(key) is True and not current.get(key):
                updates[key] = True
        return updates

    async def find_or_create(
        self,
        agent_id: str,
        user_id: Optional[int] = None,
        *,
        workspace: Optional[str] = None,
        workspace_path: Optional[str] = None,
        name: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, str]] = None,
        execution_mode: Optional[str] = None,
    ) -> dict:
        record = self._workspaces().resolve(
            workspace or workspace_path, user_id,
            execution_mode=execution_mode)
        existing = [
            item for item in (await self.list(agent_id, user_id)).get("sandboxes", [])
            if item.get("workspace_id") == record["id"]
        ]
        if existing:
            ref = existing[0]
            updates = self._policy_raises(ref.get("policy") or {}, policy or {})
            if updates:
                ref = await self.update_policy(
                    ref["sandbox_id"], agent_id, updates, user_id=user_id)
            return ref
        return await self.create_for(
            agent_id, user_id, name=name, policy=policy, metadata=metadata,
            workspace=record["path"], execution_mode=record["execution_mode"])

    async def get(self, sandbox_id: str, agent_id: str,
                  user_id: Optional[int] = None) -> dict:
        return self._serialize(self.backend.get(sandbox_id, agent_id, user_id))

    async def list(self, agent_id: Optional[str] = None,
                   user_id: Optional[int] = None) -> dict:
        items = [self._serialize(item)
                 for item in self.backend.list(agent_id, user_id)]
        return {"sandboxes": items, "count": len(items)}

    async def update_policy(self, sandbox_id: str, agent_id: str,
                            policy: Dict[str, Any],
                            user_id: Optional[int] = None) -> dict:
        merged = {**self.backend.get(sandbox_id, agent_id, user_id).policy.as_dict(),
                  **policy}
        sandbox = await self.backend.update_policy(
            sandbox_id, SandboxPolicy.from_dict(merged), agent_id, user_id)
        return self._serialize(sandbox)

    async def delete(self, sandbox_id: str, agent_id: str,
                     user_id: Optional[int] = None) -> None:
        await self.backend.delete(sandbox_id, agent_id, user_id)

    # ------------------------------------------------------------------ execution
    async def execute(self, sandbox_id: str, command: Sequence[str] | str, agent_id: str,
                      timeout_seconds: Optional[int] = None, **kwargs) -> dict:
        return await self.backend.execute(
            sandbox_id, command, agent_id, timeout_seconds, **kwargs)

    async def start(self, sandbox_id: str, command: Sequence[str] | str, agent_id: str,
                    **kwargs) -> dict:
        job = await self.backend.start(sandbox_id, command, agent_id, **kwargs)
        return job.as_dict()

    async def install(self, sandbox_id: str, packages: Sequence[str], agent_id: str,
                      manager: str = "auto", user_id: Optional[int] = None) -> dict:
        return await self.backend.install(
            sandbox_id, packages, agent_id, manager=manager, user_id=user_id)

    async def job(self, job_id: str, agent_id: str,
                  user_id: Optional[int] = None) -> dict:
        return self.backend.job(job_id, agent_id, user_id).as_dict()

    async def job_logs(self, job_id: str, agent_id: str,
                       user_id: Optional[int] = None) -> dict:
        return self.backend.job(job_id, agent_id, user_id).as_dict()

    async def list_jobs(self, sandbox_id: str, agent_id: str,
                        user_id: Optional[int] = None) -> dict:
        jobs = [job.as_dict() for job in
                self.backend.list_jobs(sandbox_id, agent_id, user_id)]
        return {"jobs": jobs, "count": len(jobs)}

    async def kill_job(self, job_id: str, agent_id: str,
                       user_id: Optional[int] = None) -> dict:
        return (await self.backend.kill_job(job_id, agent_id, user_id)).as_dict()

    # ------------------------------------------------------------------ files
    def _sandbox(self, sandbox_id: str, agent_id: str,
                 user_id: Optional[int] = None) -> SandboxRef:
        return self.backend.get(sandbox_id, agent_id, user_id)

    def _touch(self, sandbox: SandboxRef) -> None:
        sandbox.touch()
        save = getattr(self.backend, "save", None)
        if save is not None:
            save(sandbox)

    def _resolve(self, sandbox_id: str, agent_id: str, path: str,
                 user_id: Optional[int] = None,
                 allow_root: bool = False) -> tuple[Path, Path]:
        workspace = self._sandbox(sandbox_id, agent_id, user_id).workspace.resolve()
        relative = str(path or "").strip()
        if relative.startswith("/workspace"):
            relative = relative[len("/workspace"):]
        relative = relative.lstrip("/")
        if not relative and not allow_root:
            raise ValueError("path is required, e.g. 'src/main.py'")
        target = (workspace / relative).resolve()  # also resolves symlinks
        if target != workspace and workspace not in target.parents:
            raise ValueError("path must stay inside the sandbox workspace")
        if relative and ".venv" in Path(relative).parts:
            raise ValueError("paths inside .venv are managed by the package installer")
        return workspace, target

    @staticmethod
    def _workspace_usage(workspace: Path) -> int:
        total = 0
        for root, directories, files in os.walk(workspace, followlinks=False):
            directories[:] = [name for name in directories if name not in
                              {".venv", "node_modules", "__pycache__"}]
            for name in files:
                try:
                    total += (Path(root) / name).lstat().st_size
                except OSError:
                    pass
        return total

    def _enforce_quota(self, sandbox: SandboxRef) -> None:
        used = self._workspace_usage(sandbox.workspace.resolve())
        limit = sandbox.policy.workspace_quota_mb * 1024 * 1024
        if used > limit:
            raise ValueError(
                f"Sandbox workspace quota exceeded ({used} > {limit} bytes); "
                "delete build artifacts or use a larger policy.workspace_quota_mb"
            )

    async def write_file(self, sandbox_id: str, agent_id: str, path: str,
                         content: Any = "", *, append: bool = False,
                         user_id: Optional[int] = None) -> dict:
        sandbox = self._sandbox(sandbox_id, agent_id, user_id)
        _, target = self._resolve(sandbox_id, agent_id, path, user_id)
        data = str(content if content is not None else "").encode("utf-8")
        if len(data) > self.MAX_WRITE_BYTES:
            raise ValueError(f"content exceeds {self.MAX_WRITE_BYTES} bytes")
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if append else "wb"
        with target.open(mode) as handle:
            handle.write(data)
        self._enforce_quota(sandbox)
        self._touch(sandbox)
        workspace = sandbox.workspace.resolve()
        return {"path": str(target.relative_to(workspace)), "bytes": len(data),
                "appended": append}

    async def write_files(self, sandbox_id: str, agent_id: str,
                          files: Dict[str, Any],
                          user_id: Optional[int] = None) -> dict:
        if not isinstance(files, dict) or not files:
            raise ValueError("files must be a non-empty object of path -> content")
        total = sum(len(str(value if value is not None else "").encode("utf-8"))
                    for value in files.values())
        if total > self.MAX_TOTAL_WRITE_BYTES:
            raise ValueError(f"total content exceeds {self.MAX_TOTAL_WRITE_BYTES} bytes")
        written = []
        for path, content in files.items():
            result = await self.write_file(
                sandbox_id, agent_id, str(path), content, user_id=user_id)
            written.append(result)
        return {"files": written, "count": len(written), "bytes": total}

    async def read_file(self, sandbox_id: str, agent_id: str, path: str,
                        *, offset: int = 0, limit: Optional[int] = None,
                        user_id: Optional[int] = None) -> dict:
        _, target = self._resolve(sandbox_id, agent_id, path, user_id)
        if not target.is_file():
            raise FileNotFoundError(f"No such file in the sandbox: {path}")
        size = target.stat().st_size
        if size > self.MAX_READ_SOURCE_BYTES:
            raise ValueError(
                f"File is too large to read ({size} bytes); "
                "use 'search' or read a smaller file")
        text = target.read_text(encoding="utf-8", errors="replace")
        start = max(0, int(offset or 0))
        cap = min(int(limit or self.MAX_READ_CHARS), self.MAX_READ_CHARS)
        chunk = text[start:start + cap]
        return {
            "path": path,
            "content": chunk,
            "offset": start,
            "size": size,
            "truncated": start + len(chunk) < len(text),
        }

    async def list_files(self, sandbox_id: str, agent_id: str, path: str = "",
                         *, recursive: bool = True, max_results: int = 500,
                         user_id: Optional[int] = None) -> dict:
        workspace, base = self._resolve(
            sandbox_id, agent_id, path, user_id, allow_root=True)
        if not base.is_dir():
            raise ValueError(f"Not a directory in the sandbox: {path or '.'}")
        if not recursive:
            entries = sorted(base.iterdir(), key=lambda item: (item.is_file(), item.name))
        else:
            entries = sorted(
                (item for item in base.rglob("*")
                 if not any(part in {".venv", "node_modules", "__pycache__", ".git"}
                            for part in item.relative_to(workspace).parts)),
                key=lambda item: str(item),
            )
        limit = max(1, min(int(max_results), self.MAX_LIST_RESULTS))
        files, directories = [], []
        for item in entries[:limit]:
            if item.is_symlink():
                continue
            relative = str(item.relative_to(workspace))
            if item.is_dir():
                directories.append(relative)
            elif item.is_file():
                try:
                    files.append({"path": relative, "bytes": item.stat().st_size})
                except OSError:
                    files.append({"path": relative, "bytes": None})
        return {
            "path": str(base.relative_to(workspace)) if base != workspace else "",
            "files": files,
            "directories": directories,
            "truncated": len(entries) > limit,
        }

    async def stat_file(self, sandbox_id: str, agent_id: str, path: str,
                        user_id: Optional[int] = None) -> dict:
        workspace, target = self._resolve(sandbox_id, agent_id, path, user_id)
        if not target.exists():
            raise FileNotFoundError(f"No such path in the sandbox: {path}")
        stat = target.stat()
        return {
            "path": str(target.relative_to(workspace)),
            "type": "directory" if target.is_dir() else "file",
            "bytes": stat.st_size,
            "modified": stat.st_mtime,
        }

    async def make_dir(self, sandbox_id: str, agent_id: str, path: str,
                       user_id: Optional[int] = None) -> dict:
        sandbox = self._sandbox(sandbox_id, agent_id, user_id)
        _, target = self._resolve(sandbox_id, agent_id, path, user_id)
        target.mkdir(parents=True, exist_ok=True)
        self._touch(sandbox)
        return {"created": True, "path": str(target.relative_to(sandbox.workspace.resolve()))}

    async def delete_path(self, sandbox_id: str, agent_id: str, path: str,
                          *, recursive: bool = False,
                          user_id: Optional[int] = None) -> dict:
        sandbox = self._sandbox(sandbox_id, agent_id, user_id)
        workspace, target = self._resolve(sandbox_id, agent_id, path, user_id)
        if target == workspace:
            raise ValueError("Refusing to delete the sandbox workspace")
        if not target.exists():
            return {"deleted": False, "path": path}
        if target.is_dir():
            if not recursive:
                raise ValueError("path is a directory; pass recursive=True to delete it")
            shutil.rmtree(target)
        else:
            target.unlink()
        self._touch(sandbox)
        return {"deleted": True, "path": str(target.relative_to(workspace)), "recursive": recursive}

    async def move_path(self, sandbox_id: str, agent_id: str, source: str,
                        destination: str, *, overwrite: bool = False,
                        user_id: Optional[int] = None) -> dict:
        sandbox = self._sandbox(sandbox_id, agent_id, user_id)
        workspace, src = self._resolve(sandbox_id, agent_id, source, user_id)
        _, dst = self._resolve(sandbox_id, agent_id, destination, user_id)
        if not src.exists():
            raise FileNotFoundError(f"No such path in the sandbox: {source}")
        if dst.exists() and not overwrite:
            raise ValueError(f"Destination already exists: {destination}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(src), str(dst))
        self._touch(sandbox)
        return {"moved": True, "source": str(src.relative_to(workspace)),
                "destination": str(dst.relative_to(workspace))}

    async def copy_path(self, sandbox_id: str, agent_id: str, source: str,
                        destination: str, *, overwrite: bool = False,
                        user_id: Optional[int] = None) -> dict:
        sandbox = self._sandbox(sandbox_id, agent_id, user_id)
        workspace, src = self._resolve(sandbox_id, agent_id, source, user_id)
        _, dst = self._resolve(sandbox_id, agent_id, destination, user_id)
        if not src.exists():
            raise FileNotFoundError(f"No such path in the sandbox: {source}")
        if dst.exists() and not overwrite:
            raise ValueError(f"Destination already exists: {destination}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        self._enforce_quota(sandbox)
        self._touch(sandbox)
        return {"copied": True, "source": str(src.relative_to(workspace)),
                "destination": str(dst.relative_to(workspace))}

    async def search_files(self, sandbox_id: str, agent_id: str, pattern: str,
                           path: str = "", *, glob: str = "*", case_sensitive: bool = False,
                           max_results: int = 100,
                           user_id: Optional[int] = None) -> dict:
        if not str(pattern or ""):
            raise ValueError("search requires 'pattern'")
        workspace, base = self._resolve(
            sandbox_id, agent_id, path, user_id, allow_root=True)
        if not base.is_dir():
            raise ValueError(f"Not a directory in the sandbox: {path or '.'}")
        needle = str(pattern) if case_sensitive else str(pattern).lower()
        limit = max(1, min(int(max_results), 500))
        matches = []
        for item in base.rglob(glob or "*"):
            if len(matches) >= limit:
                break
            if not item.is_file() or item.is_symlink() or any(
                part in {".venv", "node_modules", "__pycache__", ".git"}
                for part in item.relative_to(workspace).parts
            ):
                continue
            try:
                resolved = item.resolve()
                resolved.relative_to(workspace)
            except (OSError, ValueError):
                continue
            try:
                if item.stat().st_size > self.MAX_READ_SOURCE_BYTES:
                    continue
                with item.open("r", encoding="utf-8", errors="replace") as handle:
                    for number, line in enumerate(handle, 1):
                        haystack = line if case_sensitive else line.lower()
                        if needle in haystack:
                            matches.append({
                                "path": str(item.relative_to(workspace)),
                                "line": number,
                                "text": line.rstrip("\n")[:500],
                            })
                            if len(matches) >= limit:
                                break
            except OSError:
                continue
        return {"matches": matches, "count": len(matches),
                "truncated": len(matches) >= limit}

    async def usage(self, sandbox_id: str, agent_id: str,
                    user_id: Optional[int] = None) -> dict:
        sandbox = self._sandbox(sandbox_id, agent_id, user_id)
        used = self._workspace_usage(sandbox.workspace.resolve())
        limit = sandbox.policy.workspace_quota_mb * 1024 * 1024
        return {
            "workspace_bytes": used,
            "quota_bytes": limit,
            "quota_used_percent": round((used / limit) * 100, 2) if limit else 0,
        }

    # ------------------------------------------------------------------ archive
    async def archive(self, sandbox_id: str, agent_id: str,
                      user_id: Optional[int] = None,
                      include_dependencies: bool = False) -> str:
        return str(await self.backend.archive(
            sandbox_id, agent_id, user_id, include_dependencies))

    async def restore(self, archive_path: str, agent_id: str,
                      run_id: Optional[str] = None,
                      user_id: Optional[int] = None,
                      policy: Optional[Dict[str, Any]] = None,
                      name: Optional[str] = None) -> dict:
        sandbox = await self.backend.restore(
            archive_path, agent_id, run_id,
            user_id=user_id,
            policy=SandboxPolicy.from_dict(
                {**self.default_policy.as_dict(), **(policy or {})}),
            name=name,
        )
        return self._serialize(sandbox)

    # ------------------------------------------------------------------ serialize
    @staticmethod
    def _serialize(sandbox: SandboxRef) -> dict:
        return {
            "sandbox_id": sandbox.sandbox_id,
            "agent_id": sandbox.agent_id,
            "run_id": sandbox.run_id,
            "name": sandbox.name,
            "workspace": str(sandbox.workspace),
            "workspace_id": sandbox.workspace_id,
            "workspace_name": (sandbox.metadata or {}).get("workspace_name"),
            "status": sandbox.status.value,
            "policy": sandbox.policy.as_dict(),
            "archive_path": str(sandbox.archive_path) if sandbox.archive_path else None,
            "created_at": sandbox.created_at,
            "updated_at": sandbox.updated_at,
            "last_used_at": sandbox.last_used_at,
            "execution_count": sandbox.execution_count,
        }
