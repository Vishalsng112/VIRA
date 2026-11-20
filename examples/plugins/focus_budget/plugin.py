"""Example VIRA plugin: a local daily focus budget.

Demonstrates event subscription, scheduled work, persisted state, an HTTP route
and a read-only tool. It never sends data anywhere; state is namespaced per
plugin and stored by the server.
"""
from datetime import date

from fastapi import APIRouter

from vira.plugins.api import Plugin
from vira.tools.base import BaseTool, ToolPermission, text_result


def _today() -> str:
    return date.today().isoformat()


def _minutes(ctx, day: str | None = None) -> int:
    bucket = ctx.get_state("minutes", {})
    if not isinstance(bucket, dict):
        return 0
    return int(bucket.get(day or _today(), 0) or 0)


class FocusBudgetTool(BaseTool):
    def __init__(self, ctx):
        super().__init__(
            name="focus_budget",
            description="Check today's focus minutes against the configured daily target.",
            permissions=ToolPermission(actions=["read"]),
            input_schema={"type": "object", "properties": {}},
        )
        self.ctx = ctx

    async def execute(self, **kwargs):
        target = int(self.ctx.config.get("daily_target_minutes", 120))
        minutes = _minutes(self.ctx)
        remaining = max(0, target - minutes)
        return text_result(
            f"Today: {minutes} focus minutes. Target: {target}. Remaining: {remaining}."
        )


class FocusBudgetPlugin(Plugin):
    async def setup(self, ctx):
        self.ctx = ctx
        ctx.register_tool(FocusBudgetTool(ctx))

        async def on_focus_session(event):
            payload = event.data.get("payload", {}) if hasattr(event, "data") else {}
            duration = int(payload.get("duration_seconds", 0) or 0)
            if duration <= 0:
                return
            bucket = ctx.get_state("minutes", {})
            if not isinstance(bucket, dict):
                bucket = {}
            day = _today()
            bucket[day] = int(bucket.get(day, 0) or 0) + max(1, duration // 60)
            # Keep only the last 30 days; this plugin stores no content.
            for key in sorted(bucket)[:-30]:
                bucket.pop(key, None)
            ctx.set_state("minutes", bucket)

        ctx.on_event("device.focus.session", on_focus_session)

        async def cleanup():
            bucket = ctx.get_state("minutes", {})
            if isinstance(bucket, dict) and len(bucket) > 30:
                ctx.set_state("minutes", dict(sorted(bucket.items())[-30:]))

        ctx.schedule(cleanup, interval_seconds=3600, run_immediately=False)

        router = APIRouter()

        @router.get("/summary")
        async def summary():
            target = int(ctx.config.get("daily_target_minutes", 120))
            minutes = _minutes(ctx)
            return {
                "date": _today(),
                "minutes": minutes,
                "target_minutes": target,
                "remaining_minutes": max(0, target - minutes),
            }

        ctx.register_router(router)

    async def start(self):
        pass

    async def stop(self):
        pass
