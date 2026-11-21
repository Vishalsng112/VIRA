"""Agent tool: summarise a user's device activity without raw event dumps."""
from typing import Any, Dict, Optional

from vira.auth import database
from vira.devices import store as device_store
from vira.insights.service import summarize_device
from vira.tools.base import BaseTool, ToolPermission, text_result


class InsightsTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="insights",
            description=(
                "Summarise a user's device activity for a time window: screen time, "
                "top apps, app categories, focus sessions, unlocks, battery and device "
                "health warnings. Use this for questions about the user's usage, focus, "
                "productivity or wellbeing. Optionally pass device_id; otherwise the "
                "most recently enrolled device is used."
            ),
            permissions=ToolPermission(actions=["read"]),
            input_schema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Optional device id"},
                    "days": {"type": "integer", "minimum": 1, "maximum": 90,
                             "description": "Lookback window in days (default 7)"},
                    "include_apps": {
                        "type": "boolean",
                        "description": ("Include top app names. Set false for "
                                        "privacy-safe weekly reports."),
                    },
                },
            },
        )

    async def execute(self, user_id: Any = None, device_id: Optional[str] = None,
                      days: int = 7, include_apps: bool = True, **kwargs) -> Any:
        try:
            numeric_user = int(user_id)
        except (TypeError, ValueError):
            return text_result("ERROR: this tool needs an authenticated user.", is_error=True)
        user = database.get_user_by_id(numeric_user)
        if not user:
            return text_result("ERROR: unknown user.", is_error=True)
        devices = device_store.list_devices_for_user(numeric_user, limit=200)
        if not devices:
            return text_result(
                "No enrolled devices have sent data for this user yet. "
                "Open VIRA Link and let it sync first."
            )
        selected = None
        if device_id:
            selected = next((d for d in devices if d["id"] == device_id), None)
            if selected is None:
                return text_result(
                    "ERROR: that device is not linked to this user.", is_error=True)
        else:
            selected = devices[0]
        data = summarize_device(selected["id"], days, include_apps=include_apps)
        top = ", ".join(
            f"{app['label']} ({app['foreground_ms'] // 60000}m)"
            for app in data["top_apps"][:5]
        ) or "no app data"
        categories = ", ".join(
            f"{item['category']} ({item['foreground_ms'] // 60000}m)"
            for item in data.get("categories", [])[:5]
        ) or "no category data"
        warnings = data["health"].get("warnings", [])
        battery = data.get("battery") or {}
        lines = [
            f"Device: {selected['display_name']} ({selected.get('platform', 'unknown')})",
            data["summary"],
            (f"Top apps: {top}." if include_apps
             else "Top apps: hidden for privacy."),
            f"Categories: {categories}.",
            f"Focus score: {data['focus'].get('score', 0)}/100. "
            f"Focus sessions: {data['totals'].get('focus_sessions', 0)}.",
        ]
        if battery:
            lines.append(
                f"Battery: {battery.get('level_percent', '?')}%"
                f" ({'charging' if battery.get('charging') else 'on battery'})."
            )
        if warnings:
            lines.append("Health warnings: " + "; ".join(warnings))
        lines.append(
            "Use this summary to answer the user's question. Do not invent numbers "
            "that are not present here."
        )
        return text_result("\n".join(lines))
