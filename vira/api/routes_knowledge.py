"""Scoped knowledge base API.

This is the human-facing counterpart of the ``knowledge_search`` /
``knowledge_write`` agent tools.  Both go through ``vira.knowledge.service`` so
scoping and promotion policy stay in one place.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.knowledge import consolidation, policy, service
from vira.organizations import service as org_service


class KnowledgeWriteRequest(BaseModel):
    content: str
    kind: str = "fact"
    scope: Optional[str] = None
    requested_by_user: bool = True
    agent_role: Optional[str] = None
    summary: Optional[str] = None
    confidence: float = 0.5
    importance: float = 0.0
    tags: List[str] = []


class KnowledgePromoteRequest(BaseModel):
    target_scope: str = "global"
    force: bool = False


class KnowledgeCorrectRequest(BaseModel):
    content: str
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    kind: Optional[str] = None


def build_knowledge_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/knowledge")

    @router.post("/items", status_code=201)
    async def write_item(
        body: KnowledgeWriteRequest,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        if not body.content.strip():
            raise errors.ValidationFailed("content is required")
        org_service.require_member(organization_id, user.user_id)
        try:
            return await service.write(
                body.content,
                user_id=user.user_id,
                kind=body.kind,
                scope=body.scope,
                requested_by_user=body.requested_by_user,
                agent_role=body.agent_role,
                organization_id=organization_id,
                summary=body.summary,
                confidence=body.confidence,
                importance=body.importance,
                tags=body.tags,
            )
        except (ValueError, PermissionError) as exc:
            raise errors.ValidationFailed(str(exc))

    @router.get("/items")
    async def list_items(
        scope: Optional[str] = None,
        limit: int = 100,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        if scope and scope not in policy.ALL_SCOPES:
            raise errors.ValidationFailed("unknown scope")
        return {"items": service.get_store().list_items(
            user_id=user.user_id, organization_id=organization_id,
            scope=scope, limit=limit)}

    @router.get("/search")
    async def search(
        q: str,
        limit: int = 8,
        agent_role: Optional[str] = None,
        conversation_id: Optional[str] = None,
        include_documents: bool = True,
        include_memories: bool = True,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        if not q.strip():
            raise errors.ValidationFailed("q is required")
        org_service.require_member(organization_id, user.user_id)
        return {"results": await service.search(
            q, user_id=user.user_id, agent_role=agent_role,
            conversation_id=conversation_id, organization_id=organization_id,
            limit=limit, include_documents=include_documents,
            include_memories=include_memories)}

    @router.get("/stats")
    async def stats(
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        return consolidation.inspect()

    @router.get("/items/{item_id}")
    async def get_item(
        item_id: str,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        item = service.get_store().get(item_id)
        if item is None:
            raise errors.NotFound("Knowledge item not found")
        owned = item.get("user_id") == user.user_id
        in_org = bool(organization_id and item.get("organization_id") == organization_id)
        if item.get("scope") != "global" and not (owned or in_org):
            raise errors.NotFound("Knowledge item not found")
        return item

    @router.get("/items/{item_id}/revisions")
    async def revisions(
        item_id: str,
        user: UserPrincipal = Depends(user_dep),
    ):
        chain = service.revisions(item_id)
        if not chain:
            raise errors.NotFound("Knowledge item not found")
        return {"revisions": chain}

    @router.patch("/items/{item_id}")
    async def correct_item(
        item_id: str,
        body: KnowledgeCorrectRequest,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        if not body.content.strip():
            raise errors.ValidationFailed("content is required")
        org_service.require_member(organization_id, user.user_id)
        try:
            return await service.correct(
                item_id,
                body.content,
                user_id=user.user_id,
                summary=body.summary,
                tags=body.tags,
                kind=body.kind,
                organization_id=organization_id,
            )
        except (ValueError, PermissionError) as exc:
            raise errors.ValidationFailed(str(exc))

    @router.post("/items/{item_id}/promote", status_code=201)
    async def promote(
        item_id: str,
        body: KnowledgePromoteRequest,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        if body.target_scope == "global" and not user.is_admin:
            raise errors.ValidationFailed("only admins may promote to global knowledge")
        try:
            return await service.promote(
                item_id, target_scope=body.target_scope,
                actor=user.username, organization_id=organization_id,
                force=bool(body.force and user.is_admin))
        except (ValueError, PermissionError) as exc:
            raise errors.ValidationFailed(str(exc))

    @router.delete("/items/{item_id}", status_code=204)
    async def delete_item(
        item_id: str,
        user: UserPrincipal = Depends(user_dep),
    ):
        item = service.get_store().get(item_id)
        if item is None:
            raise errors.NotFound("Knowledge item not found")
        owned = item.get("user_id") == user.user_id
        if not owned and not user.is_admin:
            raise errors.NotFound("Knowledge item not found")
        service.get_store().delete(item_id)
        return Response(status_code=204)

    return router
