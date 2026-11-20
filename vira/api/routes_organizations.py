"""Organization / team management."""
from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.organizations import service


class OrganizationCreate(BaseModel):
    name: str


class OrganizationUpdate(BaseModel):
    name: str


class MemberAdd(BaseModel):
    user_id: int
    role: str = "member"


class MemberUpdate(BaseModel):
    role: str


def build_organization_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.get("")
    async def list_organizations(user: UserPrincipal = Depends(user_dep)):
        return {"organizations": service.list_for_user(user.user_id)}

    @router.post("", status_code=201)
    async def create_organization(body: OrganizationCreate,
                                  user: UserPrincipal = Depends(user_dep)):
        return {"organization": service.create(user.user_id, body.name)}

    @router.get("/{org_id}")
    async def get_organization(org_id: str, user: UserPrincipal = Depends(user_dep)):
        org = service.get(org_id)
        if org is None or not service.is_member(org_id, user.user_id):
            raise errors.NotFound("Organization not found")
        return {"organization": org}

    @router.patch("/{org_id}")
    async def update_organization(org_id: str, body: OrganizationUpdate,
                                  user: UserPrincipal = Depends(user_dep)):
        return {"organization": service.update(org_id, user.user_id, body.name)}

    @router.delete("/{org_id}", status_code=204)
    async def delete_organization(org_id: str, user: UserPrincipal = Depends(user_dep)):
        if not service.delete(org_id, user.user_id):
            raise errors.NotFound("Organization not found")
        return Response(status_code=204)

    @router.post("/{org_id}/members", status_code=201)
    async def add_member(org_id: str, body: MemberAdd,
                         user: UserPrincipal = Depends(user_dep)):
        return {"organization": service.add_member(
            org_id, user.user_id, body.user_id, body.role)}

    @router.patch("/{org_id}/members/{user_id}")
    async def update_member(org_id: str, user_id: int, body: MemberUpdate,
                            user: UserPrincipal = Depends(user_dep)):
        return {"organization": service.update_member(
            org_id, user.user_id, user_id, body.role)}

    @router.delete("/{org_id}/members/{user_id}", status_code=204)
    async def remove_member(org_id: str, user_id: int,
                            user: UserPrincipal = Depends(user_dep)):
        if not service.remove_member(org_id, user.user_id, user_id):
            raise errors.NotFound("Member not found")
        return Response(status_code=204)

    return router
