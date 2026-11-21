"""Proactive agent schedules, execution, notifications and API."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vira import notifications
from vira.agent import schedules
from vira.agent.base import TaskResult
from vira.agent.proactive import ProactiveScheduler
from vira.agent_orchestration.scheduler import RuntimeScheduler
from vira.api.routes_schedules import build_schedule_router
from vira.auth import auth, database


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ScheduleMathTests(unittest.TestCase):
    def test_daily_rolls_to_next_day(self):
        schedule = {"schedule_type": "daily", "time_of_day": "08:00",
                    "timezone": "UTC"}
        value = schedules.next_run_at(
            schedule, after=_dt("2026-11-21T09:00:00+00:00"))
        self.assertEqual(_dt(value), _dt("2026-11-22T08:00:00+00:00"))

    def test_daily_uses_local_timezone(self):
        schedule = {"schedule_type": "daily", "time_of_day": "08:00",
                    "timezone": "Asia/Kolkata"}
        value = schedules.next_run_at(
            schedule, after=_dt("2026-11-21T00:00:00+00:00"))
        # 08:00 IST is 02:30 UTC.
        self.assertEqual(_dt(value), _dt("2026-11-21T02:30:00+00:00"))

    def test_weekly_rolls_to_target_weekday(self):
        # 2026-11-21 is a Saturday; next Monday is 2026-11-23.
        schedule = {"schedule_type": "weekly", "time_of_day": "09:00",
                    "weekday": 0, "timezone": "UTC"}
        value = schedules.next_run_at(
            schedule, after=_dt("2026-11-21T12:00:00+00:00"))
        self.assertEqual(_dt(value), _dt("2026-11-23T09:00:00+00:00"))

    def test_interval(self):
        schedule = {"schedule_type": "interval", "interval_minutes": 90}
        value = schedules.next_run_at(
            schedule, after=_dt("2026-11-21T10:00:00+00:00"))
        self.assertEqual(_dt(value), _dt("2026-11-21T11:30:00+00:00"))

    def test_quiet_hours_defer_to_end(self):
        schedule = {"schedule_type": "daily", "time_of_day": "23:30",
                    "timezone": "UTC", "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00"}
        value = schedules.next_run_at(
            schedule, after=_dt("2026-11-21T20:00:00+00:00"))
        self.assertEqual(_dt(value), _dt("2026-11-22T07:00:00+00:00"))

    def test_invalid_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            schedules.validate_schedule_fields("daily", "25:00", None, None)
        with self.assertRaises(ValueError):
            schedules.validate_schedule_fields("weekly", "08:00", 9, None)
        with self.assertRaises(ValueError):
            schedules.validate_schedule_fields("interval", None, None, 0)


class ScheduleStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "schedules.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        database.create_user("other", "hash", "recovery", role="user")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_adds_tables_and_notification_columns(self):
        with database.get_connection() as conn:
            tables = {row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            columns = {row["name"] for row in conn.execute(
                "PRAGMA table_info(user_notifications)")}
        self.assertIn("agent_schedules", tables)
        self.assertIn("agent_schedule_runs", tables)
        self.assertTrue({"channel", "dedupe_key", "attempts", "last_error"}
                        <= columns)

    def test_crud_and_user_isolation(self):
        item = schedules.create_schedule(
            1, "chatbot", "Morning", "Summarise my day",
            schedule_type="daily", time_of_day="07:30")
        self.assertEqual(item["user_id"], 1)
        self.assertTrue(item["next_run_at"])
        self.assertIsNotNone(schedules.get_schedule(item["id"], 1))
        self.assertIsNone(schedules.get_schedule(item["id"], 2))
        self.assertEqual(len(schedules.list_schedules(1)), 1)
        self.assertEqual(schedules.list_schedules(2), [])

        updated = schedules.update_schedule(
            item["id"], 1, time_of_day="09:00")
        self.assertEqual(updated["time_of_day"], "09:00")
        self.assertIsNone(schedules.update_schedule(item["id"], 2, name="x"))

        self.assertTrue(schedules.delete_schedule(item["id"], 2) is False)
        self.assertTrue(schedules.delete_schedule(item["id"], 1))

    def test_claim_is_atomic_and_complete_advances(self):
        item = schedules.create_schedule(
            1, "chatbot", "Morning", "Summarise",
            schedule_type="interval", interval_minutes=60)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with database.transaction() as conn:
            conn.execute("UPDATE agent_schedules SET next_run_at = ? WHERE id = ?",
                         (past, item["id"]))
        first = schedules.claim_due(now=datetime.now(timezone.utc))
        self.assertEqual([row["id"] for row in first], [item["id"]])
        second = schedules.claim_due(now=datetime.now(timezone.utc))
        self.assertEqual(second, [])
        updated = schedules.complete_run(item["id"])
        self.assertGreater(_dt(updated["next_run_at"]), datetime.now(timezone.utc))

    def test_run_now_requires_enabled_schedule(self):
        item = schedules.create_schedule(
            1, "chatbot", "Morning", "Summarise")
        self.assertIsNotNone(schedules.run_now(item["id"], 1))
        schedules.update_schedule(item["id"], 1, enabled=False)
        self.assertIsNone(schedules.run_now(item["id"], 1))

    def test_disabled_schedule_is_not_claimed(self):
        item = schedules.create_schedule(
            1, "chatbot", "Morning", "Summarise", enabled=False)
        with database.transaction() as conn:
            conn.execute("UPDATE agent_schedules SET next_run_at = ? WHERE id = ?",
                         ("2000-01-01T00:00:00+00:00", item["id"]))
        self.assertEqual(schedules.claim_due(), [])


class _Agent:
    agent_id = "agent-1"
    name = "chatbot"
    architecture = "single"

    def __init__(self):
        self.requests = []

    async def run_task(self, request):
        self.requests.append(request)
        return TaskResult(text="Daily brief: 3 priorities.", data={})


class _Registry:
    def __init__(self, agent):
        self.agent = agent
        self.states = []

    async def get_instance(self, agent_id):
        return self.agent if agent_id in {self.agent.agent_id, self.agent.name} else None

    async def list_agents(self):
        return [SimpleNamespace(agent_id=self.agent.agent_id,
                                name=self.agent.name,
                                architecture=self.agent.architecture,
                                enabled=True)]

    async def update_state(self, agent_id, state):
        self.states.append((agent_id, state))


class ProactiveExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "proactive.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")

    def tearDown(self):
        self.tmp.cleanup()

    async def test_due_schedule_runs_agent_and_notifies(self):
        item = schedules.create_schedule(
            1, "chatbot", "Morning brief", "Summarise my day",
            schedule_type="interval", interval_minutes=60,
            task_profile={"decomposability": 0.8})
        with database.transaction() as conn:
            conn.execute("UPDATE agent_schedules SET next_run_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                          item["id"]))
        agent = _Agent()
        registry = _Registry(agent)
        scheduler = ProactiveScheduler(
            registry, RuntimeScheduler(registry),
            config={"max_concurrent": 1, "run_timeout_seconds": 30})
        ran = await scheduler.run_due()
        await scheduler.drain()
        self.assertEqual(ran, 1)
        self.assertEqual(len(agent.requests), 1)
        request = agent.requests[0]
        self.assertEqual(request.user_id, 1)
        self.assertTrue(request.metadata["proactive"])
        self.assertEqual(request.metadata["task_profile"], {"decomposability": 0.8})

        notes = notifications.list_for_user(1)
        self.assertEqual(len(notes), 1)
        self.assertIn("Daily brief", notes[0]["body"])
        runs = schedules.list_runs(item["id"], 1)
        self.assertEqual(runs[0]["status"], "ok")
        self.assertTrue(schedules.get_schedule(item["id"], 1)["last_run_at"])

    async def test_unknown_agent_records_failure(self):
        item = schedules.create_schedule(
            1, "missing", "Broken", "Do work",
            schedule_type="interval", interval_minutes=60)
        with database.transaction() as conn:
            conn.execute("UPDATE agent_schedules SET next_run_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                          item["id"]))
        scheduler = ProactiveScheduler(
            _Registry(_Agent()), RuntimeScheduler(_Registry(_Agent())),
            config={})
        await scheduler.run_due()
        await scheduler.drain()
        runs = schedules.list_runs(item["id"], 1)
        self.assertEqual(runs[0]["status"], "error")
        self.assertIn("agent not found", runs[0]["error"])
        notes = notifications.list_for_user(1)
        self.assertTrue(any("failed" in note["title"] for note in notes))

    async def test_deduplicated_notifications(self):
        item = schedules.create_schedule(
            1, "chatbot", "Morning", "Summarise", schedule_type="interval",
            interval_minutes=60)
        first = notifications.create(
            1, "Morning", "one", kind="agent_schedule",
            dedupe_key=f"schedule:{item['id']}:t1:inapp")
        second = notifications.create(
            1, "Morning", "two", kind="agent_schedule",
            dedupe_key=f"schedule:{item['id']}:t1:inapp")
        self.assertEqual(first["id"], second["id"])


class NotificationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "notify.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_inapp_is_delivered_immediately(self):
        item = notifications.create(1, "Hello")
        self.assertEqual(item["status"], "delivered")
        self.assertEqual(notifications.list_for_user(1)[0]["status"], "delivered")

    def test_webhook_success_and_failure(self):
        item = notifications.create(1, "Hello", channel="webhook",
                                    dedupe_key="webhook-1")
        with mock.patch("vira.notifications._post_webhook", return_value=True):
            result = notifications.deliver_pending(
                webhook_url="http://example.test", max_attempts=2)
        self.assertEqual(result["delivered"], 1)
        rows = notifications.list_for_user(1)
        delivered = next(row for row in rows if row["id"] == item["id"])
        self.assertEqual(delivered["status"], "delivered")

        failed = notifications.create(1, "Fail", channel="webhook",
                                      dedupe_key="webhook-2")
        with mock.patch("vira.notifications._post_webhook", return_value=False):
            notifications.deliver_pending(webhook_url="http://example.test",
                                          max_attempts=1)
        row = next(row for row in notifications.list_for_user(1)
                   if row["id"] == failed["id"])
        self.assertEqual(row["status"], "failed")


class ScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "api.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        app = FastAPI()
        user = SimpleNamespace(user_id=1, username="root", roles=("admin",))
        app.include_router(build_schedule_router(
            lambda: user, SimpleNamespace(agent_orchestrator=None)))
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalog_and_crud(self):
        recipes = self.client.get("/api/v1/agent-recipes")
        self.assertEqual(recipes.status_code, 200)
        self.assertEqual(len(recipes.json()["agents"]), 5)

        status = self.client.get("/api/v1/agent-schedules/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["available"])

        created = self.client.post("/api/v1/agent-schedules", json={
            "agent_id": "chatbot",
            "name": "Morning brief",
            "message": "Summarise my day",
            "schedule_type": "daily",
            "time_of_day": "07:30",
            "timezone": "UTC",
            "channels": ["inapp"],
        })
        self.assertEqual(created.status_code, 201)
        item = created.json()
        self.assertEqual(item["user_id"], 1)

        listed = self.client.get("/api/v1/agent-schedules")
        self.assertEqual(len(listed.json()["schedules"]), 1)

        patched = self.client.patch(
            f"/api/v1/agent-schedules/{item['id']}",
            json={"time_of_day": "09:00", "enabled": False})
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["time_of_day"], "09:00")
        self.assertFalse(patched.json()["enabled"])

        run = self.client.post(f"/api/v1/agent-schedules/{item['id']}/run")
        self.assertEqual(run.status_code, 409)

        deleted = self.client.delete(f"/api/v1/agent-schedules/{item['id']}")
        self.assertEqual(deleted.status_code, 204)

    def test_invalid_schedule_is_rejected(self):
        response = self.client.post("/api/v1/agent-schedules", json={
            "agent_id": "chatbot",
            "name": "Bad",
            "message": "Do it",
            "schedule_type": "daily",
            "time_of_day": "25:99",
        })
        self.assertEqual(response.status_code, 422)

    def test_other_user_cannot_read_schedule(self):
        item = schedules.create_schedule(
            1, "chatbot", "Mine", "task", schedule_type="daily")
        # Rebuild the client with a different user.
        app = FastAPI()
        other = SimpleNamespace(user_id=2, username="other", roles=("user",))
        app.include_router(build_schedule_router(
            lambda: other, SimpleNamespace(agent_orchestrator=None)))
        client = TestClient(app)
        self.assertEqual(client.get("/api/v1/agent-schedules").json()["schedules"], [])
        self.assertEqual(client.delete(
            f"/api/v1/agent-schedules/{item['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
