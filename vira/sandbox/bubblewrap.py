"""Bubblewrap-backed sandbox backend.

The backend owns the on-disk sandbox registry (``metadata.json`` per sandbox),
builds the Bubblewrap command line, runs foreground commands, tracks background
jobs, and performs workspace file operations at the manager layer.
"""
from __future__ import annotations

import asyncio
import json
import re
import resource
import shlex
import shutil
import tarfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .models import (
    JobStatus,
    SandboxJob,
    SandboxPolicy,
    SandboxRef,
    SandboxStatus,
    utc_now,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_PACKAGE_RE = re.compile(
    r"^(?:@[A-Za-z0-9][A-Za-z0-9_.-]*/)?"
    r"[A-Za-z0-9][A-Za-z0-9_.-]*"
    r"(?:\[[A-Za-z0-9_,.\-]+\])?"
    r"(?:[<>=!~^@][A-Za-z0-9.*+,<>=!~^@\-]+)?$"
)
_DEP_CACHE_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                   ".mypy_cache", ".ruff_cache", ".cache"}
_DEFAULT_ENV = {
    "HOME": "/tmp/home",
    "TMPDIR": "/tmp",
    "TERM": "dumb",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    "NPM_CONFIG_FUND": "false",
    "NPM_CONFIG_AUDIT": "false",
}


