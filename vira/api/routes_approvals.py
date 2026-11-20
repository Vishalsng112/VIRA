"""Human approval queue for destructive tool calls."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vira.auth import database
from vira.auth.principals import UserPrincipal
from vira.security import approvals


class ApprovalDecision(BaseModel):
    approved: bool
    note: Optional[str] = None


def build_approval_router(user_dep, admin_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/approvals")
    async def list_approvals(status: str = "pending", run_id: Optional[str] = None,
                             all: bool = False, limit: int = 100,
                             user: UserPrincipal = Depends(user_dep)):
        """Pending approvals for the caller. Administrators may pass ``all=true``."""
        show_all = bool(all and user.is_admin)
        return {
            "approvals": approvals.list_requests(
                None if show_all else user.user_id,
                status=status or None,
                run_id=run_id,
                limit=limit,
            )
        }

    @router.get("/admin/approvals")
    async def list_all_approvals(status: str = "pending", limit: int = 200,
                                 user: UserPrincipal = Depends(admin_dep)):
        return {"approvals": approvals.list_requests(
            None, status=status or None, limit=limit)}

    @router.post("/approvals/{approval_id}")
    async def decide_approval(approval_id: str, body: ApprovalDecision,
                              user: UserPrincipal = Depends(user_dep)):
        current = approvals.get_request(approval_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        if not user.is_admin and current.get("user_id") != user.user_id:
            raise HTTPException(status_code=404, detail="Approval not found")
        if current.get("status") != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Approval is already {current.get('status')}",
            )
        updated = approvals.decide(
            approval_id, body.approved, user.user_id, body.note)
        if updated is None:
            raise HTTPException(
                status_code=409,
                detail="Approval expired or was decided by another request",
            )
        database.record_auth_audit(
            "approval",
            "tool.approve" if body.approved else "tool.deny",
            bool(body.approved),
            user_id=user.user_id,
            resource=updated.get("tool_name"),
            details=f"approval={approval_id} status={updated.get('status')}",
            target=updated.get("run_id"),
        )
        return {"approval": updated}

    return router
