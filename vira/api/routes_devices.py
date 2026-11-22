"""Device routes under /api/v1 (design 7.2-7.4)."""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from vira import errors
from vira.auth import auth, database
from vira.auth.principals import DevicePrincipal, UserPrincipal
from vira.devices import commands as command_store
from vira.devices import pairing as pairing_store
from vira.devices import consent as consent_store
from .deps import correlation_id_of


class DeviceRegisterRequest(BaseModel):
    display_name: str
    platform: str
    device_type: str
    os_version: Optional[str] = None
    client_version: Optional[str] = None
    capabilities: List[str] = []
    installation_id: Optional[str] = None


class DeviceUpdateRequest(BaseModel):
    display_name: Optional[str] = None


class RotateRequest(BaseModel):
    current_password: Optional[str] = None


class AccessGrantRequest(BaseModel):
    user_id: str            # users.public_id
    access_role: str = "viewer"


class PairRequest(BaseModel):
    code: str
    display_name: str
    platform: str
    device_type: str
    os_version: Optional[str] = None
    client_version: Optional[str] = None
    capabilities: List[str] = []
    installation_id: Optional[str] = None


class PairingCodeRequest(BaseModel):
    ttl_minutes: int = 10


class CommandRequest(BaseModel):
    kind: str
    payload: Dict[str, Any] = {}
    ttl_hours: int = 24


class CommandResultRequest(BaseModel):
    status: str = "completed"
    result: Any = None


class ConsentRequest(BaseModel):
    collector: str
    enabled: bool = True
    purpose: str = "device_insights"
    retention_hours: Optional[int] = None


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

    # ---------------- pairing ---------------- #
    @router.post("/devices/pairing-code", status_code=201)
    async def pairing_code(body: PairingCodeRequest, request: Request,
                           user: UserPrincipal = Depends(user_dep)):
        created = pairing_store.create_code(user.user_id, body.ttl_minutes)
        server = str(request.base_url).rstrip("/")
        payload = pairing_store.pairing_uri(server, created["code"])
        created.update({
            "server": server,
            "pairing_uri": payload,
            "qr_svg": pairing_store.qr_svg_data_uri(payload),
        })
        return created

    @router.post("/devices/pair", status_code=201)
    async def pair_device(body: PairRequest):
        try:
            created = pairing_store.redeem(
                body.code, body.display_name, body.platform, body.device_type,
                body.os_version, body.client_version, body.capabilities,
                installation_id=body.installation_id,
            )
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc), code="pairing_failed") from exc
        account = created["account"]
        # A single-use code created by an authenticated user is equivalent to a
        # one-time sign-in for the device being enrolled. The client needs a
        # session for chat, schedules and device management after pairing.
        session_id = auth.create_authenticated_session(
            {"id": account["user_id"]},
            kernel.config_manager.get("auth.session_max_age", 86400),
        )
        database.record_auth_audit(
            "pairing", "session.create", True,
            user_id=account["user_id"], session_id=session_id,
        )
        created["session_id"] = session_id
        return created

    # ---------------- user-facing device management ---------------- #
    @router.post("/devices", status_code=201)
    async def register_device(body: DeviceRegisterRequest, request: Request,
                              user: UserPrincipal = Depends(user_dep)):
        # Client-supplied id/owner/state/scope are not part of the contract.
        return svc().register_device(
            user, body.display_name, body.platform, body.device_type, body.os_version,
            body.client_version, body.capabilities, correlation_id_of(request),
            installation_id=body.installation_id)

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

    @router.get("/devices/{device_id}/consent")
    async def list_consent(device_id: str, user: UserPrincipal = Depends(user_dep)):
        kernel.device_service.authorize(user, device_id, roles=("owner", "operator"),
                                        allow_admin=True)
        return {"device_id": device_id, "consent": consent_store.list_for_device(device_id)}

    @router.put("/devices/{device_id}/consent")
    async def set_consent(device_id: str, body: ConsentRequest,
                          user: UserPrincipal = Depends(user_dep)):
        kernel.device_service.authorize(user, device_id, roles=("owner", "operator"),
                                        allow_admin=True)
        try:
            item = consent_store.set_consent(
                device_id, body.collector, body.enabled, body.purpose,
                body.retention_hours, user.user_id,
            )
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc), code="invalid_collector") from exc
        return {"device_id": device_id, "consent": item}

    @router.delete("/devices/{device_id}/consent/{collector}", status_code=204)
    async def revoke_consent(device_id: str, collector: str,
                             user: UserPrincipal = Depends(user_dep)):
        kernel.device_service.authorize(user, device_id, roles=("owner", "operator"),
                                        allow_admin=True)
        try:
            consent_store.set_consent(device_id, collector, False, user_id=user.user_id)
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc), code="invalid_collector") from exc
        return Response(status_code=204)

    @router.post("/devices/{device_id}/commands", status_code=201)
    async def create_command(device_id: str, body: CommandRequest,
                             user: UserPrincipal = Depends(user_dep)):
        kernel.device_service.authorize(user, device_id, roles=("owner", "operator"),
                                        allow_admin=True)
        try:
            return command_store.create(device_id, body.kind, body.payload,
                                        user.user_id, body.ttl_hours)
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc), code="invalid_command") from exc

    @router.get("/devices/{device_id}/commands")
    async def list_commands(device_id: str, limit: int = 50,
                            user: UserPrincipal = Depends(user_dep)):
        kernel.device_service.authorize(user, device_id, roles=("owner", "operator"),
                                        allow_admin=True)
        return {"commands": command_store.list_for_device(device_id, limit)}

    @router.get("/devices/{device_id}/commands/pending")
    async def pending_commands(device_id: str,
                               principal: DevicePrincipal = Depends(device_dep)):
        if principal.device_id != device_id:
            raise errors.Forbidden("Credential does not belong to this device",
                                   code="device_mismatch")
        return {"commands": command_store.claim_pending(device_id)}

    @router.post("/devices/{device_id}/commands/{command_id}/result")
    async def command_result(device_id: str, command_id: str,
                             body: CommandResultRequest,
                             principal: DevicePrincipal = Depends(device_dep)):
        if principal.device_id != device_id:
            raise errors.Forbidden("Credential does not belong to this device",
                                   code="device_mismatch")
        try:
            changed = command_store.complete(device_id, command_id, body.status, body.result)
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc), code="invalid_command") from exc
        if not changed:
            raise errors.NotFound("Command not found or already completed")
        return {"command_id": command_id, "status": body.status}

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
