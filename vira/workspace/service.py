"""Resolve and register workspace directories.

Resolution rules:

* a plain name (``coffee-shop``) lives under ``workspace.root``;
* an absolute path or ``~`` path is used as-is when
  ``workspace.allow_user_paths`` is true (default), so users can point agents at
  an existing project on their machine;
* when no workspace is requested, every agent for a user shares
  ``<root>/user-<id>``.  This is the behaviour that lets several agents work on
  the same project.

The workspace is the durable thing; sandboxes attach to it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from . import store

_SLUG = re.compile(r"[^a-zA-Z0-9_.-]+")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_FORBIDDEN_PATHS = {
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot",
    "/sys", "/proc", "/dev", "/root", "/var", "/var/lib", "/run",
}


def _load_settings() -> Dict[str, Any]:
    try:
        import yaml
        data = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
        section = data.get("workspace") or {}
        return dict(section) if isinstance(section, dict) else {}
    except (OSError, ValueError, ImportError):
        return {}


def slugify(value: str, fallback: str = "workspace") -> str:
    value = _SLUG.sub("-", (value or "").strip()).strip(".-")
    return value[:64] or fallback


class WorkspaceService:
    def __init__(self, root: Optional[str] = None,
                 allow_user_paths: Optional[bool] = None,
                 default_execution_mode: Optional[str] = None):
        settings = _load_settings()
        self.root = Path(
            root or settings.get("root") or "~/VIRA/workspaces"
        ).expanduser().resolve()
        self.allow_user_paths = (
            bool(settings.get("allow_user_paths", True))
            if allow_user_paths is None else bool(allow_user_paths))
        self.default_execution_mode = (
            default_execution_mode or settings.get("default_execution_mode")
            or "bubblewrap")

    # ------------------------------------------------------------------ paths
    def _inside_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _target(self, target: Optional[str], user_id: Optional[int]) -> tuple[str, Path]:
        raw = (target or "").strip()
        if not raw:
            raw = f"user-{user_id}" if user_id is not None else "system"
        looks_like_path = (
            raw.startswith("~") or raw.startswith("/")
            or "/" in raw or "\\" in raw
        )
        if looks_like_path:
            path = Path(raw).expanduser().resolve()
            if path == Path("/") or any(
                    path == Path(forbidden) or Path(forbidden) in path.parents
                    for forbidden in _FORBIDDEN_PATHS):
                raise PermissionError("workspace path points at a system directory")
            if not self.allow_user_paths and not self._inside_root(path):
                raise PermissionError(
                    "workspace.allow_user_paths is false; use a name under "
                    f"{self.root}")
            return slugify(path.name), path
        name = slugify(raw)
        return name, (self.root / name).resolve()

    def resolve(self, target: Optional[str], user_id: Optional[int], *,
                execution_mode: Optional[str] = None,
                organization_id: Optional[str] = None,
                create: bool = True) -> Dict[str, Any]:
        raw = (target or "").strip()
        if raw and _UUID.match(raw):
            record = store.get(raw)
            if record is not None:
                if record.get("owner_user_id") not in (None, user_id):
                    raise PermissionError("workspace belongs to another user")
                if execution_mode and execution_mode != record["execution_mode"]:
                    record = store.upsert(
                        name=record["name"], path=record["path"],
                        owner_user_id=record.get("owner_user_id"),
                        organization_id=record.get("organization_id"),
                        execution_mode=execution_mode,
                        metadata=record.get("metadata") or {})
                return record
        name, path = self._target(target, user_id)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        record = store.find_by_path(str(path))
        if record is not None and record.get("owner_user_id") not in (None, user_id):
            raise PermissionError("workspace path belongs to another user")
        if record is None:
            record = store.find_by_name(name, user_id)
            if record is not None and Path(record["path"]) != path:
                record = None
        mode = (execution_mode or (record or {}).get("execution_mode")
                or self.default_execution_mode)
        if record is None or record["path"] != str(path) or record["execution_mode"] != mode:
            record = store.upsert(
                name=name, path=str(path), owner_user_id=user_id,
                organization_id=organization_id, execution_mode=mode,
                metadata={"user_visible": True})
        return record

    def get(self, workspace_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        record = store.get(workspace_id)
        if record is None:
            raise ValueError("workspace not found")
        if user_id is not None and record.get("owner_user_id") not in (None, user_id):
            raise PermissionError("workspace belongs to another user")
        return record

    def list(self, user_id: int, limit: int = 100) -> list[Dict[str, Any]]:
        return store.list_for_user(user_id, limit)

    def default(self, user_id: Optional[int]) -> Dict[str, Any]:
        return self.resolve(None, user_id)

    def touch(self, record: Dict[str, Any]) -> None:
        Path(record["path"]).mkdir(parents=True, exist_ok=True)


_service: Optional[WorkspaceService] = None


def get_service() -> WorkspaceService:
    global _service
    if _service is None:
        _service = WorkspaceService()
    return _service


def resolve_workspace(target: Optional[str], user_id: Optional[int], **kwargs) -> Dict[str, Any]:
    return get_service().resolve(target, user_id, **kwargs)
