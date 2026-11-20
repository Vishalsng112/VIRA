"""Device insight summaries for the dashboard, clients and future agents."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.devices import store as device_store
from vira.insights.rollup import list_daily
from vira.insights.service import summarize_device


def build_insights_router(kernel, user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/insights")

    def _summary(user: UserPrincipal, device_id: str, days: int):
        device, role = kernel.device_service.authorize(
            user, device_id, allow_admin=True)
        result = summarize_device(device_id, days)
        result["device"] = {
            "device_id": device["id"],
            "display_name": device["display_name"],
            "platform": device.get("platform"),
            "device_type": device.get("device_type"),
            "status": device.get("status"),
            "access_role": role,
        }
        return result

    @router.get("/summary")
    async def summary(device_id: str, days: int = 7,
                      user: UserPrincipal = Depends(user_dep)):
        return _summary(user, device_id, days)

    @router.get("/daily")
    async def daily(device_id: str, days: int = 7,
                    user: UserPrincipal = Depends(user_dep)):
        kernel.device_service.authorize(user, device_id, allow_admin=True)
        return {"device_id": device_id, "days": days, "daily": list_daily(device_id, days)}

    @router.get("/context")
    async def context(device_id: str, days: int = 7,
                      user: UserPrincipal = Depends(user_dep)):
        data = _summary(user, device_id, days)
        return {
            "device_id": device_id,
            "days": data["days"],
            "summary": data["summary"],
            "focus": data["focus"],
            "top_apps": data["top_apps"][:5],
            "warnings": data["health"].get("warnings", []),
            "generated_at": data["generated_at"],
        }

    @router.get("/fleet")
    async def fleet(user: UserPrincipal = Depends(user_dep)):
        if not user.is_admin:
            raise errors.Forbidden("Administrator role required", code="admin_required")
        health = device_store.health_summary()
        devices = []
        for item in health["devices"]:
            latest = {row["event_type"]: row["payload"]
                      for row in device_store.get_latest_state(item["id"])}
            battery = latest.get("device.battery.state") or {}
            devices.append({
                **item,
                "battery_level": battery.get("level_percent"),
                "charging": battery.get("charging"),
            })
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "by_status": health["by_status"],
            "devices": devices,
        }

    return router
