"""User-scoped proactive agent schedules and onboarding catalog."""
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from vira.agent import schedules
from vira.agent.recipes import get_recommended, list_recommended


class ScheduleCreate(BaseModel):
    agent_id: str
    name: str = Field(..., min_length=1, max_length=160)
    message: str = Field(..., min_length=1)
    schedule_type: str = "daily"
    time_of_day: Optional[str] = "08:00"
    weekday: Optional[int] = None
    interval_minutes: Optional[int] = None
    timezone: str = "UTC"
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    channels: List[str] = ["inapp"]
    task_profile: Dict[str, Any] = Field(default_factory=dict)
    input: Dict[str, Any] = Field(default_factory=dict)
    organization_id: Optional[str] = None
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    agent_id: Optional[str] = None
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    message: Optional[str] = Field(None, min_length=1)
    schedule_type: Optional[str] = None
    time_of_day: Optional[str] = None
    weekday: Optional[int] = None
    interval_minutes: Optional[int] = None
    timezone: Optional[str] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    channels: Optional[List[str]] = None
    task_profile: Optional[Dict[str, Any]] = None
    input: Optional[Dict[str, Any]] = None
    organization_id: Optional[str] = None
    enabled: Optional[bool] = None


def _check_timezone(name: str) -> str:
    try:
        ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, f"unknown timezone: {name}")
    return name or "UTC"


def _channels(values: Optional[List[str]]) -> List[str]:
    allowed = {"inapp", "webhook"}
    chosen = [str(value) for value in (values or ["inapp"]) if str(value) in allowed]
    return chosen or ["inapp"]


def _validate(body: ScheduleCreate) -> None:
    try:
        schedules.validate_schedule_fields(
            body.schedule_type, body.time_of_day, body.weekday,
            body.interval_minutes)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc))
    _check_timezone(body.timezone)


def build_schedule_router(user_dep, kernel) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def orchestrator():
        return getattr(kernel, "agent_orchestrator", None)

    async def _agent_exists(agent_id: str) -> bool:
        orch = orchestrator()
        registry = getattr(orch, "registry", None) if orch else None
        if registry is None:
            return True  # no runtime in lightweight deployments/tests
        if await registry.get_instance(agent_id) is not None:
            return True
        target = agent_id.lower()
        for metadata in await registry.list_agents():
            if target in {metadata.agent_id.lower(), metadata.name.lower()}:
                return True
        return False

    @router.get("/agent-recipes")
    async def recipes(user=Depends(user_dep)):
        return {"agents": list_recommended()}

    @router.get("/agent-recipes/{recipe_id}")
    async def recipe(recipe_id: str, user=Depends(user_dep)):
        item = get_recommended(recipe_id)
        if not item:
            raise HTTPException(404, "Agent recipe not found")
        return item

    @router.get("/agent-schedules/agents")
    async def installed_agents(user=Depends(user_dep)):
        orch = orchestrator()
        registry = getattr(orch, "registry", None) if orch else None
        items = []
        if registry is not None:
            for metadata in await registry.list_agents():
                items.append({
                    "id": metadata.agent_id,
                    "name": metadata.name,
                    "description": metadata.description,
                    "architecture": metadata.architecture,
                    "enabled": metadata.enabled,
                    "schedulable": True,
                })
        return {"agents": items}

    @router.get("/agent-schedules/status")
    async def scheduler_status(user=Depends(user_dep)):
        orch = orchestrator()
        scheduler = getattr(orch, "proactive_scheduler", None) if orch else None
        return {
            "available": scheduler is not None,
            "scheduler": scheduler.status() if scheduler else {"running": False},
        }

    @router.get("/agent-schedules")
    async def list_schedules(enabled: Optional[bool] = None,
                             user=Depends(user_dep)):
        return {"schedules": schedules.list_schedules(user.user_id, enabled)}

    @router.post("/agent-schedules", status_code=201)
    async def create_schedule(body: ScheduleCreate, user=Depends(user_dep)):
        _validate(body)
        if not await _agent_exists(body.agent_id):
            raise HTTPException(422, f"agent not installed: {body.agent_id}")
        return schedules.create_schedule(
            user.user_id, body.agent_id, body.name, body.message,
            schedule_type=body.schedule_type,
            time_of_day=body.time_of_day,
            weekday=body.weekday,
            interval_minutes=body.interval_minutes,
            timezone_name=_check_timezone(body.timezone),
            quiet_hours_start=body.quiet_hours_start,
            quiet_hours_end=body.quiet_hours_end,
            channels=_channels(body.channels),
            task_profile=body.task_profile,
            input_data=body.input,
            organization_id=body.organization_id,
            enabled=body.enabled,
        )

    @router.patch("/agent-schedules/{schedule_id}")
    async def update_schedule(schedule_id: str, body: ScheduleUpdate,
                              user=Depends(user_dep)):
        existing = schedules.get_schedule(schedule_id, user.user_id)
        if not existing:
            raise HTTPException(404, "Schedule not found")
        changes = body.model_dump(exclude_unset=True)
        if "agent_id" in changes and not await _agent_exists(changes["agent_id"]):
            raise HTTPException(422, f"agent not installed: {changes['agent_id']}")
        if "timezone" in changes:
            changes["timezone"] = _check_timezone(changes["timezone"])
        if "channels" in changes:
            changes["channels"] = _channels(changes["channels"])
        # The store validates type-specific fields on the merged result.
        try:
            updated = schedules.update_schedule(
                schedule_id, user.user_id, **changes)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        if not updated:
            raise HTTPException(404, "Schedule not found")
        return updated

    @router.delete("/agent-schedules/{schedule_id}", status_code=204)
    async def delete_schedule(schedule_id: str, user=Depends(user_dep)):
        if not schedules.delete_schedule(schedule_id, user.user_id):
            raise HTTPException(404, "Schedule not found")
        return Response(status_code=204)

    @router.post("/agent-schedules/{schedule_id}/run")
    async def run_now(schedule_id: str, user=Depends(user_dep)):
        orch = orchestrator()
        if orch is not None and getattr(orch, "proactive_scheduler", None) is None:
            raise HTTPException(503, "Proactive scheduler is disabled")
        item = schedules.run_now(schedule_id, user.user_id)
        if not item:
            existing = schedules.get_schedule(schedule_id, user.user_id)
            if not existing:
                raise HTTPException(404, "Schedule not found")
            raise HTTPException(409, "Schedule is disabled")
        return {"status": "queued", "schedule": item}

    @router.get("/agent-schedules/{schedule_id}/runs")
    async def schedule_runs(schedule_id: str, limit: int = 50,
                            user=Depends(user_dep)):
        if not schedules.get_schedule(schedule_id, user.user_id):
            raise HTTPException(404, "Schedule not found")
        return {"runs": schedules.list_runs(schedule_id, user.user_id, limit)}

    @router.get("/agent-schedules/{schedule_id}/runs/{run_id}")
    async def schedule_run_detail(schedule_id: str, run_id: str,
                                  user=Depends(user_dep)):
        run = schedules.get_run(run_id, schedule_id, user.user_id)
        if not run:
            raise HTTPException(404, "Schedule run not found")
        from vira.agent_runtime.run_store import timeline
        return {"run": run, "timeline": timeline(run.get("run_id") or "")}

    return router
