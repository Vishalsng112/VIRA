"""Versioned endpoints consumed by the Flutter family client."""
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from vira.auth.principals import UserPrincipal
from vira.family import store


class HouseholdCreate(BaseModel):
    name: str


class MemberUpdate(BaseModel):
    role: str


class SyncPush(BaseModel):
    device_id: str | None = None
    household_id: str
    ops: List[Dict[str, Any]]


def build_client_router(user_dep, kernel) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/client-config")
    async def client_config():
        return {"protocol": {"current": 1, "min_supported": 1},
                "server": {"id": "local-vira", "name": "VIRA", "version": "0.3.0"},
                "limits": {"max_note_bytes": 102400, "max_ops_per_push": 200, "max_changes_per_page": 500},
                "features": {"attachments": False, "push": False, "chat_grounding": True}}

    @router.get("/households")
    async def households(user: UserPrincipal = Depends(user_dep)):
        return {"items": store.list_households(user.user_id), "next_cursor": None}

    @router.get("/households/{household_id}")
    async def household_detail(household_id: str, user: UserPrincipal = Depends(user_dep)):
        items = [item for item in store.list_households(user.user_id)
                 if item["id"] == household_id]
        if not items:
            raise HTTPException(404, "Household not found")
        return items[0]

    @router.get("/households/{household_id}/members")
    async def household_members(household_id: str, user: UserPrincipal = Depends(user_dep)):
        try:
            return {"items": store.members(user.user_id, household_id)}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.patch("/households/{household_id}/members/{member_public_id}")
    async def update_household_member(household_id: str, member_public_id: str,
                                      body: MemberUpdate,
                                      user: UserPrincipal = Depends(user_dep)):
        try:
            store.update_member(user.user_id, household_id, member_public_id, body.role)
            return {"status": "updated"}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/households/{household_id}/notebooks")
    async def household_notebooks(household_id: str, user: UserPrincipal = Depends(user_dep)):
        try:
            return {"items": store.notebooks(user.user_id, household_id)}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.post("/households", status_code=201)
    async def create_household(body: HouseholdCreate, user: UserPrincipal = Depends(user_dep)):
        if not body.name.strip():
            raise HTTPException(422, "name is required")
        return store.ensure_household(user.user_id, body.name.strip()[:120])

    @router.get("/workspace")
    async def workspace_summary(user: UserPrincipal = Depends(user_dep)):
        """Safe workspace status available to every signed-in VIRA user."""
        orchestrator = getattr(kernel, "agent_orchestrator", None)
        registry = getattr(orchestrator, "registry", None) if orchestrator else None
        agents = []
        if registry is not None:
            for metadata in await registry.list_agents():
                agents.append({
                    "id": metadata.agent_id,
                    "name": metadata.name,
                    "description": metadata.description,
                    "state": metadata.state.value,
                    "enabled": metadata.enabled,
                })
        scheduler = getattr(orchestrator, "runtime_scheduler", None)
        running_tasks = getattr(scheduler, "_running_tasks", {}) if scheduler else {}
        return {
            "server": {
                "status": "healthy" if kernel.is_running() else "unhealthy",
                "version": "0.3.0",
            },
            "agents": agents,
            "scheduler": {
                "running_tasks": len(running_tasks),
            },
        }

    @router.get("/sync/changes")
    async def sync_changes(household_id: str, cursor: int = 0, limit: int = 500,
                           user: UserPrincipal = Depends(user_dep)):
        try:
            return store.changes(user.user_id, household_id, cursor, limit)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.post("/sync/push")
    async def sync_push(body: SyncPush, user: UserPrincipal = Depends(user_dep)):
        try:
            return store.push(user.user_id, body.household_id, body.ops)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @router.get("/sync/wait")
    async def sync_wait(household_id: str, cursor: int = 0, timeout: int = 25,
                        user: UserPrincipal = Depends(user_dep)):
        timeout = min(max(timeout, 0), 30)
        for _ in range(timeout):
            current = store.changes(user.user_id, household_id, cursor, 1)
            if current["changes"]:
                return {"latest_seq": current["next_cursor"], "changed": True}
            import asyncio
            await asyncio.sleep(1)
        return {"latest_seq": cursor, "changed": False}

    return router
