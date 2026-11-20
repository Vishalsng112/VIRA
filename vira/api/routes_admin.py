"""Administrator routes: user lifecycle, fleet view, audit (design 7.2)."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from vira import errors
from vira.auth import database
from vira.security.redaction import redact
from vira.auth.admin import UserAdminService
from vira.auth.principals import UserPrincipal
from vira.devices import store as device_store
from vira.jobs import queue as jobs
from vira.ops.backup import create_backup, list_backups
from vira.family import store as family_store
from .deps import correlation_id_of


class UserCreateRequest(BaseModel):
    username: str
    role: str = "user"
    password: Optional[str] = None  # omitted -> a one-time temporary password is generated


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


def build_admin_router(kernel, deps: dict, stream_manager) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    admin = deps["require_admin"]
    users = UserAdminService()

    @router.get("/admin/users")
    async def list_users(limit: int = 50, cursor: Optional[str] = None,
                         include_deleted: bool = False, actor: UserPrincipal = Depends(admin)):
        return users.list_users(actor, limit, cursor, include_deleted)

    @router.post("/admin/users", status_code=201)
    async def create_user(body: UserCreateRequest, request: Request,
                          actor: UserPrincipal = Depends(admin)):
        import asyncio
        result = await asyncio.to_thread(
            users.create_user, actor, body.username, body.role, body.password,
            correlation_id_of(request))
        # New active admins own the server device.
        if kernel.local_device:
            kernel.local_device.sync_access()
        # New household users join the administrator's first family by default.
        # The admin can later change their household role through household APIs.
        household = family_store.ensure_household(actor.user_id)
        target = database.get_user_by_public_id(result["user_id"])
        if target:
            family_store.add_member(actor.user_id, household["id"], int(target["id"]), "adult")
        return result

    @router.get("/admin/users/{user_public_id}")
    async def get_user(user_public_id: str, actor: UserPrincipal = Depends(admin)):
        return users.get_user(actor, user_public_id)

    @router.patch("/admin/users/{user_public_id}")
    async def update_user(user_public_id: str, body: UserUpdateRequest, request: Request,
                          actor: UserPrincipal = Depends(admin)):
        result = users.update_user(actor, user_public_id, body.role, body.status,
                                   correlation_id_of(request))
        target = database.get_user_by_public_id(user_public_id)
        if target and target["status"] != "active":
            stream_manager.disconnect_user(int(target["id"]))
        if kernel.local_device:
            kernel.local_device.sync_access()
        stream_manager.invalidate_access()
        return result

    @router.delete("/admin/users/{user_public_id}", status_code=204)
    async def delete_user(user_public_id: str, request: Request,
                          actor: UserPrincipal = Depends(admin)):
        target = database.get_user_by_public_id(user_public_id)
        users.delete_user(actor, user_public_id, correlation_id_of(request))
        if target:
            stream_manager.disconnect_user(int(target["id"]))
        stream_manager.invalidate_access()
        return Response(status_code=204)

    @router.get("/admin/devices")
    async def fleet(limit: int = 50, cursor: Optional[str] = None,
                    actor: UserPrincipal = Depends(admin)):
        """Fleet inventory and health: metadata only, never raw event payloads."""
        return kernel.device_service.list_fleet(actor, limit, cursor)

    @router.get("/admin/audit")
    async def audit(limit: int = 100, before_id: Optional[int] = None,
                    actor: UserPrincipal = Depends(admin)):
        return {"audit": database.list_audit(limit, before_id)}

    @router.get("/admin/diagnostics")
    async def diagnostics(limit: int = 100, actor: UserPrincipal = Depends(admin)):
        """Opt-in client diagnostic reports, redacted at ingestion."""
        rows = database.list_audit_by_type("client_diagnostic", limit)
        for row in rows:
            row["details"] = redact(row.get("details"))
        return {"diagnostics": rows}

    @router.get("/admin/audit/export")
    async def export_audit(format: str = "json", kind: str = "all",
                           limit: int = 1000, since: Optional[str] = None,
                           until: Optional[str] = None,
                           actor: UserPrincipal = Depends(admin)):
        """Redacted audit/tool-call export for administrators.

        ``format`` is ``json`` or ``csv``; ``kind`` is ``audit``, ``tool_calls``
        or ``all``. Secret-looking keys and token-shaped values are replaced
        before serialization. Session hashes and raw payloads are not exported.
        """
        if format.lower() not in ("json", "csv"):
            raise errors.ValidationFailed("format must be json or csv")
        if kind.lower() not in ("audit", "tool_calls", "all"):
            raise errors.ValidationFailed("kind must be audit, tool_calls or all")

        rows = []
        if kind.lower() in ("audit", "all"):
            rows += [
                {**redact(row), "export_kind": "audit"}
                for row in database.list_audit_export(limit, since, until)
            ]
        if kind.lower() in ("tool_calls", "all"):
            rows += [
                {**redact(row), "export_kind": "tool_call"}
                for row in database.list_tool_calls_export(limit, since, until)
            ]
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)

        database.record_auth_audit(
            "audit", "audit.export", True, user_id=actor.user_id,
            details=f"kind={kind.lower()} format={format.lower()} rows={len(rows)}",
        )
        if format.lower() == "csv":
            buffer = io.StringIO()
            fieldnames = sorted({key for row in rows for key in row})
            writer = csv.DictWriter(buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    key: json.dumps(value, default=str) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                })
            return Response(
                buffer.getvalue(), media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=vira-audit.csv"},
            )
        return JSONResponse(
            {"exported_at": datetime.now(timezone.utc).isoformat(),
             "kind": kind.lower(), "count": len(rows), "rows": rows},
            headers={"Content-Disposition": "attachment; filename=vira-audit.json"},
        )

    @router.get("/admin/jobs")
    async def job_status(status: Optional[str] = None, limit: int = 100,
                         actor: UserPrincipal = Depends(admin)):
        return {"stats": jobs.stats(), "jobs": jobs.list_jobs(status, limit)}

    @router.post("/admin/jobs/{job_id}/retry")
    async def retry_job(job_id: str, actor: UserPrincipal = Depends(admin)):
        return {"job_id": job_id, "retried": jobs.retry(job_id)}

    @router.get("/admin/backups")
    async def backups(actor: UserPrincipal = Depends(admin)):
        return {"backups": [str(path) for path in list_backups()]}

    @router.post("/admin/backups", status_code=201)
    async def backup_now(actor: UserPrincipal = Depends(admin)):
        return {"backup": str(create_backup())}

    @router.get("/admin/fleet/ops")
    async def fleet_ops(actor: UserPrincipal = Depends(admin)):
        now = datetime.now(timezone.utc)
        stale_cutoff = (now - timedelta(days=7)).isoformat()
        expiring_cutoff = (now + timedelta(days=7)).isoformat()
        with database.get_connection() as conn:
            stale = [dict(row) for row in conn.execute(
                "SELECT id, display_name, platform, last_seen_at FROM devices "
                "WHERE status = 'active' AND (last_seen_at IS NULL OR last_seen_at < ?)",
                (stale_cutoff,),
            ).fetchall()]
            expiring = [dict(row) for row in conn.execute(
                "SELECT device_id, expires_at FROM device_credentials "
                "WHERE revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at <= ?",
                (expiring_cutoff,),
            ).fetchall()]
            commands = conn.execute(
                "SELECT status, COUNT(*) AS c FROM device_commands GROUP BY status"
            ).fetchall()
            missing_consent = conn.execute(
                "SELECT COUNT(*) AS c FROM devices d WHERE d.status = 'active' "
                "AND NOT EXISTS (SELECT 1 FROM device_consents c WHERE c.device_id = d.id)"
            ).fetchone()["c"]
        return {
            "stale_devices": stale,
            "expiring_credentials": expiring,
            "commands": {row["status"]: int(row["c"]) for row in commands},
            "devices_without_explicit_consent": int(missing_consent),
        }

    @router.get("/ops/alerts")
    async def alerts(actor: UserPrincipal = Depends(admin)):
        counts = database.outbox_counts()
        job_stats = jobs.stats()
        devices = device_store.health_summary()
        alerts = []
        if counts.get("dead_letter", 0):
            alerts.append({"level": "error", "kind": "outbox",
                           "message": f"{counts['dead_letter']} dead-letter event(s)"})
        if counts.get("pending", 0) > 1000:
            alerts.append({"level": "warning", "kind": "outbox",
                           "message": f"{counts['pending']} pending outbox event(s)"})
        if job_stats.get("dead", 0):
            alerts.append({"level": "error", "kind": "jobs",
                           "message": f"{job_stats['dead']} dead job(s)"})
        if job_stats.get("pending", 0) > 100:
            alerts.append({"level": "warning", "kind": "jobs",
                           "message": f"{job_stats['pending']} pending job(s)"})
        stale = [d for d in devices.get("devices", []) if d.get("status") == "active"
                 and not d.get("last_seen_at")]
        if stale:
            alerts.append({"level": "warning", "kind": "devices",
                           "message": f"{len(stale)} active device(s) never seen"})
        return {"alerts": alerts, "counts": counts, "jobs": job_stats}

    @router.get("/ops/devices/health")
    async def devices_health(actor: UserPrincipal = Depends(admin)):
        summary = device_store.health_summary()
        summary["outbox"] = database.outbox_counts()
        summary["stream_subscribers"] = stream_manager.subscriber_count
        return summary

    return router
