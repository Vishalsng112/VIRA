"""P1 tests: consent, schemas, commands, pairing, account data."""
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from vira.account.data import delete_user_data, export_user
from vira.auth import auth, database
from vira.devices import commands as command_store
from vira.devices import consent as consent_store
from vira.devices import pairing as pairing_store
from vira.devices import DeviceService, EventIngestionService
from vira.devices.policy import EventPolicy
from vira import notifications


def _app_usage_event(**over):
    item = {
        "event_id": str(uuid.uuid4()),
        "type": "device.app.usage",
        "schema_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source_component": "active_window",
        "payload": {
            "total_foreground_ms": 60000,
            "apps": [{"package": "code", "label": "VS Code",
                      "category": "productivity", "foreground_ms": 60000}],
        },
    }
    item.update(over)
    return item


class P1Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "p1.sqlite3"
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

    def tearDown(self):
        self.tmp.cleanup()


class ConsentAndSchemaTests(P1Base):
    def test_consent_blocks_collector_events(self):
        first, _, _ = self.ing.ingest_sync(
            self.device_principal, self.device_id, [_app_usage_event()])
        self.assertEqual(first["accepted"], 1)
        consent_store.set_consent(self.device_id, "app_usage", False, user_id=1)
        second, _, _ = self.ing.ingest_sync(
            self.device_principal, self.device_id, [_app_usage_event()])
        self.assertEqual(second["rejected"], 1)
        self.assertEqual(second["results"][0]["code"], "consent_denied")
        rows = consent_store.list_for_device(self.device_id)
        app_usage = next(row for row in rows if row["collector"] == "app_usage")
        self.assertFalse(app_usage["enabled"])
        self.assertTrue(app_usage["explicit"])

    def test_schema_validation_rejects_malformed_known_event(self):
        bad = _app_usage_event(payload={"total_foreground_ms": 10})
        result, _, _ = self.ing.ingest_sync(
            self.device_principal, self.device_id, [bad])
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["results"][0]["code"], "schema_validation_failed")

    def test_consent_retention_override(self):
        consent_store.set_consent(self.device_id, "app_usage", True,
                                  retention_hours=1, user_id=1)
        self.ing.ingest_sync(self.device_principal, self.device_id, [_app_usage_event()])
        rows = self.devs.list_events(self.principal, self.device_id, limit=10)
        self.assertTrue(rows["events"])


class CommandTests(P1Base):
    def test_command_lifecycle(self):
        created = command_store.create(self.device_id, "capture.pause", {"minutes": 5}, 1)
        pending = command_store.claim_pending(self.device_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["kind"], "capture.pause")
        self.assertTrue(command_store.complete(
            self.device_id, created["id"], "completed", {"ok": True}))
        history = command_store.list_for_device(self.device_id)
        self.assertEqual(history[0]["status"], "completed")


class PairingTests(P1Base):
    def test_pairing_code_creates_device(self):
        code = pairing_store.create_code(1)
        created = pairing_store.redeem(
            code["code"], "New phone", "android", "phone",
            capabilities=["device_status"],
        )
        self.assertTrue(created["device_id"])
        self.assertTrue(created["credential"]["token"].startswith("vdc_"))
        self.assertEqual(created["account"]["username"], "root")
        with self.assertRaises(ValueError):
            pairing_store.redeem(code["code"], "Again", "android", "phone")

    def test_pairing_uri_is_a_deep_link_with_server_and_code(self):
        uri = pairing_store.pairing_uri("http://192.168.1.20:8000/", "abcd2345")
        self.assertEqual(
            uri, "vira://pair?server=http%3A%2F%2F192.168.1.20%3A8000&code=ABCD2345")

    def test_pairing_qr_is_an_inline_svg(self):
        payload = pairing_store.pairing_uri("http://vira.local:8000", "ABCD2345")
        data_uri = pairing_store.qr_svg_data_uri(payload)
        self.assertTrue(data_uri.startswith("data:image/svg+xml;base64,"))
        self.assertGreater(len(data_uri), 500)


class NotificationTests(P1Base):
    def test_notification_queue_and_push_token(self):
        item = notifications.create(1, "Take a break", "You have been focused for 50 minutes.")
        rows = notifications.list_for_user(1)
        self.assertEqual(rows[0]["id"], item["id"])
        self.assertTrue(notifications.mark_read(1, item["id"]))
        self.assertEqual(notifications.list_for_user(1, unread_only=True), [])
        notifications.register_push_token(self.device_id, "android", "token-123")
        with database.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM device_push_tokens").fetchone()["c"]
        self.assertEqual(count, 1)


class AccountDataTests(P1Base):
    def test_export_and_delete(self):
        self.ing.ingest_sync(self.device_principal, self.device_id, [_app_usage_event()])
        auth_database_user = database.get_user_by_id(1)
        export = export_user(self.principal)
        self.assertEqual(export["user"]["username"], auth_database_user["username"])
        self.assertTrue(export["devices"])
        self.assertTrue(export["devices"][0]["events"])
        counts = delete_user_data(self.principal, delete_devices=True)
        self.assertGreaterEqual(counts["devices"], 1)
        with database.get_connection() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) AS c FROM devices WHERE created_by_user_id = 1"
            ).fetchone()["c"]
        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
