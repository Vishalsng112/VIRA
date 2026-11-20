"""Non-destructive backup/restore drill.

The drill creates a real backup with the production helper, copies it to a
temporary directory, opens the copy as a database, runs ``PRAGMA
integrity_check`` and compares table row counts. It never overwrites the live
database, so it is safe to run on a serving instance.

Reported metrics:

* **RPO** — age of the previous backup before this drill (or the drill's own age
  after it completes). The worker schedules a backup every 24 hours, so the
  documented target is 24 hours.
* **RTO** — measured time to copy the backup, open it and validate it.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from vira.auth import database
from vira.ops import backup as backup_ops

RPO_TARGET_HOURS = 24


def _table_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    tables = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    counts = {}
    for table in tables:
        try:
            counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except sqlite3.Error:
            counts[table] = -1
    return counts


def _backup_age_minutes(directory: Path) -> Optional[float]:
    existing = backup_ops.list_backups(str(directory))
    if not existing:
        return None
    newest = existing[0]
    age = datetime.now(timezone.utc).timestamp() - newest.stat().st_mtime
    return round(max(0.0, age) / 60, 2)


def run_drill(backup_dir: Optional[str] = None,
              work_dir: Optional[str] = None) -> Dict[str, Any]:
    """Create, copy, open and validate a backup without touching the live DB."""
    if database.is_postgres():
        raise RuntimeError("The drill currently supports the SQLite baseline.")

    directory = Path(backup_dir or backup_ops.DEFAULT_BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    previous_age = _backup_age_minutes(directory)

    started = time.perf_counter()
    backup_path = backup_ops.create_backup(str(directory))
    backup_seconds = round(time.perf_counter() - started, 3)

    restore_started = time.perf_counter()
    temp_root = Path(work_dir) if work_dir else None
    if temp_root:
        temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(temp_root) if temp_root else None) as temp:
        restored = Path(temp) / "restored.sqlite3"
        shutil.copy2(backup_path, restored)
        conn = sqlite3.connect(str(restored))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = _table_counts(conn)
        finally:
            conn.close()
    restore_seconds = round(time.perf_counter() - restore_started, 3)

    with sqlite3.connect(str(database.DB_PATH)) as live:
        live_counts = _table_counts(live)
    missing = [table for table in live_counts if table not in counts]
    mismatched = [
        table for table in live_counts
        if table in counts and counts[table] != live_counts[table]
    ]
    # A live server may accept writes between the backup and this read, so row
    # mismatches are reported but do not fail the drill. Missing tables and a
    # failed integrity check are hard failures.
    ok = integrity == "ok" and not missing

    return {
        "ok": ok,
        "source": str(database.DB_PATH),
        "backup": str(backup_path),
        "backup_seconds": backup_seconds,
        "restore_seconds": restore_seconds,
        "integrity": integrity,
        "tables": len(counts),
        "rows": sum(max(0, value) for value in counts.values()),
        "previous_backup_age_minutes": previous_age,
        "rpo_target_hours": RPO_TARGET_HOURS,
        "rto_seconds": restore_seconds,
        "missing_tables": missing,
        "row_mismatch_tables": mismatched,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    previous = report.get("previous_backup_age_minutes")
    previous_text = (
        f"{previous} minutes" if previous is not None
        else "none yet; this drill establishes the first restore point"
    )
    return "\n".join([
        "# Backup and restore drill",
        "",
        f"Checked: {report.get('checked_at', '')}",
        "",
        "## Result",
        "",
        f"- Status: **{'PASS' if report.get('ok') else 'FAIL'}**",
        f"- Source: `{report.get('source')}`",
        f"- Backup: `{report.get('backup')}`",
        f"- Integrity check: `{report.get('integrity')}`",
        f"- Tables/rows restored: {report.get('tables')} / {report.get('rows')}",
        f"- Missing tables: {report.get('missing_tables') or 'none'}",
        f"- Row-count mismatches: {report.get('row_mismatch_tables') or 'none'}",
        "",
        "## Recovery objectives",
        "",
        f"- **RPO target:** {report.get('rpo_target_hours')} hours. The worker schedules a",
        "  database backup every 24 hours (`jobs.backup_keep` controls retention).",
        f"- **Previous backup age at drill time:** {previous_text}.",
        f"- **Measured RTO for this drill:** {report.get('rto_seconds')} seconds",
        "  (copy + open + integrity check, excluding container startup and DNS).",
        "",
        "## What this proves",
        "",
        "The backup is a consistent database image and it can be copied and opened",
        "independently of the live server. Row counts are compared with the live",
        "database; a serving instance may have accepted writes since the backup, so",
        "treat mismatches as informational and run the drill on an idle instance for",
        "a strict count comparison.",
        "",
        "It does **not** prove that the master key is backed up. Without",
        "`data/.vira_master_key` (or `VIRA_MASTER_KEY`), encrypted fields cannot be",
        "recovered. Back up the key separately.",
        "",
    ])
