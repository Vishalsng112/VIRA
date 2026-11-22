"""Tests for the read-only database MCP query core."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from vira.auth import database
from vira.tooling.services import database_query as dbq


class DatabaseQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "query.sqlite3"
        self._old_path = database.DB_PATH
        self._old_url = database.DATABASE_URL
        self._old_read_url = database.READ_DATABASE_URL
        database.DB_PATH = self.db_path
        database.DATABASE_URL = ""
        database.READ_DATABASE_URL = ""
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT, role TEXT, status TEXT,
                password_hash TEXT, recovery_code_hash TEXT
            );
            CREATE TABLE devices (
                id TEXT PRIMARY KEY, display_name TEXT, status TEXT,
                created_by_user_id INTEGER, queue_backlog INTEGER DEFAULT 0
            );
            CREATE TABLE user_device_access (
                user_id INTEGER, device_id TEXT, status TEXT
            );
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, user_id INTEGER, title TEXT
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, user_id INTEGER, content TEXT
            );
            CREATE TABLE memories (
                id TEXT PRIMARY KEY, user_id INTEGER, content TEXT
            );
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY, user_id INTEGER, session_id_hash TEXT,
                expires_at TEXT, revoked_at TEXT
            );
            CREATE TABLE user_notifications (
                id INTEGER PRIMARY KEY, user_id INTEGER, read_at TEXT
            );
            INSERT INTO users VALUES
                (1, 'vishal', 'admin', 'active', 'hash', 'recovery'),
                (2, 'alice', 'user', 'active', 'hash', 'recovery');
            INSERT INTO devices VALUES
                ('d1', 'Phone', 'active', 1, 3),
                ('d2', 'Laptop', 'active', 2, 0),
                ('d3', 'Old', 'revoked', 2, 0);
            INSERT INTO user_device_access VALUES
                (1, 'd1', 'active'), (1, 'd2', 'active'), (2, 'd2', 'active');
            INSERT INTO conversations VALUES ('c1', 1, 'Hello');
            INSERT INTO messages VALUES ('m1', 1, 'Hi');
            INSERT INTO memories VALUES ('mem1', 1, 'Remember');
            INSERT INTO sessions VALUES (1, 1, 'hash', '2999-01-01T00:00:00', NULL);
            INSERT INTO user_notifications VALUES (1, 1, NULL);
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_PATH = self._old_path
        database.DATABASE_URL = self._old_url
        database.READ_DATABASE_URL = self._old_read_url
        self.tmp.cleanup()

    def test_catalog_hides_secrets_and_internal_tables(self):
        catalog = dbq.table_catalog()
        names = {item["name"] for item in catalog["tables"]}
        self.assertIn("devices", names)
        self.assertNotIn("plugin_storage", names)
        users = next(item for item in catalog["tables"] if item["name"] == "users")
        self.assertNotIn("password_hash", users["key_columns"])

        schema = dbq.describe_schema(table="users")
        columns = {column["name"] for column in schema["tables"][0]["columns"]}
        self.assertIn("username", columns)
        self.assertNotIn("password_hash", columns)
        self.assertNotIn("recovery_code_hash", columns)

    def test_validation_allows_select_and_rejects_writes(self):
        for sql in (
            "SELECT COUNT(*) FROM devices",
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "SELECT * FROM devices;",
        ):
            ok, reason = dbq.validate_sql(sql)
            self.assertTrue(ok, reason)
        for sql in (
            "INSERT INTO users VALUES (3, 'x', 'admin', 'active', '', '')",
            "UPDATE users SET role = 'admin'",
            "DELETE FROM devices",
            "DROP TABLE devices",
            "PRAGMA table_info(users)",
            "SELECT * FROM users; DROP TABLE users",
            "ATTACH DATABASE 'x.db' AS x",
            "SELECT load_extension('x')",
            "SELECT password_hash FROM users",
            "SELECT * FROM plugin_storage",
        ):
            ok, _ = dbq.validate_sql(sql)
            self.assertFalse(ok, sql)

    def test_admin_can_query_and_non_admin_is_denied(self):
        result = dbq.run_query(
            "SELECT COUNT(*) AS n FROM devices", caller_user_id=1
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["rows"], [[3]])

        denied = dbq.run_query(
            "SELECT COUNT(*) AS n FROM devices", caller_user_id=2
        )
        self.assertFalse(denied["ok"])
        self.assertIn("administrator", denied["error"].lower())

    def test_caller_placeholder_is_scoped(self):
        result = dbq.run_query(
            "SELECT COUNT(*) AS n FROM user_device_access "
            "WHERE user_id = {{caller_user_id}} AND status = 'active'",
            caller_user_id=1,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["rows"], [[2]])

    def test_account_summary_is_scoped(self):
        summary = dbq.account_summary(2)
        self.assertTrue(summary["ok"], summary)
        self.assertEqual(summary["devices"]["total"], 1)
        self.assertEqual(summary["devices"]["active"], 1)
        self.assertEqual(summary["account"]["username"], "alice")


if __name__ == "__main__":
    unittest.main()
