"""RAG document ingestion and local vector search."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.organizations import service as org_service
from vira.rag import service


class RagDocumentRequest(BaseModel):
    title: str
    content: str
    source: str = "manual"
    metadata: Dict[str, Any] = {}


def build_rag_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/rag")

    @router.post("/documents", status_code=201)
    async def ingest_document(
        body: RagDocumentRequest,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        if not body.title.strip() or not body.content.strip():
            raise errors.ValidationFailed("title and content are required")
        org_service.require_member(organization_id, user.user_id)
        return await service.ingest(user.user_id, body.title, body.content,
                                    body.source, body.metadata, organization_id)

    @router.get("/documents")
    async def list_documents(
        limit: int = 100,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        return {"documents": service.list_documents(user.user_id, limit, organization_id)}

    @router.delete("/documents/{document_id}", status_code=204)
    async def delete_document(
        document_id: str,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        if not service.delete_document(user.user_id, document_id, organization_id):
            raise errors.NotFound("Document not found")
        return Response(status_code=204)

    @router.get("/search")
    async def search(
        q: str, limit: int = 8, document_id: Optional[str] = None,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        if not q.strip():
            raise errors.ValidationFailed("q is required")
        org_service.require_member(organization_id, user.user_id)
        return {"results": await service.search(
            user.user_id, q, limit, document_id, organization_id)}

    return router
