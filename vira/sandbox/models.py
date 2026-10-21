from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional


class SandboxStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass(frozen=True)
class SandboxPolicy:
    network_enabled: bool = False
    timeout_seconds: int = 900
    max_processes: int = 128
    cpu_seconds: int = 600
    memory_mb: int = 2048
    allow_package_install: bool = True

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 86_400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        if self.max_processes <= 0:
            raise ValueError("max_processes must be positive")
        if self.cpu_seconds <= 0:
            raise ValueError("cpu_seconds must be positive")
        if self.memory_mb <= 0:
            raise ValueError("memory_mb must be positive")


@dataclass
class SandboxRef:
    sandbox_id: str
    agent_id: str
    run_id: Optional[str]
    workspace: Path
    status: SandboxStatus = SandboxStatus.CREATED
    policy: SandboxPolicy = field(default_factory=SandboxPolicy)
    archive_path: Optional[Path] = None
    metadata: Dict[str, str] = field(default_factory=dict)
