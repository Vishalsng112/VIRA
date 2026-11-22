"""Insight aggregation tests (offline, no database)."""
import asyncio
import unittest

from vira.insights.aggregate import aggregate_events


def _event(event_type, payload, day="2026-01-02"):
    return {"event_type": event_type, "occurred_at": f"{day}T10:00:00+00:00",
            "payload": payload}


class InsightAggregationTests(unittest.TestCase):
    def test_aggregates_apps_sessions_focus_and_health(self):
        events = [
            _event("device.app.usage", {
                "total_foreground_ms": 600000,
                "categories": {"social": 400000, "productivity": 200000},
                "apps": [
                    {"package": "com.instagram.android", "label": "Instagram",
                     "category": "social", "foreground_ms": 400000},
                    {"package": "code", "label": "VS Code",
                     "category": "productivity", "foreground_ms": 200000},
                ],
            }),
            _event("device.session.state", {
                "interactive_ms": 900000, "unlocks": 12, "interactions": 30,
            }),
            _event("device.focus.state", {
                "focus_ms": 200000, "distraction_ms": 400000,
                "focus_score": 33, "state": "distracted",
            }),
            _event("device.focus.session", {
                "duration_seconds": 1500, "completed": True, "label": "Study",
            }),
            _event("device.battery.state", {"level_percent": 72, "charging": True}),
            _event("device.health.state", {
                "storage_percent": 93, "thermal_c": 47.0,
                "warnings": ["Low storage: 93% used"],
            }),
        ]
        result = aggregate_events(events, 7)
        self.assertEqual(result["totals"]["app_ms"], 600000)
        self.assertEqual(result["totals"]["screen_ms"], 900000)
        self.assertEqual(result["totals"]["unlocks"], 12)
        self.assertEqual(result["totals"]["focus_sessions"], 1)
        self.assertEqual(result["totals"]["completed_focus_sessions"], 1)
        self.assertEqual(result["top_apps"][0]["label"], "Instagram")
        self.assertEqual(result["categories"][0]["category"], "social")
        self.assertEqual(result["battery"]["level_percent"], 72)
        self.assertIn("Low storage", result["health"]["warnings"][0])
        self.assertIn("Top app: Instagram", result["summary"])
        self.assertEqual(result["daily"][0]["screen_ms"], 900000)

    def test_empty_window_is_safe(self):
        result = aggregate_events([], 7)
        self.assertEqual(result["top_apps"], [])
        self.assertEqual(result["totals"]["app_ms"], 0)
        self.assertIn("no app data", result["summary"])

    def test_include_apps_false_redacts_summary(self):
        events = [_event("device.app.usage", {
            "total_foreground_ms": 600000,
            "categories": {"social": 400000, "productivity": 200000},
            "apps": [{"package": "com.instagram.android", "label": "Instagram",
                      "category": "social", "foreground_ms": 400000}],
        })]
        result = aggregate_events(events, 7, include_apps=False)
        self.assertIn("hidden for privacy", result["summary"])
        self.assertNotIn("Instagram", result["summary"])


if __name__ == "__main__":
    unittest.main()


class InsightsToolTests(unittest.TestCase):
    def setUp(self):
        import tempfile, uuid
        from datetime import datetime, timezone
        from pathlib import Path
        from vira.auth import auth, database
        from vira.devices import DeviceService, EventIngestionService
        from vira.devices.policy import EventPolicy

        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "insights.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        user = database.get_user_by_id(1)
        self.principal = auth.UserPrincipal(
            user_id=1, username=user["username"], roles=(user["role"],),
            session_id="s", public_id=user["public_id"])
        self.devs = DeviceService(EventPolicy())
        self.ing = EventIngestionService(EventPolicy())
        reg = self.devs.register_device(self.principal, "Laptop", "linux", "laptop")
        self.device_id = reg["device_id"]
        self.device_principal = self.devs.authenticate_credential(
            reg["credential"]["token"])
        self.devs.heartbeat(self.device_principal, self.device_id)
        event = {
            "event_id": str(uuid.uuid4()),
            "type": "device.app.usage",
            "schema_version": 1,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source_component": "active_window",
            "payload": {
                "total_foreground_ms": 3600000,
                "categories": {"productivity": 2400000, "social": 1200000},
                "apps": [
                    {"package": "code", "label": "VS Code",
                     "category": "productivity", "foreground_ms": 2400000},
                    {"package": "instagram", "label": "Instagram",
                     "category": "social", "foreground_ms": 1200000},
                ],
            },
        }
        self.ing.ingest_sync(self.device_principal, self.device_id, [event])

    def tearDown(self):
        self.tmp.cleanup()

    def test_tool_summarises_selected_device(self):
        from vira.tooling import ToolContext
        from vira.tooling.servers.vira_core.tools import ViraInsightsTool
        result = asyncio.run(ViraInsightsTool().invoke(
            {"device_id": self.device_id, "days": 7},
            ToolContext(user_id=1)))
        self.assertTrue(result.ok)
        text = result.data.text
        self.assertIn("VS Code", text)
        self.assertIn("Focus score", text)
        self.assertIn("Laptop", text)

    def test_tool_rejects_unknown_device(self):
        from vira.tooling import ToolContext
        from vira.tooling.servers.vira_core.tools import ViraInsightsTool
        result = asyncio.run(ViraInsightsTool().invoke(
            {"device_id": "not-a-device", "days": 7},
            ToolContext(user_id=1)))
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
