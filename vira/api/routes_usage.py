"""Cost/quota dashboard and administrator quota management."""
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.llm import usage
from vira.organizations import service as org_service


class QuotaRequest(BaseModel):
    scope: str = "user"
    subject_id: str
    period: str = "month"
    token_limit: Optional[int] = None
    cost_limit_usd: Optional[float] = None


def build_usage_router(admin_dep, user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/usage/summary")
    async def my_usage(
        days: int = 30,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        data = usage.summary(user.user_id, days, organization_id, is_admin=False)
        quota_rows = usage.list_quotas()
        mine = []
        for quota in quota_rows:
            if quota["scope"] == "user" and str(quota["subject_id"]) != str(user.user_id):
                continue
            if quota["scope"] == "org" and str(quota["subject_id"]) != str(organization_id or ""):
                continue
            current = usage.usage_for_quota(quota["scope"], str(quota["subject_id"]), quota["period"])
            mine.append({**quota, "current": current})
        data["quotas"] = mine
        return data

    @router.get("/admin/usage")
    async def admin_usage(
        days: int = 30,
        user_id: Optional[int] = None,
        organization_id: Optional[str] = None,
        actor: UserPrincipal = Depends(admin_dep),
    ):
        if user_id is not None:
            return usage.summary(user_id, days, organization_id, is_admin=False)
        return usage.summary(None, days, organization_id, is_admin=True)

    @router.get("/admin/quotas")
    async def list_quotas(actor: UserPrincipal = Depends(admin_dep)):
        rows = usage.list_quotas()
        for row in rows:
            row["current"] = usage.usage_for_quota(
                row["scope"], str(row["subject_id"]), row["period"])
        return {"quotas": rows}

    @router.put("/admin/quotas")
    async def set_quota(body: QuotaRequest, actor: UserPrincipal = Depends(admin_dep)):
        if body.scope == "org":
            org_service.require_member(body.subject_id, actor.user_id)
        return {"quota": usage.set_quota(
            body.scope, body.subject_id, body.period,
            body.token_limit, body.cost_limit_usd)}

    @router.delete("/admin/quotas/{quota_id}", status_code=204)
    async def delete_quota(quota_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not usage.delete_quota(quota_id):
            raise errors.NotFound("Quota not found")
        return Response(status_code=204)

    return router
