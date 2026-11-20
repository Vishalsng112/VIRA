"""Object storage API for attachments, exports and large artifacts."""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.organizations import service as org_service
from vira.storage import service


class ObjectList(BaseModel):
    pass


def build_storage_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/objects")

    @router.post("", status_code=201)
    async def upload_object(
        file: UploadFile = File(...),
        key: Optional[str] = Form(None),
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        content = await file.read()
        try:
            record = await service.put(
                content,
                content_type=file.content_type or "application/octet-stream",
                user_id=user.user_id,
                organization_id=organization_id,
                object_key=key,
                metadata={"filename": file.filename or key or "upload"},
            )
        except ValueError as exc:
            raise errors.PayloadTooLarge(str(exc))
        return {"object": record}

    @router.get("")
    async def list_objects(
        limit: int = 100,
        organization_id: Optional[str] = Header(None, alias="X-Organization-ID"),
        user: UserPrincipal = Depends(user_dep),
    ):
        org_service.require_member(organization_id, user.user_id)
        return {"objects": service.list_objects(
            user.user_id, organization_id, min(max(limit, 1), 500), user.is_admin)}

    @router.get("/{object_id}")
    async def download_object(object_id: str, user: UserPrincipal = Depends(user_dep)):
        record = service.get_record(object_id)
        if record is None or not service.can_access(record, user.user_id, user.is_admin):
            raise errors.NotFound("Object not found")
        content = await service.read(record)
        filename = record.get("metadata", {}).get("filename") or object_id
        return Response(
            content=content,
            media_type=record.get("content_type") or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                "X-Object-SHA256": record.get("sha256", ""),
            },
        )

    @router.delete("/{object_id}", status_code=204)
    async def delete_object(object_id: str, user: UserPrincipal = Depends(user_dep)):
        record = service.get_record(object_id)
        if record is None or not service.can_access(record, user.user_id, user.is_admin):
            raise errors.NotFound("Object not found")
        await service.delete(object_id)
        return Response(status_code=204)

    return router