class BubblewrapBackend:
    """Creates Linux user-space sandboxes with a private filesystem namespace."""

    def __init__(self, root: str = "/AgentWorkspace", bwrap_binary: str = "bwrap"):
        self.root = Path(root).resolve()
        self.bwrap_binary = bwrap_binary
        self._sandboxes: Dict[str, SandboxRef] = {}
        self._jobs: Dict[str, SandboxJob] = {}
        self._preflight_ok = False
        self._load_existing()

    # ------------------------------------------------------------------ registry
    def _load_existing(self) -> None:
        """Restore sandboxes created before a server restart."""
        if not self.root.is_dir():
            return
        for directory in self.root.iterdir():
            metadata_path = directory / "metadata.json"
            if not directory.is_dir() or not metadata_path.is_file():
                continue
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                sandbox_id = str(data.get("sandbox_id") or directory.name)
                if sandbox_id != directory.name or not _ID_RE.match(sandbox_id):
                    continue
                workspace = directory / "workspace"
                if not workspace.is_dir():
                    continue
                status = SandboxStatus(str(data.get("status") or "idle"))
                if status in {SandboxStatus.RUNNING, SandboxStatus.DELETED, SandboxStatus.ERROR}:
                    # A process cannot survive a server restart and deleted
                    # workspaces should not reappear in the registry.
                    if status == SandboxStatus.DELETED:
                        continue
                    status = SandboxStatus.IDLE
                archive = data.get("archive_path")
                sandbox = SandboxRef(
                    sandbox_id=sandbox_id,
                    agent_id=str(data.get("agent_id") or ""),
                    run_id=data.get("run_id"),
                    workspace=workspace,
                    status=status,
                    policy=SandboxPolicy.from_dict(data.get("policy")),
                    archive_path=Path(archive) if archive else None,
                    metadata=dict(data.get("metadata") or {}),
                    owner_user_id=data.get("owner_user_id"),
                    name=data.get("name"),
                    created_at=str(data.get("created_at") or utc_now()),
                    updated_at=str(data.get("updated_at") or utc_now()),
                    last_used_at=data.get("last_used_at"),
                    execution_count=int(data.get("execution_count") or 0),
                )
                self._sandboxes[sandbox_id] = sandbox
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue

    def _write_metadata(self, sandbox: SandboxRef) -> None:
        target = sandbox.workspace.parent / "metadata.json"
        payload = {
            "sandbox_id": sandbox.sandbox_id,
            "agent_id": sandbox.agent_id,
            "run_id": sandbox.run_id,
            "status": sandbox.status.value,
            "policy": sandbox.policy.as_dict(),
            "archive_path": str(sandbox.archive_path) if sandbox.archive_path else None,
            "metadata": sandbox.metadata,
            "owner_user_id": sandbox.owner_user_id,
            "name": sandbox.name,
            "created_at": sandbox.created_at,
            "updated_at": sandbox.updated_at,
            "last_used_at": sandbox.last_used_at,
            "execution_count": sandbox.execution_count,
        }
        try:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            # The sandbox is still usable if metadata cannot be persisted.
            pass

    # ------------------------------------------------------------------ limits
    @staticmethod
    def _task_count() -> int:
        """Upper bound of tasks (processes+threads) already alive on this machine."""
        try:
            with open("/proc/loadavg") as handle:
                return int(handle.read().split()[3].split("/")[1])
        except (OSError, ValueError, IndexError):
            return 4096

    async def _preflight(self) -> None:
        """Fail early, with the real bubblewrap error and a hint, if it cannot start."""
        if self._preflight_ok:
            return
        try:
            process = await asyncio.create_subprocess_exec(
                self.bwrap_binary, "--ro-bind", "/", "/", "--unshare-pid", "--dev", "/dev", "true",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), 20)
        except (OSError, asyncio.TimeoutError) as exc:
            raise RuntimeError(f"Bubblewrap could not be started: {exc}") from exc
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip() or f"exit code {process.returncode}"
            hint = ""
            if any(word in detail.lower() for word in ("permission", "not permitted", "namespace", "uid map")):
                hint = (" On Ubuntu 24.04+ AppArmor blocks unprivileged user namespaces; run "
                        "'sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0' "
                        "or add an AppArmor profile for bwrap.")
            raise RuntimeError(f"Bubblewrap cannot create a sandbox: {detail}.{hint}")
        self._preflight_ok = True

    def _require_bwrap(self) -> None:
        if shutil.which(self.bwrap_binary) is None:
            raise RuntimeError(
                "Bubblewrap is required for sandbox execution; install the 'bubblewrap' package"
            )

    @staticmethod
    def _apply_limits(policy: SandboxPolicy, existing_tasks: int = 0) -> None:
        # RLIMIT_NPROC counts every task of the *user*, not just this sandbox, so a
        # fixed cap below the user's current count makes fork() fail with EAGAIN
        # ("Resource temporarily unavailable").  Allow max_processes on top of them.
        nproc = existing_tasks + policy.max_processes
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
        resource.setrlimit(resource.RLIMIT_CPU, (policy.cpu_seconds, policy.cpu_seconds))
        memory_bytes = policy.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

    # ------------------------------------------------------------------ access
    def _get(self, sandbox_id: str, agent_id: Optional[str] = None,
             user_id: Optional[int] = None) -> SandboxRef:
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None or sandbox.status == SandboxStatus.DELETED:
            raise ValueError(f"Sandbox '{sandbox_id}' does not exist")
        if agent_id is not None and sandbox.agent_id != agent_id:
            raise PermissionError("Sandbox does not belong to this agent")
        if (user_id is not None and sandbox.owner_user_id is not None
                and int(user_id) != int(sandbox.owner_user_id)):
            raise PermissionError("Sandbox does not belong to this user")
        return sandbox

    def get(self, sandbox_id: str, agent_id: Optional[str] = None,
            user_id: Optional[int] = None) -> SandboxRef:
        return self._get(sandbox_id, agent_id, user_id)

    def list(self, agent_id: Optional[str] = None,
             user_id: Optional[int] = None) -> List[SandboxRef]:
        items = [item for item in self._sandboxes.values()
                 if item.status != SandboxStatus.DELETED]
        if agent_id is not None:
            items = [item for item in items if item.agent_id == agent_id]
        if user_id is not None:
            items = [item for item in items
                     if item.owner_user_id is None or int(item.owner_user_id) == int(user_id)]
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    # ------------------------------------------------------------------ create
    async def create(
        self,
        agent_id: str,
        run_id: Optional[str] = None,
        policy: Optional[SandboxPolicy] = None,
        sandbox_id: Optional[str] = None,
        user_id: Optional[int] = None,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> SandboxRef:
        self._require_bwrap()
        await self._preflight()
        policy = policy or SandboxPolicy()
        sandbox_id = sandbox_id or str(uuid.uuid4())
        if not _ID_RE.match(sandbox_id):
            raise ValueError(
                "sandbox_id must be 1-64 characters: letters, digits, dot, dash or underscore"
            )
        parent = self.root / sandbox_id
        workspace = parent / "workspace"
        try:
            workspace.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(f"Sandbox '{sandbox_id}' already exists") from exc
        (parent / "artifacts").mkdir(exist_ok=True)
        now = utc_now()
        sandbox = SandboxRef(
            sandbox_id=sandbox_id,
            agent_id=agent_id,
            run_id=run_id,
            workspace=workspace,
            policy=policy,
            owner_user_id=int(user_id) if user_id is not None else None,
            name=name,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self._sandboxes[sandbox_id] = sandbox
        self._write_metadata(sandbox)
        return sandbox

    # ------------------------------------------------------------------ command
    @staticmethod
    def _validate_env(env: Optional[Dict[str, Any]]) -> Dict[str, str]:
        validated: Dict[str, str] = {}
        for key, value in (env or {}).items():
            key, value = str(key), str(value)
            if not _ENV_NAME_RE.fullmatch(key):
                raise ValueError(f"Invalid environment variable name: {key!r}")
            if len(value) > 8192:
                raise ValueError(f"Environment variable {key} is too long")
            validated[key] = value
        return validated

    def _resolve_cwd(self, sandbox: SandboxRef, cwd: Optional[str]) -> str:
        if not cwd or cwd in ("/workspace", ".", "./"):
            return "/workspace"
        candidate = str(cwd).strip()
        if candidate == "/artifacts" or candidate.startswith("/artifacts/"):
            root, relative = "/artifacts", candidate[len("/artifacts"):]
        elif candidate.startswith("/workspace"):
            root, relative = "/workspace", candidate[len("/workspace"):]
        else:
            root, relative = "/workspace", "/" + candidate
        target = (sandbox.workspace if root == "/workspace"
                  else sandbox.workspace.parent / "artifacts") / relative.lstrip("/")
        base = (sandbox.workspace if root == "/workspace"
                else sandbox.workspace.parent / "artifacts").resolve()
        try:
            target = target.resolve()
            target.relative_to(base)
        except (ValueError, OSError) as exc:
            raise ValueError("cwd must stay inside the sandbox") from exc
        return root + ("/" + str(target.relative_to(base)) if target != base else "")

    def _command(
        self,
        sandbox: SandboxRef,
        command: Sequence[str] | str,
        *,
        shell: bool = False,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        if shell:
            if not sandbox.policy.allow_shell:
                raise PermissionError("Shell execution is disabled by the sandbox policy")
            if isinstance(command, (list, tuple)):
                script = shlex.join([str(part) for part in command])
            else:
                script = str(command)
            if not script.strip():
                raise ValueError("command must not be empty")
            argv = ["/bin/bash", "-lc", script] if Path("/bin/bash").exists() else ["/bin/sh", "-lc", script]
        else:
            if isinstance(command, str):
                command = shlex.split(command)
            if not command or any(not isinstance(part, str) or not part for part in command):
                raise ValueError("command must be a non-empty sequence of non-empty strings")
            argv = list(command)

        policy = sandbox.policy
        parent = sandbox.workspace.parent
        venv_bin = sandbox.workspace / ".venv" / "bin"
        path = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        if venv_bin.is_dir():
            path = "/workspace/.venv/bin:" + path
        default_env = dict(_DEFAULT_ENV)
        if (sandbox.workspace / ".vendor").is_dir():
            default_env["PYTHONPATH"] = "/workspace/.vendor"
        args = [
            self.bwrap_binary, "--die-with-parent", "--new-session",
            "--unshare-pid", "--unshare-uts", "--unshare-ipc",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--cap-drop", "ALL",
            "--chdir", self._resolve_cwd(sandbox, cwd),
            "--dir", "/tmp/home",
            "--clearenv",
        ]
        for key, value in {**default_env, "PATH": path, **self._validate_env(env)}.items():
            args += ["--setenv", key, value]
        if Path("/lib64").exists():
            args += ["--ro-bind", "/lib64", "/lib64"]
        if Path("/usr/local").exists():
            args += ["--ro-bind", "/usr/local", "/usr/local"]
        if Path("/etc").exists():
            args += ["--ro-bind", "/etc", "/etc"]
        # Bind the workspace before hiding the sandbox root. Bubblewrap resolves
        # the bind source in the new namespace; hiding the root first would make
        # /AgentWorkspace/<id>/workspace unreachable.
        args += [
            "--bind", str(sandbox.workspace), "/workspace",
            "--bind", str(parent / "artifacts"), "/artifacts",
        ]
        for private_path in ("/home", "/root", "/var", "/opt", "/srv",
                             "/mnt", "/media", "/data", str(self.root)):
            if Path(private_path).exists():
                args += ["--tmpfs", private_path]
        # /etc/resolv.conf is commonly a symlink into /run/systemd/resolve.
        # Keep DNS working for networked sandboxes by exposing /run read-only.
        # Without networking the entire /run tree is private.
        if Path("/run").exists():
            if policy.network_enabled:
                args += ["--ro-bind", "/run", "/run"]
            else:
                args += ["--tmpfs", "/run"]
        if not policy.network_enabled:
            args.append("--unshare-net")
        return args + ["--"] + argv

    # ------------------------------------------------------------------ execute
    async def _spawn(
        self,
        sandbox: SandboxRef,
        command: Sequence[str] | str,
        *,
        shell: bool,
        cwd: Optional[str],
        env: Optional[Dict[str, str]],
        policy: Optional[SandboxPolicy] = None,
    ):
        effective = replace(sandbox, policy=policy) if policy is not None else sandbox
        self._require_bwrap()
        await self._preflight()
        existing_tasks = self._task_count()
        try:
            return await asyncio.create_subprocess_exec(
                *self._command(effective, command, shell=shell, cwd=cwd, env=env),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                preexec_fn=lambda: self._apply_limits(effective.policy, existing_tasks),
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start the sandbox process: {exc}") from exc

    async def execute(
        self,
        sandbox_id: str,
        command: Sequence[str] | str,
        agent_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        *,
        shell: bool = False,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Optional[str] = None,
        user_id: Optional[int] = None,
        _policy: Optional[SandboxPolicy] = None,
    ) -> dict:
        sandbox = self._get(sandbox_id, agent_id, user_id)
        effective = sandbox.policy if _policy is None else _policy
        timeout = effective.timeout_seconds if timeout_seconds is None else int(timeout_seconds)
        if timeout <= 0 or timeout > effective.timeout_seconds:
            raise ValueError(f"timeout_seconds must be between 1 and {effective.timeout_seconds}")
        started = time.monotonic()
        sandbox.status = SandboxStatus.RUNNING
        process = await self._spawn(
            sandbox, command, shell=shell, cwd=cwd, env=env, policy=_policy,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=stdin.encode("utf-8") if stdin is not None else None),
                timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            sandbox.status = SandboxStatus.IDLE
            sandbox.touch()
            self._write_metadata(sandbox)
            raise TimeoutError(f"Sandbox command exceeded {timeout} seconds")
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        sandbox.status = SandboxStatus.IDLE
        sandbox.touch()
        sandbox.execution_count += 1
        self._write_metadata(sandbox)
        limit = effective.max_output_bytes
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        truncated = len(out) > limit or len(err) > limit
        return {
            "exit_code": process.returncode,
            "stdout": out[:limit],
            "stderr": err[:limit],
            "truncated": truncated,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    # ------------------------------------------------------------------ jobs
    @staticmethod
    async def _read_limited(stream: asyncio.StreamReader, limit: int) -> tuple[str, bool]:
        chunks: List[bytes] = []
        size = 0
        truncated = False
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            if size < limit:
                keep = chunk[: limit - size]
                chunks.append(keep)
                size += len(keep)
                if len(keep) < len(chunk):
                    truncated = True
            else:
                truncated = True
        return b"".join(chunks).decode(errors="replace"), truncated

    async def _collect_job(self, job: SandboxJob, process, limit: int) -> None:
        try:
            (stdout, out_truncated), (stderr, err_truncated) = await asyncio.gather(
                self._read_limited(process.stdout, limit),
                self._read_limited(process.stderr, limit),
            )
            await process.wait()
            job.stdout, job.stderr = stdout, stderr
            job.truncated = out_truncated or err_truncated
            job.exit_code = process.returncode
            if job.status == JobStatus.KILLED:
                pass
            elif process.returncode == 0:
                job.status = JobStatus.COMPLETED
            else:
                job.status = JobStatus.FAILED
        except Exception as exc:  # job failures must not crash the event loop
            job.status = JobStatus.FAILED
            job.stderr = (job.stderr + f"\njob collector failed: {exc}").strip()
        finally:
            job.ended_at = utc_now()
            sandbox = self._sandboxes.get(job.sandbox_id)
            if sandbox is not None:
                sandbox.status = SandboxStatus.IDLE
                sandbox.touch()
                self._write_metadata(sandbox)

    async def start(
        self,
        sandbox_id: str,
        command: Sequence[str] | str,
        agent_id: Optional[str] = None,
        *,
        shell: bool = False,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> SandboxJob:
        sandbox = self._get(sandbox_id, agent_id, user_id)
        process = await self._spawn(sandbox, command, shell=shell, cwd=cwd, env=env)
        if stdin is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError, RuntimeError):
                pass
        job = SandboxJob(
            job_id=str(uuid.uuid4()),
            sandbox_id=sandbox_id,
            command=shlex.join(command) if isinstance(command, (list, tuple)) else str(command),
            pid=process.pid,
            _process=process,
        )
        self._jobs[job.job_id] = job
        sandbox.status = SandboxStatus.RUNNING
        sandbox.touch()
        sandbox.execution_count += 1
        self._write_metadata(sandbox)
        job._task = asyncio.create_task(
            self._collect_job(job, process, sandbox.policy.max_output_bytes)
        )
        return job

    def _job(self, job_id: str, agent_id: Optional[str] = None,
             user_id: Optional[int] = None) -> SandboxJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Sandbox job '{job_id}' does not exist")
        self._get(job.sandbox_id, agent_id, user_id)
        return job

    def job(self, job_id: str, agent_id: Optional[str] = None,
            user_id: Optional[int] = None) -> SandboxJob:
        return self._job(job_id, agent_id, user_id)

    def list_jobs(self, sandbox_id: str, agent_id: Optional[str] = None,
                  user_id: Optional[int] = None) -> List[SandboxJob]:
        self._get(sandbox_id, agent_id, user_id)
        return [job for job in self._jobs.values() if job.sandbox_id == sandbox_id]

    async def kill_job(self, job_id: str, agent_id: Optional[str] = None,
                       user_id: Optional[int] = None) -> SandboxJob:
        job = self._job(job_id, agent_id, user_id)
        process = job._process
        if process is not None and process.returncode is None:
            job.status = JobStatus.KILLED
            process.kill()
            await process.wait()
        if job._task is not None and not job._task.done():
            try:
                await asyncio.wait_for(job._task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        return job

    # ------------------------------------------------------------------ packages
    @staticmethod
    def _validate_packages(packages: Sequence[str]) -> List[str]:
        if not packages:
            raise ValueError("At least one package is required")
        validated = []
        for package in packages:
            if not isinstance(package, str) or not _PACKAGE_RE.fullmatch(package):
                raise ValueError(f"Invalid package specification: {package!r}")
            if package.startswith("-"):
                raise ValueError(f"Invalid package specification: {package!r}")
            validated.append(package)
        return validated

    async def install(
        self,
        sandbox_id: str,
        packages: Sequence[str],
        agent_id: Optional[str] = None,
        manager: str = "auto",
        user_id: Optional[int] = None,
    ) -> dict:
        sandbox = self._get(sandbox_id, agent_id, user_id)
        if not sandbox.policy.allow_package_install:
            raise PermissionError("Package installation is disabled by the sandbox policy")
        validated = self._validate_packages(packages)
        manager = (manager or "auto").strip().lower()
        if manager == "auto":
            manager = "npm" if all(item.startswith("@") or "/" in item for item in validated) else "pip"
        if manager not in {"pip", "npm"}:
            raise ValueError("package manager must be 'pip', 'npm' or 'auto'")
        install_policy = replace(sandbox.policy, network_enabled=True)
        if manager == "npm":
            return await self.execute(
                sandbox_id,
                ["npm", "install", "--no-audit", "--no-fund",
                 "--prefix", "/workspace", *validated],
                agent_id=agent_id,
                user_id=user_id,
                _policy=install_policy,
            )
        venv = sandbox.workspace / ".venv"
        if not (venv / "bin" / "python").is_file():
            venv_result = await self.execute(
                sandbox_id,
                ["/usr/bin/python3", "-m", "venv", "/workspace/.venv"],
                agent_id=agent_id,
                user_id=user_id,
                _policy=install_policy,
            )
            # Some distributions ship Python without ensurepip. The venv then has
            # an interpreter but no pip; fall back to a project-local target
            # directory that is added to PYTHONPATH for later commands.
            if venv_result["exit_code"] != 0:
                return await self._pip_target_install(
                    sandbox_id, validated, agent_id, user_id, install_policy)
        pip_check = await self.execute(
            sandbox_id,
            ["/workspace/.venv/bin/python", "-m", "pip", "--version"],
            agent_id=agent_id, user_id=user_id, _policy=install_policy,
        )
        if pip_check["exit_code"] != 0:
            return await self._pip_target_install(
                sandbox_id, validated, agent_id, user_id, install_policy)
        return await self.execute(
            sandbox_id,
            ["/workspace/.venv/bin/python", "-m", "pip", "install",
             "--disable-pip-version-check", "--no-input", *validated],
            agent_id=agent_id,
            user_id=user_id,
            _policy=install_policy,
        )

    async def _pip_target_install(
        self,
        sandbox_id: str,
        packages: Sequence[str],
        agent_id: Optional[str],
        user_id: Optional[int],
        policy: SandboxPolicy,
    ) -> dict:
        return await self.execute(
            sandbox_id,
            ["/usr/bin/python3", "-m", "pip", "install",
             "--disable-pip-version-check", "--no-input",
             "--target", "/workspace/.vendor", *packages],
            agent_id=agent_id,
            user_id=user_id,
            _policy=policy,
        )

    # ------------------------------------------------------------------ archive
    @staticmethod
    def _archive_filter(include_dependencies: bool):
        def filter_member(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
            parts = Path(info.name).parts
            if info.issym() or info.islnk():
                return None
            if not include_dependencies and any(part in _DEP_CACHE_DIRS for part in parts):
                return None
            return info
        return filter_member

    async def archive(
        self,
        sandbox_id: str,
        agent_id: Optional[str] = None,
        user_id: Optional[int] = None,
        include_dependencies: bool = False,
    ) -> Path:
        sandbox = self._get(sandbox_id, agent_id, user_id)
        archive = self.root / f"{sandbox_id}.tar.gz"
        filter_member = self._archive_filter(include_dependencies)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(sandbox.workspace, arcname="workspace", filter=filter_member)
            bundle.add(
                sandbox.workspace.parent / "artifacts",
                arcname="artifacts", filter=filter_member,
            )
        sandbox.archive_path = archive
        sandbox.status = SandboxStatus.ARCHIVED
        sandbox.touch()
        self._write_metadata(sandbox)
        return archive

    async def restore(
        self,
        archive_path: str,
        agent_id: str,
        run_id: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        user_id: Optional[int] = None,
        policy: Optional[SandboxPolicy] = None,
        name: Optional[str] = None,
    ) -> SandboxRef:
        archive = Path(archive_path).resolve()
        if archive.parent != self.root or archive.suffixes != [".tar", ".gz"]:
            raise ValueError("Archive must be a .tar.gz file inside the sandbox root")
        if not archive.is_file():
            raise FileNotFoundError(archive)
        sandbox_id = sandbox_id or str(uuid.uuid4())
        if not _ID_RE.match(sandbox_id):
            raise ValueError("Invalid sandbox_id")
        destination = self.root / sandbox_id
        try:
            destination.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(f"Sandbox '{sandbox_id}' already exists") from exc
        try:
            with tarfile.open(archive, "r:gz") as bundle:
                target = destination.resolve()
                for member in bundle.getmembers():
                    extracted = (destination / member.name).resolve()
                    if extracted != target and target not in extracted.parents:
                        raise ValueError("Archive contains a path outside the sandbox")
                    if member.isdev() or member.isfifo():
                        raise ValueError("Archive contains unsupported special files")
                    if member.issym() or member.islnk():
                        raise ValueError("Archive contains symbolic links")
                bundle.extractall(destination)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        workspace = destination / "workspace"
        if not workspace.is_dir():
            shutil.rmtree(destination, ignore_errors=True)
            raise ValueError("Archive does not contain a sandbox workspace")
        now = utc_now()
        sandbox = SandboxRef(
            sandbox_id=sandbox_id,
            agent_id=agent_id,
            run_id=run_id,
            workspace=workspace,
            status=SandboxStatus.IDLE,
            policy=policy or SandboxPolicy(),
            archive_path=archive,
            owner_user_id=int(user_id) if user_id is not None else None,
            name=name,
            created_at=now,
            updated_at=now,
        )
        self._sandboxes[sandbox_id] = sandbox
        self._write_metadata(sandbox)
        return sandbox

    # ------------------------------------------------------------------ lifecycle
    def save(self, sandbox: SandboxRef) -> None:
        """Persist the sandbox metadata after a file or lifecycle change."""
        self._write_metadata(sandbox)

    async def update_policy(self, sandbox_id: str, policy: SandboxPolicy,
                            agent_id: Optional[str] = None,
                            user_id: Optional[int] = None) -> SandboxRef:
        sandbox = self._get(sandbox_id, agent_id, user_id)
        sandbox.policy = policy
        sandbox.touch()
        self._write_metadata(sandbox)
        return sandbox

    async def delete(self, sandbox_id: str, agent_id: Optional[str] = None,
                     user_id: Optional[int] = None) -> None:
        sandbox = self._get(sandbox_id, agent_id, user_id)
        for job in [job for job in self._jobs.values() if job.sandbox_id == sandbox_id]:
            if job._process is not None and job._process.returncode is None:
                try:
                    job._process.kill()
                except ProcessLookupError:
                    pass
            if job._task is not None and not job._task.done():
                job._task.cancel()
            self._jobs.pop(job.job_id, None)
        shutil.rmtree(sandbox.workspace.parent, ignore_errors=True)
        if sandbox.archive_path:
            sandbox.archive_path.unlink(missing_ok=True)
        sandbox.status = SandboxStatus.DELETED
        sandbox.touch()
        self._sandboxes.pop(sandbox_id, None)
