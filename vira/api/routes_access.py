"""Read-only access-provider status and guided Tailscale setup."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from vira.access import access_status
from vira.access.tailscale_setup import TailscaleController


class TailscaleConnectRequest(BaseModel):
    auth_key: Optional[str] = Field(default=None, repr=False, max_length=512)
    hostname: Optional[str] = Field(default=None, max_length=63)


def build_access_router(kernel, deps: dict) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    user_dep = deps["get_current_user"]
    admin_dep = deps["require_admin"]
    tailscale = TailscaleController()

    @router.get("/access")
    async def get_access(request: Request, user=Depends(user_dep)):
        return await asyncio.to_thread(
            access_status, request, kernel.config_manager.get_all()
        )

    @router.get("/access/tailscale")
    async def get_tailscale(user=Depends(admin_dep)):
        return await asyncio.to_thread(
            tailscale.status, kernel.config_manager.get_all()
        )

    @router.post("/access/tailscale/connect")
    async def connect_tailscale(body: TailscaleConnectRequest,
                                user=Depends(admin_dep)):
        return await asyncio.to_thread(
            tailscale.connect,
            kernel.config_manager.get_all(),
            body.auth_key,
            body.hostname,
        )

    return router
