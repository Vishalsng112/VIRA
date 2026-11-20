"""Agent tool: compact, consent-aware user/device context."""
from typing import Any, Optional

from vira.auth import database
from vira.devices import store as device_store
from vira.devices import consent
from vira.insights.service import summarize_device
from vira.tools.base import BaseTool, ToolPermission, text_result


class UserContextTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="user_context",
            description=(
                "Return compact context for the authenticated user: linked devices, "
                "collector consent, latest battery/health, and a short usage summary. "
                "Use before personalised recommendations when you need identity or "
                "device context, not raw events."
            ),
            permissions=ToolPermission(actions=["read"]),
            input_schema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Optional device id"},
                },
            },
        )

    async def execute(self, user_id: Any = None, device_id: Optional[str] = None,
                      **kwargs) -> Any:
        try:
            numeric = int(user_id)
        except (TypeError, ValueError):
            return text_result("ERROR: authenticated user required.", is_error=True)
        devices = device_store.list_devices_for_user(numeric, limit=50)
        if not devices:
            return text_result("No linked devices.")
        selected = next((d for d in devices if d["id"] == device_id), None) if device_id else devices[0]
        if selected is None:
            return text_result("ERROR: device is not linked to this user.", is_error=True)
        consent_rows = consent.list_for_device(selected["id"])
        latest = {row["event_type"]: row["payload"]
                  for row in device_store.get_latest_state(selected["id"])}
        summary = summarize_device(selected["id"], 7)
        enabled = [row["collector"] for row in consent_rows if row["enabled"]]
        return text_result(
            "\n".join([
                f"User id: {numeric}",
                f"Devices: " + ", ".join(f"{d['display_name']} ({d['platform']})" for d in devices[:5]),
                f"Selected device: {selected['display_name']} ({selected['platform']})",
                f"Enabled collectors: {', '.join(enabled) or 'none'}",
                f"Battery: {latest.get('device.battery.state', {})}",
                f"Health: {latest.get('device.health.state', {})}",
                summary["summary"],
            ])
        )
