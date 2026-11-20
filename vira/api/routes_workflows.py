"""Durable workflow API: create, inspect, replay, resume and cancel."""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from vira import errors
from vira.agent_orchestration import workflow_store as store
from vira.agent_orchestration.workflow import Workflow, WorkflowStatus, WorkflowStep
from vira.auth.principals import UserPrincipal
from vira.organizations import service as org_service


class WorkflowCreate(BaseModel):
    name: str
    context: Dict[str, Any] = {}
    steps: List[WorkflowStep]


def build_workflow_router(kernel, user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/workflows")

    def engine():
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        value = getattr(orchestrator, "workflow_engine", None) if orchestrator else None
        if value is None:
            raise errors.ServiceUnavailable("workflow engine unavailable", code="workflow_unavailable")
        return value

    def owned(workflow_id: str, user: UserPrincipal):
        workflow = store.load(workflow_id)
        if not workflow:
            raise errors.NotFound("Workflow not found")
        if user.is_admin or workflow.created_by_user_id == user.user_id:
            return workflow
        if workflow.organization_id and org_service.is_member(
            workflow.organization_id, user.user_id
        ):
            return workflow
        raise errors.NotFound("Workflow not found")

    @router.post("", status_code=201)
    async def create_workflow(
        body: WorkflowCreate,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        workflow = Workflow(
            id=str(uuid.uuid4()),
            name=body.name,
            steps=body.steps,
            context=body.context,
            created_by_user_id=user.user_id,
            organization_id=organization_id,
        )
        eng = engine()
        await eng.create(workflow, user.user_id)
        await eng.start(workflow.id)
        return {"workflow": store.load(workflow.id)}

    @router.get("")
    async def list_workflows(
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        return {"workflows": store.list_workflows(
            user.user_id, user.is_admin, organization_id=organization_id)}

    @router.get("/{workflow_id}")
    async def get_workflow(workflow_id: str, user: UserPrincipal = Depends(user_dep)):
        return {"workflow": owned(workflow_id, user)}

    @router.post("/{workflow_id}/resume")
    async def resume_workflow(workflow_id: str, retry_failed: bool = False,
                              user: UserPrincipal = Depends(user_dep)):
        owned(workflow_id, user)
        return {"workflow": await engine().resume(workflow_id, retry_failed)}

    @router.post("/{workflow_id}/cancel")
    async def cancel_workflow(workflow_id: str, user: UserPrincipal = Depends(user_dep)):
        owned(workflow_id, user)
        await engine().cancel(workflow_id)
        return {"workflow": store.load(workflow_id)}

    @router.get("/{workflow_id}/replay")
    async def replay_workflow(workflow_id: str, user: UserPrincipal = Depends(user_dep)):
        workflow = owned(workflow_id, user)
        return {"workflow": workflow, "events": store.list_events(workflow_id)}

    return router
