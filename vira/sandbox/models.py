"""Data models for the VIRA sandbox subsystem.

A sandbox is a long-lived, owner-scoped workspace backed by a private Linux
filesystem namespace (Bubblewrap).  These models describe its policy, lifecycle
and background jobs.  They are deliberately plain dataclasses so they can be
serialized to ``metadata.json`` and restored after a server restart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SandboxStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    DELETED = "deleted"
    ERROR = "error"


class JobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    KILLED = "killed"


@dataclass(frozen=True)
class SandboxPolicy:
    """Execution limits and capabilities for one sandbox.

    Policies are immutable.  To change one, create a new sandbox or use
    :meth:`vira.sandbox.manager.SandboxManager.update_policy`, which replaces the
    stored policy atomically.
    """

    network_enabled: bool = False
    timeout_seconds: int = 900
    max_processes: int = 128
    cpu_seconds: int = 600
    memory_mb: int = 2048
    allow_package_install: bool = True
    allow_shell: bool = True
    workspace_quota_mb: int = 2048
    max_output_bytes: int = 200_000
    #: "bubblewrap" is isolated; "host" runs in the shared workspace with the
    #: host toolchain (admin/workspace setting only, never model-controlled).
    execution_mode: str = "bubblewrap"
    #: Extra host PATH entries prepended for host mode / exposed in bubblewrap.
    extra_path: str = ""

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 86_400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        if self.max_processes <= 0:
            raise ValueError("max_processes must be positive")
        if self.cpu_seconds <= 0:
            raise ValueError("cpu_seconds must be positive")
        if self.memory_mb <= 0:
            raise ValueError("memory_mb must be positive")
        if self.workspace_quota_mb <= 0:
            raise ValueError("workspace_quota_mb must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if self.execution_mode not in ("bubblewrap", "host"):
            raise ValueError("execution_mode must be 'bubblewrap' or 'host'")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "network_enabled": self.network_enabled,
            "timeout_seconds": self.timeout_seconds,
            "max_processes": self.max_processes,
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "allow_package_install": self.allow_package_install,
            "allow_shell": self.allow_shell,
            "workspace_quota_mb": self.workspace_quota_mb,
            "max_output_bytes": self.max_output_bytes,
            "execution_mode": self.execution_mode,
            "extra_path": self.extra_path,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SandboxPolicy":
        data = data or {}
        allowed = set(cls.__dataclass_fields__.keys())
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class SandboxRef:
    sandbox_id: str
    agent_id: str
    run_id: Optional[str]
    workspace: Path
    workspace_id: Optional[str] = None
    status: SandboxStatus = SandboxStatus.CREATED
    policy: SandboxPolicy = field(default_factory=SandboxPolicy)
    archive_path: Optional[Path] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    owner_user_id: Optional[int] = None
    name: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_used_at: Optional[str] = None
    execution_count: int = 0

    def touch(self) -> None:
        self.updated_at = utc_now()
        self.last_used_at = self.updated_at


@dataclass
class SandboxJob:
    job_id: str
    sandbox_id: str
    command: str
    status: JobStatus = JobStatus.RUNNING
    exit_code: Optional[int] = None
    started_at: str = field(default_factory=utc_now)
    ended_at: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    pid: Optional[int] = None
    _process: Any = field(default=None, repr=False, compare=False)
    _task: Any = field(default=None, repr=False, compare=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "sandbox_id": self.sandbox_id,
            "command": self.command,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "truncated": self.truncated,
            "pid": self.pid,
        }
