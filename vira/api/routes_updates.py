"""Update channel API: releases plus client/server update checks."""
from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from vira import errors
from vira import __version__ as SERVER_VERSION
from vira.auth.principals import UserPrincipal
from vira.updates import service


class ReleaseRequest(BaseModel):
    product: str = "client"
    channel: str = "stable"
    version: str
    notes: str = ""
    url: str = ""
    checksum: Optional[str] = None
    min_version: Optional[str] = None


def build_update_router(admin_dep, user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/updates")

    @router.get("/check")
    async def check_update(
        product: str = "client",
        channel: str = "stable",
        current_version: Optional[str] = None,
        user: UserPrincipal = Depends(user_dep),
    ):
        if product == "server" and not current_version:
            current_version = SERVER_VERSION
        if not current_version:
            raise errors.ValidationFailed("current_version is required")
        return service.check(product, channel, current_version)

    @router.get("/releases")
    async def list_releases(product: Optional[str] = None, channel: Optional[str] = None,
                            limit: int = 100,
                            user: UserPrincipal = Depends(user_dep)):
        return {"releases": service.list_releases(product, channel, limit)}

    @router.post("/releases", status_code=201)
    async def publish_release(body: ReleaseRequest,
                              actor: UserPrincipal = Depends(admin_dep)):
        return {"release": service.publish(
            body.product, body.channel, body.version, body.notes,
            body.url, body.checksum, body.min_version, actor.user_id)}

    @router.delete("/releases/{release_id}", status_code=204)
    async def delete_release(release_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not service.delete(release_id):
            raise errors.NotFound("Release not found")
        return Response(status_code=204)

    return router
