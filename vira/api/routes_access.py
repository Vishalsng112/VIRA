"""Read-only access-provider status and guided Tailscale setup."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from vira.access import access_status
from vira.access.cloudflare_setup import CloudflareController
from vira.access.tailscale_setup import TailscaleController


class TailscaleConnectRequest(BaseModel):
    auth_key: Optional[str] = Field(default=None, repr=False, max_length=512)
    hostname: Optional[str] = Field(default=None, max_length=63)


class CloudflareConnectRequest(BaseModel):
    hostname: str
    tunnel_name: Optional[str] = Field(default=None, max_length=63)


def build_access_router(kernel, deps: dict) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    user_dep = deps["get_current_user"]
    admin_dep = deps["require_admin"]
    tailscale = TailscaleController()
    cloudflare = CloudflareController()

    def save_cloudflare(result: dict) -> None:
        public_url = result.get("public_url")
        if not public_url:
            return
        updated = kernel.config_manager.get_all()
        access = updated.setdefault("access", {})
        cloud = access.setdefault("cloudflare", {})
        cloud["public_url"] = public_url
        cloud["hostname"] = result.get("hostname") or public_url.removeprefix("https://")
        if result.get("tunnel_name"):
            cloud["tunnel_name"] = result["tunnel_name"]
        if result.get("tunnel_id"):
            cloud["tunnel_id"] = result["tunnel_id"]
        kernel.config_manager.save(updated)

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

    @router.get("/access/cloudflare")
    async def get_cloudflare(user=Depends(admin_dep)):
        return await asyncio.to_thread(
            cloudflare.status, kernel.config_manager.get_all()
        )

    @router.post("/access/cloudflare/login")
    async def login_cloudflare(user=Depends(admin_dep)):
        return await asyncio.to_thread(
            cloudflare.login, kernel.config_manager.get_all()
        )

    @router.post("/access/cloudflare/connect")
    async def connect_cloudflare(body: CloudflareConnectRequest,
                                 user=Depends(admin_dep)):
        result = await asyncio.to_thread(
            cloudflare.connect,
            kernel.config_manager.get_all(),
            body.hostname,
            body.tunnel_name,
        )
        save_cloudflare(result)
        return result

    return router
