"""Account data export and deletion endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from vira import errors
from vira.account.data import delete_user_data, export_user
from vira.auth import auth, database
from vira.auth.principals import UserPrincipal
from vira import errors as vira_errors


class DeleteAccountRequest(BaseModel):
    confirm: str


def build_account_router(user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/account")

    @router.post("/export")
    async def export_account(user: UserPrincipal = Depends(user_dep)):
        return export_user(user)

    @router.post("/data/delete")
    async def delete_data(user: UserPrincipal = Depends(user_dep)):
        return delete_user_data(user, delete_devices=False)

    @router.delete("")
    async def delete_account(body: DeleteAccountRequest,
                             user: UserPrincipal = Depends(user_dep)):
        record = database.get_user_by_id(user.user_id) or {}
        if body.confirm != record.get("username"):
            raise errors.ValidationFailed("Type your username to confirm", code="confirmation_required")
        if user.is_admin:
            with database.get_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin' AND status != 'deleted'"
                ).fetchone()
            if int(row["cnt"]) <= 1:
                raise vira_errors.Conflict(
                    "Cannot delete the last administrator", code="last_admin")
        counts = delete_user_data(user, delete_devices=True)
        try:
            database.change_user_state(user.user_id, status="deleted")
        except database.LastAdminError as exc:
            raise errors.Conflict(str(exc), code="last_admin") from exc
        return {"status": "deleted", "counts": counts}

    return router
