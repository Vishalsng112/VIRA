import asyncio
import json
import resource
import re
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path
from typing import Optional, Sequence

from .models import SandboxPolicy, SandboxRef, SandboxStatus


class BubblewrapBackend:
    """Creates Linux user-space sandboxes with a private filesystem namespace."""

    def __init__(self, root: str = "/AgentWorkspace", bwrap_binary: str = "bwrap"):
        self.root = Path(root).resolve()
        self.bwrap_binary = bwrap_binary
        self._sandboxes: dict[str, SandboxRef] = {}

    def _require_bwrap(self) -> None:
        if shutil.which(self.bwrap_binary) is None:
            raise RuntimeError(
                "Bubblewrap is required for sandbox execution; install the 'bubblewrap' package"
            )

    def _get(self, sandbox_id: str, agent_id: Optional[str] = None) -> SandboxRef:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None or sandbox.status == SandboxStatus.DELETED:
            raise ValueError(f"Sandbox '{sandbox_id}' does not exist")
        if agent_id is not None and sandbox.agent_id != agent_id:
            raise PermissionError("Sandbox does not belong to this agent")
        return sandbox

    def get(self, sandbox_id: str, agent_id: Optional[str] = None) -> SandboxRef:
        return self._get(sandbox_id, agent_id)

    async def create(
        self, agent_id: str, run_id: Optional[str] = None,
        policy: Optional[SandboxPolicy] = None,
        sandbox_id: Optional[str] = None,
    ) -> SandboxRef:
        import uuid

        self._require_bwrap()
        policy = policy or SandboxPolicy()
        sandbox_id = sandbox_id or str(uuid.uuid4())
        workspace = self.root / sandbox_id / "workspace"
        try:
            workspace.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(f"Sandbox '{sandbox_id}' already exists") from exc
        (workspace.parent / "artifacts").mkdir()
        (workspace.parent / "metadata.json").write_text(
            json.dumps({"sandbox_id": sandbox_id, "agent_id": agent_id, "run_id": run_id}),
            encoding="utf-8",
        )
        sandbox = SandboxRef(sandbox_id, agent_id, run_id, workspace, policy=policy)
        self._sandboxes[sandbox_id] = sandbox
        return sandbox

    def _command(self, sandbox: SandboxRef, command: Sequence[str]) -> list[str]:
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("command must be a non-empty sequence of non-empty strings")
        policy = sandbox.policy
        parent = sandbox.workspace.parent
        args = [
            self.bwrap_binary, "--die-with-parent", "--new-session",
            "--unshare-pid", "--unshare-uts", "--unshare-ipc",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib", "--chdir", "/workspace",
            "--dir", "/tmp/home",
            "--setenv", "HOME", "/tmp/home",
            "--setenv", "PATH", (
                "/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin"
                if (sandbox.workspace / ".venv" / "bin").is_dir()
                else "/usr/local/bin:/usr/bin:/bin"
            ),
        ]
        if Path("/lib64").exists():
            args += ["--ro-bind", "/lib64", "/lib64"]
        if Path("/usr/local").exists():
            args += ["--ro-bind", "/usr/local", "/usr/local"]
        if Path("/etc").exists():
            args += ["--ro-bind", "/etc", "/etc"]
        for private_path in ("/home", "/root", "/run", "/var", "/opt", "/srv",
                             "/mnt", "/media", "/data", str(self.root)):
            if Path(private_path).exists():
                args += ["--tmpfs", private_path]
        args += [
            "--bind", str(sandbox.workspace), "/workspace",
            "--bind", str(parent / "artifacts"), "/artifacts",
        ]
        if not policy.network_enabled:
            args.append("--unshare-net")
        return args + ["--"] + list(command)

    @staticmethod
    def _validate_packages(packages: Sequence[str]) -> list[str]:
        if not packages:
            raise ValueError("At least one package is required")
        package_pattern = re.compile(
            r"^[A-Za-z0-9][A-Za-z0-9_.-]*"
            r"(?:\[[A-Za-z0-9_,.-]+\])?"
            r"(?:[<>=!~][A-Za-z0-9.*+,<>=!~-]+)?$"
        )
        validated = []
        for package in packages:
            if not isinstance(package, str) or not package_pattern.fullmatch(package):
                raise ValueError(f"Invalid package specification: {package!r}")
            validated.append(package)
        return validated

    @staticmethod
    def _apply_limits(policy: SandboxPolicy) -> None:
        resource.setrlimit(resource.RLIMIT_NPROC, (policy.max_processes, policy.max_processes))
        resource.setrlimit(resource.RLIMIT_CPU, (policy.cpu_seconds, policy.cpu_seconds))
        memory_bytes = policy.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

    async def execute(
        self, sandbox_id: str, command: Sequence[str], agent_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        _policy: Optional[SandboxPolicy] = None,
    ) -> dict:
        sandbox = self._get(sandbox_id, agent_id)
        self._require_bwrap()
        effective_sandbox = (
            sandbox if _policy is None else replace(sandbox, policy=_policy)
        )
        timeout = (
            effective_sandbox.policy.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout <= 0 or timeout > effective_sandbox.policy.timeout_seconds:
            raise ValueError("timeout_seconds exceeds the sandbox policy")
        sandbox.status = SandboxStatus.RUNNING
        process = await asyncio.create_subprocess_exec(
            *self._command(effective_sandbox, command),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            preexec_fn=lambda: self._apply_limits(effective_sandbox.policy),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            sandbox.status = SandboxStatus.STOPPED
            raise TimeoutError(f"Sandbox command exceeded {timeout} seconds")
        sandbox.status = SandboxStatus.STOPPED
        return {
            "exit_code": process.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }

    async def install(
        self, sandbox_id: str, packages: Sequence[str], agent_id: Optional[str] = None,
    ) -> dict:
        sandbox = self._get(sandbox_id, agent_id)
        if not sandbox.policy.allow_package_install:
            raise PermissionError("Package installation is disabled by the sandbox policy")
        validated = self._validate_packages(packages)
        install_sandbox = replace(
            sandbox,
            policy=replace(sandbox.policy, network_enabled=True),
        )
        venv_result = await self.execute(
            sandbox_id,
            ["python3", "-m", "venv", "/workspace/.venv"],
            agent_id=agent_id,
            _policy=install_sandbox.policy,
        )
        if venv_result["exit_code"] != 0:
            return venv_result
        return await self.execute(
            sandbox_id,
            [
                "/workspace/.venv/bin/python", "-m", "pip", "install",
                "--disable-pip-version-check", "--no-input", *validated,
            ],
            agent_id=agent_id,
            _policy=install_sandbox.policy,
        )

    async def archive(self, sandbox_id: str, agent_id: Optional[str] = None) -> Path:
        sandbox = self._get(sandbox_id, agent_id)
        archive = self.root / f"{sandbox_id}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(sandbox.workspace, arcname="workspace")
            bundle.add(sandbox.workspace.parent / "artifacts", arcname="artifacts")
            metadata = sandbox.workspace.parent / "metadata.json"
            if metadata.is_file():
                bundle.add(metadata, arcname="metadata.json")
        sandbox.archive_path = archive
        sandbox.status = SandboxStatus.ARCHIVED
        return archive

    async def restore(
        self, archive_path: str, agent_id: str, run_id: Optional[str] = None,
        sandbox_id: Optional[str] = None,
    ) -> SandboxRef:
        archive = Path(archive_path).resolve()
        if archive.parent != self.root or archive.suffixes != [".tar", ".gz"]:
            raise ValueError("Archive must be a .tar.gz file inside /AgentWorkspace")
        if not archive.is_file():
            raise FileNotFoundError(archive)
        import uuid
        sandbox_id = sandbox_id or str(uuid.uuid4())
        destination = self.root / sandbox_id
        destination.mkdir(parents=True, exist_ok=False)
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            target = destination.resolve()
            for member in members:
                extracted = (destination / member.name).resolve()
                if extracted != target and target not in extracted.parents:
                    raise ValueError("Archive contains a path outside the sandbox")
            bundle.extractall(destination)
        workspace = destination / "workspace"
        if not workspace.is_dir():
            raise ValueError("Archive does not contain a sandbox workspace")
        sandbox = SandboxRef(sandbox_id, agent_id, run_id, workspace, status=SandboxStatus.STOPPED)
        self._sandboxes[sandbox_id] = sandbox
        return sandbox

    async def delete(self, sandbox_id: str, agent_id: Optional[str] = None) -> None:
        sandbox = self._get(sandbox_id, agent_id)
        shutil.rmtree(sandbox.workspace.parent)
        if sandbox.archive_path:
            sandbox.archive_path.unlink(missing_ok=True)
        sandbox.status = SandboxStatus.DELETED
