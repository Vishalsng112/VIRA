"""Proactive agent scheduler integrated with the agent orchestrator.

The scheduler owns no second runtime: it resolves agents from the existing
``AgentRegistry`` and executes through ``RuntimeScheduler.run_task`` so scheduled
runs get the same identity, lifecycle, tools, approvals, progress events and
error handling as chat runs.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.agent import schedules
from vira.agent.base import TaskRequest
from vira.agent_runtime import run_store
from vira.auth import database
from vira.notifications import create as create_notification


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_device_id(user_id: int) -> Optional[str]:
    """Prefer the user's most recently active client device.

    Agents otherwise fall back to the server-local device and answer with
    runtime metrics instead of the user's phone or desktop telemetry.
    """
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM devices "
            "WHERE created_by_user_id = ? AND status = 'active' "
            "AND is_server_local = 0 "
            "ORDER BY COALESCE(last_seen_at, created_at) DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            return row["id"]
        row = conn.execute(
            "SELECT id FROM devices WHERE is_server_local = 1 "
            "AND status = 'active' ORDER BY last_seen_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None


class ProactiveScheduler:
    """Claim due schedules and run their agents with bounded concurrency."""

    def __init__(self, registry, runtime_scheduler, *,
                 config: Optional[Dict[str, Any]] = None,
                 notification_config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self._registry = registry
        self._runtime_scheduler = runtime_scheduler
        self._notification_config = notification_config or {}
        self.tick_seconds = max(5.0, float(config.get("tick_seconds", 20)))
        self.max_concurrent = max(1, min(int(config.get("max_concurrent", 2)), 10))
        self.max_runs_per_tick = max(1, min(int(config.get("max_runs_per_tick", 10)), 100))
        self.lock_seconds = max(60, int(config.get("lock_seconds", 300)))
        self.run_timeout_seconds = max(
            10, int(config.get("run_timeout_seconds", 240)))
        # A run must finish well before its claim lock expires.
        self.lock_seconds = max(self.lock_seconds, self.run_timeout_seconds + 60)
        self.notify_on_error = bool(config.get("notify_on_error", True))
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active: set = set()
        self._last_tick: Optional[str] = None
        self._runs = 0
        self._failures = 0
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Proactive agent scheduler started (tick={}s)", self.tick_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        for task in list(self._active):
            task.cancel()
        if self._active:
            await asyncio.gather(*list(self._active), return_exceptions=True)
        self._active.clear()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Proactive scheduler tick failed")
            await asyncio.sleep(self.tick_seconds)

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_tick": self._last_tick,
            "runs": self._runs,
            "failures": self._failures,
            "active": len(self._active),
            "max_concurrent": self.max_concurrent,
            "tick_seconds": self.tick_seconds,
        }

    # --------------------------------------------------------------- execution
    async def run_due(self, now: Optional[datetime] = None) -> int:
        """Claim due schedules and start their runs without blocking the tick."""
        due = schedules.claim_due(
            limit=self.max_runs_per_tick, lock_seconds=self.lock_seconds, now=now)
        self._last_tick = _now_iso()
        for schedule in due:
            task = asyncio.create_task(self._bounded_run(schedule))
            self._active.add(task)
            task.add_done_callback(self._active.discard)
        return len(due)

    async def drain(self) -> None:
        """Wait for currently active scheduled runs (used by tests and shutdown)."""
        while self._active:
            await asyncio.gather(*list(self._active), return_exceptions=True)

    async def _bounded_run(self, schedule: Dict[str, Any]) -> None:
        async with self._semaphore:
            try:
                await self._execute(schedule)
            except Exception:
                logger.exception("Scheduled agent run failed for {}", schedule.get("id"))

    async def _resolve_agent(self, reference: str):
        instance = await self._registry.get_instance(reference)
        if instance is not None:
            return instance
        target = str(reference or "").lower()
        for metadata in await self._registry.list_agents():
            names = {metadata.agent_id.lower(), metadata.name.lower()}
            if target in names:
                return await self._registry.get_instance(metadata.agent_id)
        return None

    async def _execute(self, schedule: Dict[str, Any]) -> None:
        schedule_id = schedule["id"]
        scheduled_for = schedule.get("next_run_at")
        started_at = _now_iso()
        run_id = str(uuid.uuid4())
        agent = await self._resolve_agent(schedule["agent_id"])
        if agent is None:
            error = f"agent not found: {schedule['agent_id']}"
            self._failures += 1
            self._notify(schedule, scheduled_for, None, error)
            schedules.record_run(
                schedule_id, int(schedule["user_id"]), agent_id=schedule["agent_id"],
                run_id=run_id, scheduled_for=scheduled_for, status="error",
                error=error, started_at=started_at, completed_at=_now_iso())
            schedules.fail_run(schedule_id, error)
            return

        run_store.append(run_id, "schedule.started", {
            "schedule_id": schedule_id,
            "scheduled_for": scheduled_for,
            "agent_id": agent.agent_id,
            "architecture": getattr(agent, "architecture", "single"),
        })
        payload = dict(schedule.get("input") or {})
        payload.update({
            "message": schedule["message"],
            "trigger": "schedule",
            "schedule_id": schedule_id,
            "scheduled_for": scheduled_for,
        })
        device_id = (
            schedule.get("device_id")
            or payload.get("device_id")
            or _default_device_id(int(schedule["user_id"]))
        )
        if device_id:
            payload["device_id"] = device_id
        request = TaskRequest(
            input=payload,
            user_id=int(schedule["user_id"]),
            organization_id=schedule.get("organization_id"),
            device_id=device_id,
            run_id=run_id,
            metadata={
                "schedule_id": schedule_id,
                "scheduled_for": scheduled_for,
                "proactive": True,
                "trigger": "schedule",
                "task_profile": schedule.get("task_profile") or {},
            },
        )

        try:
            result = await self._runtime_scheduler.run_task(
                agent, request, timeout=self.run_timeout_seconds)
            text = (result.text or "").strip()
            error = result.error
            status = "ok" if not error else "error"
            if error:
                self._failures += 1
            else:
                self._runs += 1
            notification = self._notify(
                schedule, scheduled_for, text, error, run_id=run_id)
            run_store.append(run_id, "schedule.completed", {
                "schedule_id": schedule_id,
                "status": status,
                "error": error,
                "chars": len(text),
            })
            schedules.record_run(
                schedule_id, int(schedule["user_id"]), agent_id=agent.agent_id,
                run_id=run_id, scheduled_for=scheduled_for, status=status,
                result=text, error=error,
                notification_id=notification.get("id") if notification else None,
                started_at=started_at, completed_at=_now_iso())
            if error:
                schedules.fail_run(schedule_id, error)
            else:
                schedules.complete_run(schedule_id)
        except Exception as exc:
            self._failures += 1
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("Scheduled agent run crashed: {}", error)
            run_store.append(run_id, "schedule.failed", {
                "schedule_id": schedule_id, "error": error})
            self._notify(schedule, scheduled_for, None, error, run_id=run_id)
            schedules.record_run(
                schedule_id, int(schedule["user_id"]), agent_id=agent.agent_id,
                run_id=run_id, scheduled_for=scheduled_for, status="error",
                error=error, started_at=started_at, completed_at=_now_iso())
            schedules.fail_run(schedule_id, error)

    # ----------------------------------------------------------- notifications
    def _notify(self, schedule: Dict[str, Any], scheduled_for: Optional[str],
                text: Optional[str], error: Optional[str],
                run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if error and not self.notify_on_error:
            return None
        title = schedule["name"]
        body = (text or "").strip()
        if error:
            title = f"{title} (failed)"
            body = error
        if not body:
            body = "The scheduled agent completed without a text result."
        channels = schedule.get("channels") or ["inapp"]
        if not isinstance(channels, list):
            channels = ["inapp"]
        webhook_url = str(self._notification_config.get("webhook_url") or "").strip()
        first = None
        for channel in channels:
            channel = str(channel)
            if channel == "webhook" and not webhook_url:
                continue
            dedupe = f"schedule:{schedule['id']}:{scheduled_for}:{channel}"
            notification = create_notification(
                int(schedule["user_id"]),
                title=title,
                body=body[:4000],
                kind="agent_schedule",
                data={
                    "schedule_id": schedule["id"],
                    "scheduled_for": scheduled_for,
                    "run_id": run_id,
                    "agent_id": schedule["agent_id"],
                    "error": bool(error),
                },
                channel=channel,
                dedupe_key=dedupe,
            )
            first = first or notification
        return first
