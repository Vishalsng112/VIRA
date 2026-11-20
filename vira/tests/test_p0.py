"""P0 platform tests: jobs, rate limits, secrets, rollups."""
import asyncio
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from vira.auth import auth, database
from vira.devices import DeviceService, EventIngestionService
from vira.devices.policy import EventPolicy
from vira.jobs import queue as jobs
from vira.ratelimit import RateLimitRule, RateLimiter
from vira.secrets import SecretBox
from vira.kernel.config_manager import ConfigManager
from vira.db.postgres import _translate
from vira.insights.rollup import list_daily, refresh_daily


class PostgresTranslationTests(unittest.TestCase):
    def test_placeholders_and_insert_or_ignore(self):
        sql = _translate("INSERT OR IGNORE INTO t (a) VALUES (?)")
        self.assertIn("%s", sql)
        self.assertIn("ON CONFLICT DO NOTHING", sql)
        named = _translate("VALUES (:event_id, :x)", {"event_id": "e", "x": 1})
        self.assertIn("%(event_id)s", named)
        self.assertIn("%(x)s", named)


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "p0.sqlite3"
        database.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_claim_complete_and_dedupe(self):
        job_id = jobs.enqueue("test.job", {"x": 1}, dedupe_key="test")
        self.assertIsNotNone(job_id)
        self.assertIsNone(jobs.enqueue("test.job", {}, dedupe_key="test"))
        claimed = jobs.claim("worker-1", limit=5)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["kind"], "test.job")
        jobs.complete(job_id)
        self.assertEqual(jobs.stats()["done"], 1)

    def test_failure_moves_to_dead_and_can_retry(self):
        job_id = jobs.enqueue("test.fail", {}, max_attempts=1)
        claimed = jobs.claim("worker-1", limit=1)
        self.assertEqual(len(claimed), 1)
        jobs.fail(job_id, "boom")
        self.assertEqual(jobs.stats()["dead"], 1)
        self.assertTrue(jobs.retry(job_id))
        self.assertEqual(jobs.stats()["pending"], 1)


class RateLimitTests(unittest.TestCase):
    def test_fixed_window_blocks_and_recovers(self):
        limiter = RateLimiter({"/x": RateLimitRule(2, 60)})
        self.assertTrue(limiter.check("a", RateLimitRule(2, 60))[0])
        self.assertTrue(limiter.check("a", RateLimitRule(2, 60))[0])
        allowed, retry = limiter.check("a", RateLimitRule(2, 60))
        self.assertFalse(allowed)
        self.assertGreater(retry, 0)
        self.assertTrue(limiter.check("b", RateLimitRule(2, 60))[0])


class SecretTests(unittest.TestCase):
    def test_encrypt_decrypt_and_payload(self):
        from cryptography.fernet import Fernet
        box = SecretBox(Fernet.generate_key())
        encrypted = box.encrypt("hello")
        self.assertTrue(encrypted.startswith("enc:v1:"))
        self.assertNotIn("hello", encrypted)
        self.assertEqual(box.decrypt(encrypted), "hello")
        self.assertEqual(box.decrypt_payload(box.encrypt_payload('{"a":1}')), '{"a":1}')
        self.assertIsNone(box.encrypt_payload(None))


class ConfigEncryptionTests(unittest.TestCase):
    def test_secret_config_values_are_encrypted_on_save(self):
        import vira.secrets as secret_mod
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / ".master_key"
            config_file = Path(tmp) / "config.yaml"
            config_file.write_text("auth:\n  secret_key: plain-secret\n", encoding="utf-8")
            old_key = os.environ.get("VIRA_MASTER_KEY_FILE")
            os.environ["VIRA_MASTER_KEY_FILE"] = str(key_file)
            secret_mod._box = None
            try:
                manager = ConfigManager(str(config_file))
                asyncio.run(manager.initialize(str(config_file)))
                self.assertEqual(manager.get("auth.secret_key"), "plain-secret")
                manager.save(manager.get_all())
                text = config_file.read_text(encoding="utf-8")
                self.assertIn("enc:v1:", text)
                self.assertNotIn("plain-secret", text)
                self.assertEqual(manager.get("auth.secret_key"), "plain-secret")
            finally:
                if old_key is None:
                    os.environ.pop("VIRA_MASTER_KEY_FILE", None)
                else:
                    os.environ["VIRA_MASTER_KEY_FILE"] = old_key
                secret_mod._box = None


class RollupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "rollup.sqlite3"
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

    def test_refresh_daily_materialises_events(self):
        now = datetime.now(timezone.utc).isoformat()
        events = [
            {
                "event_id": str(uuid.uuid4()), "type": "device.app.usage",
                "schema_version": 1, "occurred_at": now,
                "source_component": "active_window",
                "payload": {
                    "total_foreground_ms": 120000,
                    "categories": {"productivity": 120000},
                    "apps": [{"package": "code", "label": "VS Code",
                              "category": "productivity", "foreground_ms": 120000}],
                },
            },
            {
                "event_id": str(uuid.uuid4()), "type": "device.session.state",
                "schema_version": 1, "occurred_at": now,
                "source_component": "screen_session",
                "payload": {"interactive_ms": 180000, "unlocks": 2},
            },
        ]
        self.ing.ingest_sync(self.device_principal, self.device_id, events)
        written = refresh_daily(days=1)
        self.assertGreaterEqual(written, 1)
        daily = list_daily(self.device_id, days=1)
        self.assertTrue(daily)
        self.assertEqual(daily[0]["app_ms"], 120000)
        self.assertEqual(daily[0]["screen_ms"], 180000)


if __name__ == "__main__":
    unittest.main()
