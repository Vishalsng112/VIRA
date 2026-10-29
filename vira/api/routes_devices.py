"""Device routes under /api/v1 (design 7.2-7.4)."""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import DevicePrincipal, UserPrincipal
from .deps import correlation_id_of


class DeviceRegisterRequest(BaseModel):
    display_name: str
    platform: str
    device_type: str
    os_version: Optional[str] = None
    client_version: Optional[str] = None
    capabilities: List[str] = []


class DeviceUpdateRequest(BaseModel):
    display_name: Optional[str] = None


class RotateRequest(BaseModel):
    current_password: Optional[str] = None


class AccessGrantRequest(BaseModel):
    user_id: str            # users.public_id
    access_role: str = "viewer"


class HeartbeatRequest(BaseModel):
    client_version: Optional[str] = None
    os_version: Optional[str] = None
    capabilities: Optional[List[str]] = None
    capability_status: Optional[Dict[str, str]] = None
    queue_backlog: Optional[int] = None


def build_device_router(kernel, deps: dict, stream_manager) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    user_dep = deps["get_current_user"]
    device_dep = deps["get_device_principal"]

    def svc():
        return kernel.device_service

    # ---------------- user-facing device management ---------------- #
    @router.post("/devices", status_code=201)
    async def register_device(body: DeviceRegisterRequest, request: Request,
                              user: UserPrincipal = Depends(user_dep)):
        # Client-supplied id/owner/state/scope are not part of the contract.
        return svc().register_device(
            user, body.display_name, body.platform, body.device_type, body.os_version,
            body.client_version, body.capabilities, correlation_id_of(request))

    @router.get("/devices")
    async def list_devices(limit: int = 50, cursor: Optional[str] = None,
                           user: UserPrincipal = Depends(user_dep)):
        return svc().list_devices(user, limit, cursor)

    @router.get("/devices/{device_id}")
    async def get_device(device_id: str, user: UserPrincipal = Depends(user_dep)):
        return svc().get_device(user, device_id)

    @router.patch("/devices/{device_id}")
    async def update_device(device_id: str, body: DeviceUpdateRequest, request: Request,
                            user: UserPrincipal = Depends(user_dep)):
        return svc().update_device(user, device_id, body.display_name, correlation_id_of(request))

    @router.post("/devices/{device_id}/credentials:rotate")
    async def rotate_credential(device_id: str, body: RotateRequest, request: Request,
                                user: UserPrincipal = Depends(user_dep)):
        return await asyncio.to_thread(
            svc().rotate_credential, user, device_id, body.current_password,
            correlation_id_of(request))

    @router.post("/devices/{device_id}/revoke", status_code=204)
    async def revoke_device(device_id: str, request: Request,
                            user: UserPrincipal = Depends(user_dep)):
        svc().revoke_device(user, device_id, correlation_id_of(request))
        stream_manager.invalidate_access()
        return Response(status_code=204)

    @router.post("/devices/{device_id}/retire", status_code=204)
    async def retire_device(device_id: str, request: Request,
                            user: UserPrincipal = Depends(user_dep)):
        svc().retire_device(user, device_id, correlation_id_of(request))
        stream_manager.invalidate_access()
        return Response(status_code=204)

    @router.post("/devices/{device_id}/access", status_code=201)
    async def grant_access(device_id: str, body: AccessGrantRequest, request: Request,
                           user: UserPrincipal = Depends(user_dep)):
        result = svc().grant_access(user, device_id, body.user_id, body.access_role,
                                    correlation_id_of(request))
        stream_manager.invalidate_access()
        return result

    @router.delete("/devices/{device_id}/access/{user_public_id}", status_code=204)
    async def revoke_access(device_id: str, user_public_id: str, request: Request,
                            user: UserPrincipal = Depends(user_dep)):
        svc().revoke_access(user, device_id, user_public_id, correlation_id_of(request))
        stream_manager.invalidate_access()
        return Response(status_code=204)

    @router.get("/devices/{device_id}/events")
    async def list_events(device_id: str, request: Request, limit: int = 50,
                          cursor: Optional[str] = None, event_type: Optional[str] = None,
                          include_payload: bool = False,
                          user: UserPrincipal = Depends(user_dep)):
        return svc().list_events(user, device_id, limit, cursor, event_type,
                                 include_payload, correlation_id_of(request))

    @router.get("/devices/{device_id}/state")
    async def latest_state(device_id: str, user: UserPrincipal = Depends(user_dep)):
        return svc().latest_state(user, device_id)

    # ---------------- device-authenticated endpoints ---------------- #
    @router.post("/devices/{device_id}/heartbeat")
    async def heartbeat(device_id: str, body: HeartbeatRequest, request: Request,
                        principal: DevicePrincipal = Depends(device_dep)):
        if not principal.has_scope("heartbeat"):
            raise errors.Forbidden("Credential lacks heartbeat scope", code="missing_scope")
        return svc().heartbeat(
            principal, device_id, body.client_version, body.os_version, body.capabilities,
            body.capability_status, body.queue_backlog, correlation_id_of(request))

    @router.post("/devices/{device_id}/events:batch")
    async def ingest_batch(device_id: str, request: Request,
                           principal: DevicePrincipal = Depends(device_dep)):
        policy = svc().policy
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > policy.max_batch_bytes * 2:
            raise errors.PayloadTooLarge("Request body too large", code="batch_too_large")
        try:
            body: Any = await request.json()
        except Exception:
            raise errors.ValidationFailed("Body must be valid JSON", code="invalid_json")
        events = body.get("events") if isinstance(body, dict) else None
        return await kernel.ingestion_service.ingest(
            principal, device_id, events, correlation_id_of(request))

    return router
