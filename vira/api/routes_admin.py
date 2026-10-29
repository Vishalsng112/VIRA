"""Administrator routes: user lifecycle, fleet view, audit (design 7.2)."""
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from vira.auth import database
from vira.auth.admin import UserAdminService
from vira.auth.principals import UserPrincipal
from vira.devices import store as device_store
from .deps import correlation_id_of


class UserCreateRequest(BaseModel):
    username: str
    role: str = "user"
    password: Optional[str] = None  # omitted -> a one-time temporary password is generated


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


def build_admin_router(kernel, deps: dict, stream_manager) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    admin = deps["require_admin"]
    users = UserAdminService()

    @router.get("/admin/users")
    async def list_users(limit: int = 50, cursor: Optional[str] = None,
                         include_deleted: bool = False, actor: UserPrincipal = Depends(admin)):
        return users.list_users(actor, limit, cursor, include_deleted)

    @router.post("/admin/users", status_code=201)
    async def create_user(body: UserCreateRequest, request: Request,
                          actor: UserPrincipal = Depends(admin)):
        import asyncio
        result = await asyncio.to_thread(
            users.create_user, actor, body.username, body.role, body.password,
            correlation_id_of(request))
        # New active admins own the server device.
        if kernel.local_device:
            kernel.local_device.sync_access()
        return result

    @router.get("/admin/users/{user_public_id}")
    async def get_user(user_public_id: str, actor: UserPrincipal = Depends(admin)):
        return users.get_user(actor, user_public_id)

    @router.patch("/admin/users/{user_public_id}")
    async def update_user(user_public_id: str, body: UserUpdateRequest, request: Request,
                          actor: UserPrincipal = Depends(admin)):
        result = users.update_user(actor, user_public_id, body.role, body.status,
                                   correlation_id_of(request))
        target = database.get_user_by_public_id(user_public_id)
        if target and target["status"] != "active":
            stream_manager.disconnect_user(int(target["id"]))
        if kernel.local_device:
            kernel.local_device.sync_access()
        stream_manager.invalidate_access()
        return result

    @router.delete("/admin/users/{user_public_id}", status_code=204)
    async def delete_user(user_public_id: str, request: Request,
                          actor: UserPrincipal = Depends(admin)):
        target = database.get_user_by_public_id(user_public_id)
        users.delete_user(actor, user_public_id, correlation_id_of(request))
        if target:
            stream_manager.disconnect_user(int(target["id"]))
        stream_manager.invalidate_access()
        return Response(status_code=204)

    @router.get("/admin/devices")
    async def fleet(limit: int = 50, cursor: Optional[str] = None,
                    actor: UserPrincipal = Depends(admin)):
        """Fleet inventory and health: metadata only, never raw event payloads."""
        return kernel.device_service.list_fleet(actor, limit, cursor)

    @router.get("/admin/audit")
    async def audit(limit: int = 100, before_id: Optional[int] = None,
                    actor: UserPrincipal = Depends(admin)):
        return {"audit": database.list_audit(limit, before_id)}

    @router.get("/ops/devices/health")
    async def devices_health(actor: UserPrincipal = Depends(admin)):
        summary = device_store.health_summary()
        summary["outbox"] = database.outbox_counts()
        summary["stream_subscribers"] = stream_manager.subscriber_count
        return summary

    return router
