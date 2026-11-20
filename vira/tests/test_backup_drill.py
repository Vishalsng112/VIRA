"""Backup and restore drill tests (SQLite baseline)."""
import tempfile
import unittest
from pathlib import Path

from vira.auth import auth, database
from vira.ops import backup as backup_ops
from vira.ops.drill import render_markdown, run_drill


class BackupDrillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        database.DB_PATH = self.root / "live.sqlite3"
        database.init_db()
        auth.create_admin("backup-user", "backuppass1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_drill_creates_opens_and_validates_a_backup(self):
        report = run_drill(str(self.root / "backups"), str(self.root / "work"))
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["integrity"], "ok")
        self.assertTrue(Path(report["backup"]).exists())
        self.assertGreater(report["tables"], 0)
        self.assertGreater(report["rows"], 0)
        self.assertIn("PASS", render_markdown(report))
        self.assertIn("RPO target", render_markdown(report))

    def test_restore_keeps_a_safety_copy(self):
        database.create_conversation(1, "before backup")
        source = backup_ops.create_backup(str(self.root / "backups"))
        database.create_conversation(1, "after backup")
        safety = backup_ops.restore_backup(str(source))
        self.assertTrue(safety.exists())
        # The restored database is the older image: one conversation, not two.
        self.assertEqual(len(database.list_conversations(1)), 1)
        self.assertEqual(database.list_conversations(1)[0]["title"], "before backup")


if __name__ == "__main__":
    unittest.main()
