"""Shared workspace API.

Workspaces are directories users can open on the host.  Agents attach their
sandboxes to them, so several agents can work on the same project.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.workspace import get_service


class WorkspaceCreateRequest(BaseModel):
    name: str
    path: Optional[str] = None
    execution_mode: Optional[str] = None


class WorkspaceUpdateRequest(BaseModel):
    execution_mode: str


def build_workspace_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/workspaces")

    @router.get("")
    async def list_workspaces(user: UserPrincipal = Depends(user_dep)):
        return {"workspaces": get_service().list(user.user_id)}

    @router.post("", status_code=201)
    async def create_workspace(body: WorkspaceCreateRequest,
                               user: UserPrincipal = Depends(user_dep)):
        if body.execution_mode and body.execution_mode not in ("bubblewrap", "host"):
            raise errors.ValidationFailed("execution_mode must be bubblewrap or host")
        try:
            return get_service().resolve(
                body.path or body.name, user.user_id,
                execution_mode=body.execution_mode)
        except (ValueError, PermissionError) as exc:
            raise errors.ValidationFailed(str(exc))

    @router.patch("/{workspace_id}")
    async def update_workspace(workspace_id: str, body: WorkspaceUpdateRequest,
                               user: UserPrincipal = Depends(user_dep)):
        if body.execution_mode not in ("bubblewrap", "host"):
            raise errors.ValidationFailed("execution_mode must be bubblewrap or host")
        try:
            record = get_service().get(workspace_id, user.user_id)
            return get_service().resolve(
                record["path"], user.user_id,
                execution_mode=body.execution_mode)
        except (ValueError, PermissionError) as exc:
            raise errors.ValidationFailed(str(exc))

    return router
