"""Notification queue and push-token endpoints."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import DevicePrincipal, UserPrincipal
from vira import notifications


class PushRegistration(BaseModel):
    platform: str
    token: str


def build_notification_router(user_dep, device_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/notifications")
    async def list_notifications(limit: int = 100, unread_only: bool = False,
                                 user: UserPrincipal = Depends(user_dep)):
        return {"notifications": notifications.list_for_user(
            user.user_id, limit, unread_only)}

    @router.post("/notifications/{notification_id}/read", status_code=204)
    async def read_notification(notification_id: str,
                                user: UserPrincipal = Depends(user_dep)):
        if not notifications.mark_read(user.user_id, notification_id):
            raise errors.NotFound("Notification not found")
        return Response(status_code=204)

    @router.post("/devices/{device_id}/push-registration", status_code=204)
    async def register_push(device_id: str, body: PushRegistration,
                            principal: DevicePrincipal = Depends(device_dep)):
        if principal.device_id != device_id:
            raise errors.Forbidden("Credential does not belong to this device",
                                   code="device_mismatch")
        notifications.register_push_token(device_id, body.platform, body.token)
        return Response(status_code=204)

    return router
