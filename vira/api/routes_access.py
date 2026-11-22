"""Read-only access-provider status for the dashboard."""
import asyncio

from fastapi import APIRouter, Depends, Request

from vira.access import access_status


def build_access_router(kernel, deps: dict) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    user_dep = deps["get_current_user"]

    @router.get("/access")
    async def get_access(request: Request, user=Depends(user_dep)):
        return await asyncio.to_thread(
            access_status, request, kernel.config_manager.get_all()
        )

    return router
