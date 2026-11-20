"""Durable database-backed job queue.

Small installs use the same SQLite database as the rest of VIRA; workers claim
jobs atomically with ``BEGIN IMMEDIATE``.  A Postgres deployment can implement
the same interface with ``SELECT ... FOR UPDATE SKIP LOCKED`` later.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _delay(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0, seconds))).isoformat()


def enqueue(kind: str, payload: Optional[Dict[str, Any]] = None, *,
            delay_seconds: float = 0, priority: int = 0,
            max_attempts: int = 5, dedupe_key: Optional[str] = None) -> Optional[str]:
    """Insert a job. Returns the job id, or None when dedupe skipped it."""
    job_id = str(uuid.uuid4())
    now = _now()
    with database.transaction() as conn:
        if dedupe_key:
            existing = conn.execute(
                "SELECT id FROM jobs WHERE dedupe_key = ? AND status IN ('pending','running')",
                (dedupe_key,),
            ).fetchone()
            if existing:
                return None
        try:
            conn.execute(
                "INSERT INTO jobs (id, kind, payload, status, priority, attempts, max_attempts, "
                "available_at, dedupe_key, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', ?, 0, ?, ?, ?, ?, ?)",
                (job_id, kind, json.dumps(payload or {}, default=str), priority,
                 max(1, max_attempts), _delay(delay_seconds), dedupe_key, now, now),
            )
        except Exception:
            # A concurrent dedupe insert won the unique constraint.
            if dedupe_key:
                return None
            raise
    return job_id


def claim(worker_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Atomically move ready jobs to running and return them."""
    limit = max(1, min(int(limit), 100))
    now = _now()
    with database.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' AND available_at <= ? "
            "ORDER BY priority DESC, created_at LIMIT ?",
            (now, limit),
        ).fetchall()
        claimed: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            changed = conn.execute(
                "UPDATE jobs SET status = 'running', locked_at = ?, locked_by = ?, "
                "attempts = attempts + 1, updated_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (now, worker_id, now, item["id"]),
            ).rowcount
            if changed:
                item["attempts"] = int(item["attempts"]) + 1
                item["status"] = "running"
                claimed.append(item)
    return claimed


def reclaim_stale(timeout_seconds: int = 900) -> int:
    """Return jobs abandoned by a crashed worker to the pending pool."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(60, timeout_seconds))).isoformat()
    now = _now()
    with database.transaction() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'pending', locked_at = NULL, locked_by = NULL, "
            "available_at = ?, updated_at = ? WHERE status = 'running' AND locked_at < ?",
            (now, now, cutoff),
        )
        return cur.rowcount


def complete(job_id: str) -> None:
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', completed_at = ?, updated_at = ?, last_error = NULL "
            "WHERE id = ?",
            (now, now, job_id),
        )


def fail(job_id: str, error: str) -> None:
    now = _now()
    with database.transaction() as conn:
        row = conn.execute(
            "SELECT attempts, max_attempts FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return
        attempts = int(row["attempts"])
        max_attempts = int(row["max_attempts"])
        if attempts >= max_attempts:
            conn.execute(
                "UPDATE jobs SET status = 'dead', last_error = ?, updated_at = ? WHERE id = ?",
                (error[:4000], now, job_id),
            )
        else:
            delay = min(300, 2 ** max(0, attempts - 1))
            conn.execute(
                "UPDATE jobs SET status = 'pending', last_error = ?, available_at = ?, "
                "locked_at = NULL, locked_by = NULL, updated_at = ? WHERE id = ?",
                (error[:4000], _delay(delay), now, job_id),
            )


def retry(job_id: str) -> bool:
    now = _now()
    with database.transaction() as conn:
        changed = conn.execute(
            "UPDATE jobs SET status = 'pending', attempts = 0, available_at = ?, "
            "last_error = NULL, locked_at = NULL, locked_by = NULL, updated_at = ? "
            "WHERE id = ? AND status IN ('dead','failed')",
            (now, now, job_id),
        ).rowcount
    return bool(changed)


def stats() -> Dict[str, int]:
    with database.get_connection() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
    result = {status: 0 for status in ("pending", "running", "done", "failed", "dead")}
    for row in rows:
        result[row["status"]] = int(row["count"])
    result["total"] = sum(result.values())
    return result


def list_jobs(status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    with database.get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except ValueError:
            item["payload"] = {}
        result.append(item)
    return result


def purge_finished(older_than_days: int = 14) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))).isoformat()
    with database.transaction() as conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE status IN ('done','failed') AND updated_at < ?",
            (cutoff,),
        )
        return cur.rowcount
