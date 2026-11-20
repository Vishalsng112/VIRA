"""Approval-gated generated tools and agents."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from vira import errors
from vira.auth import database
from vira.auth.principals import UserPrincipal
from vira.generated import service, store


class GeneratedCreateRequest(BaseModel):
    kind: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    spec: Dict[str, Any] = {}


class GeneratedRejectRequest(BaseModel):
    reason: str = ""


class GeneratedRunRequest(BaseModel):
    task: str
    device_id: Optional[str] = None


def build_generated_router(kernel, user_dep, admin_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/generated")

    def _visible(artifact: Dict[str, Any], user: UserPrincipal) -> bool:
        return (
            user.is_admin
            or artifact.get("created_by_user_id") == user.user_id
            or artifact.get("status") in ("approved", "enabled")
        )

    def _sync():
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        registry = getattr(orchestrator, "tool_registry", None) if orchestrator else None
        return service.sync_registry(registry)

    @router.post("", status_code=201)
    async def create_generated(body: GeneratedCreateRequest,
                               user: UserPrincipal = Depends(user_dep)):
        try:
            artifact = service.create_draft(
                kind=body.kind, name=body.name, version=body.version,
                description=body.description, spec=body.spec,
                created_by_user_id=user.user_id,
            )
        except service.GeneratedError as exc:
            raise errors.ValidationFailed(str(exc)) from exc
        database.record_auth_audit(
            "generated", "generated.create", True, user_id=user.user_id,
            resource=f"generated:{artifact['id']}",
            details=f"kind={artifact['kind']} name={artifact['name']} status=draft",
        )
        return {"artifact": artifact}

    @router.get("")
    async def list_generated(kind: Optional[str] = None, status: Optional[str] = None,
                             limit: int = 100,
                             user: UserPrincipal = Depends(user_dep)):
        rows = store.list_artifacts(kind, status, limit)
        return {"artifacts": [row for row in rows if _visible(row, user)]}

    @router.get("/{artifact_id}")
    async def get_generated(artifact_id: str, user: UserPrincipal = Depends(user_dep)):
        artifact = store.get(artifact_id)
        if not artifact or not _visible(artifact, user):
            raise errors.NotFound("Generated artifact not found")
        return {"artifact": artifact}

    @router.post("/{artifact_id}/approve")
    async def approve_generated(artifact_id: str,
                                actor: UserPrincipal = Depends(admin_dep)):
        try:
            artifact = service.approve(artifact_id, actor.user_id)
        except service.GeneratedError as exc:
            raise errors.Conflict(str(exc)) from exc
        database.record_auth_audit(
            "generated", "generated.approve", True, user_id=actor.user_id,
            resource=f"generated:{artifact_id}", details="status=approved",
        )
        return {"artifact": artifact}

    @router.post("/{artifact_id}/reject")
    async def reject_generated(artifact_id: str, body: GeneratedRejectRequest,
                               actor: UserPrincipal = Depends(admin_dep)):
        try:
            artifact = service.reject(artifact_id, body.reason)
        except service.GeneratedError as exc:
            raise errors.Conflict(str(exc)) from exc
        database.record_auth_audit(
            "generated", "generated.reject", False, user_id=actor.user_id,
            resource=f"generated:{artifact_id}",
            details=f"status=rejected reason={body.reason[:200]}",
        )
        return {"artifact": artifact}

    @router.post("/{artifact_id}/enable")
    async def enable_generated(artifact_id: str,
                               actor: UserPrincipal = Depends(admin_dep)):
        try:
            artifact = service.enable(artifact_id)
        except service.GeneratedError as exc:
            raise errors.Conflict(str(exc)) from exc
        registered = _sync()
        database.record_auth_audit(
            "generated", "generated.enable", True, user_id=actor.user_id,
            resource=f"generated:{artifact_id}",
            details=f"status=enabled registered={','.join(registered)[:500]}",
        )
        return {"artifact": artifact, "registered_tools": registered}

    @router.post("/{artifact_id}/disable")
    async def disable_generated(artifact_id: str,
                                actor: UserPrincipal = Depends(admin_dep)):
        try:
            artifact = service.disable(artifact_id)
        except service.GeneratedError as exc:
            raise errors.Conflict(str(exc)) from exc
        _sync()
        database.record_auth_audit(
            "generated", "generated.disable", True, user_id=actor.user_id,
            resource=f"generated:{artifact_id}", details="status=disabled",
        )
        return {"artifact": artifact}

    @router.post("/{artifact_id}/run")
    async def run_generated(artifact_id: str, body: GeneratedRunRequest,
                            user: UserPrincipal = Depends(user_dep)):
        artifact = store.get(artifact_id)
        if not artifact or not _visible(artifact, user):
            raise errors.NotFound("Generated artifact not found")
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        runtime = getattr(orchestrator, "runtime", None) if orchestrator else None
        if runtime is None:
            raise errors.ServiceUnavailable("agent runtime unavailable")
        try:
            result = await service.run_agent(
                artifact, body.task, runtime,
                user_id=user.user_id, device_id=body.device_id,
            )
        except service.GeneratedError as exc:
            raise errors.Forbidden(str(exc), code="generated_not_enabled") from exc
        database.record_auth_audit(
            "generated", "generated.run", True, user_id=user.user_id,
            resource=f"generated:{artifact_id}",
            details=f"kind={artifact['kind']} stopped={result.get('stopped')}",
        )
        return result

    return router
