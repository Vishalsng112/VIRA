"""Durable storage and scheduling math for proactive agents.

Schedules are user-scoped rows. The scheduler claims due rows atomically, so a
server restart retries a run instead of silently losing it. All timestamps are
stored in UTC; daily/weekly schedules are evaluated in their configured IANA
timezone.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vira.auth import database

SCHEDULE_TYPES = ("daily", "weekly", "interval")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _timezone(name: Optional[str]):
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_time(value: Optional[str]) -> tuple[int, int]:
    if not value:
        raise ValueError("time_of_day is required (HH:MM)")
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError("time_of_day must be HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time_of_day must be a valid HH:MM")
    return hour, minute


def validate_schedule_fields(schedule_type: str, time_of_day: Optional[str],
                             weekday: Optional[int],
                             interval_minutes: Optional[int]) -> None:
    if schedule_type not in SCHEDULE_TYPES:
        raise ValueError(f"schedule_type must be one of {SCHEDULE_TYPES}")
    if schedule_type in ("daily", "weekly"):
        _parse_time(time_of_day)
    if schedule_type == "weekly":
        if weekday is None or not (0 <= int(weekday) <= 6):
            raise ValueError("weekday must be 0 (Monday) to 6 (Sunday)")
    if schedule_type == "interval":
        if interval_minutes is None or int(interval_minutes) < 1:
            raise ValueError("interval_minutes must be >= 1")


def _quiet_window(schedule: Dict[str, Any]) -> tuple[Optional[tuple[int, int]],
                                                       Optional[tuple[int, int]]]:
    start, end = schedule.get("quiet_hours_start"), schedule.get("quiet_hours_end")
    if not start or not end:
        return None, None
    try:
        return _parse_time(start), _parse_time(end)
    except (ValueError, TypeError):
        return None, None


def _in_quiet_hours(local: datetime, start: tuple[int, int],
                    end: tuple[int, int]) -> bool:
    current = (local.hour, local.minute)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _after_quiet_hours(local: datetime, start: tuple[int, int],
                       end: tuple[int, int]) -> datetime:
    end_dt = local.replace(hour=end[0], minute=end[1], second=0, microsecond=0)
    if end_dt <= local:
        end_dt += timedelta(days=1)
    return end_dt


def next_run_at(schedule: Dict[str, Any],
                after: Optional[datetime] = None) -> str:
    """Compute the next UTC run time for a schedule."""
    after = after or _now()
    schedule_type = str(schedule.get("schedule_type") or "daily")
    if schedule_type == "interval":
        minutes = max(1, int(schedule.get("interval_minutes") or 60))
        candidate = after + timedelta(minutes=minutes)
        tz = _timezone(schedule.get("timezone"))
        local = candidate.astimezone(tz)
        start, end = _quiet_window(schedule)
        if start and end and _in_quiet_hours(local, start, end):
            candidate = _after_quiet_hours(local, start, end)
        return _iso(candidate)

    tz = _timezone(schedule.get("timezone"))
    local = after.astimezone(tz)
    hour, minute = _parse_time(schedule.get("time_of_day"))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if schedule_type == "weekly":
        target = int(schedule.get("weekday") or 0)
        days = (target - candidate.weekday()) % 7
        candidate += timedelta(days=days)
        if candidate <= local:
            candidate += timedelta(days=7)
    else:
        if candidate <= local:
            candidate += timedelta(days=1)

    start, end = _quiet_window(schedule)
    if start and end and _in_quiet_hours(candidate, start, end):
        candidate = _after_quiet_hours(candidate, start, end)
    return _iso(candidate)


def _decode(row: Any) -> Dict[str, Any]:
    item = dict(row)
    for key, default in (("channels", ["inapp"]), ("task_profile", {})):
        try:
            value = json.loads(item.get(key) or "")
        except (TypeError, ValueError):
            value = default
        item[key] = value if isinstance(value, type(default)) else default
    item["enabled"] = bool(item.get("enabled"))
    return item


def create_schedule(user_id: int, agent_id: str, name: str, message: str, *,
                    schedule_type: str = "daily",
                    time_of_day: Optional[str] = "08:00",
                    weekday: Optional[int] = None,
                    interval_minutes: Optional[int] = None,
                    timezone_name: str = "UTC",
                    quiet_hours_start: Optional[str] = None,
                    quiet_hours_end: Optional[str] = None,
                    channels: Optional[List[str]] = None,
                    task_profile: Optional[Dict[str, Any]] = None,
                    organization_id: Optional[str] = None,
                    enabled: bool = True) -> Dict[str, Any]:
    validate_schedule_fields(schedule_type, time_of_day, weekday, interval_minutes)
    schedule_id = str(uuid.uuid4())
    now = _iso(_now())
    schedule = {
        "schedule_type": schedule_type,
        "time_of_day": time_of_day,
        "weekday": weekday,
        "interval_minutes": interval_minutes,
        "timezone": timezone_name or "UTC",
        "quiet_hours_start": quiet_hours_start,
        "quiet_hours_end": quiet_hours_end,
    }
    next_run = next_run_at(schedule) if enabled else None
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO agent_schedules "
            "(id, user_id, organization_id, agent_id, name, message, schedule_type, "
            "time_of_day, weekday, interval_minutes, timezone, quiet_hours_start, "
            "quiet_hours_end, channels, task_profile, enabled, next_run_at, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                schedule_id, user_id, organization_id, agent_id, name[:160],
                message, schedule_type, time_of_day, weekday, interval_minutes,
                timezone_name or "UTC", quiet_hours_start, quiet_hours_end,
                json.dumps(channels or ["inapp"]),
                json.dumps(task_profile or {}),
                1 if enabled else 0, next_run, now, now,
            ),
        )
    return get_schedule(schedule_id, user_id)


def get_schedule(schedule_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    clause = "WHERE id = ?"
    values: List[Any] = [schedule_id]
    if user_id is not None:
        clause += " AND user_id = ?"
        values.append(user_id)
    with database.get_connection() as conn:
        row = conn.execute(
            f"SELECT * FROM agent_schedules {clause}", values).fetchone()
    return _decode(row) if row else None


def list_schedules(user_id: int, enabled: Optional[bool] = None) -> List[Dict[str, Any]]:
    clauses = ["user_id = ?"]
    values: List[Any] = [user_id]
    if enabled is not None:
        clauses.append("enabled = ?")
        values.append(1 if enabled else 0)
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_schedules WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC", values).fetchall()
    return [_decode(row) for row in rows]


def update_schedule(schedule_id: str, user_id: int, **changes: Any) -> Optional[Dict[str, Any]]:
    current = get_schedule(schedule_id, user_id)
    if not current:
        return None
    merged = dict(current)
    merged.update({key: value for key, value in changes.items()
                   if value is not None or key in {
                       "quiet_hours_start", "quiet_hours_end", "time_of_day",
                       "weekday", "interval_minutes", "task_profile", "channels",
                       "organization_id"}})
    validate_schedule_fields(
        merged["schedule_type"], merged.get("time_of_day"),
        merged.get("weekday"), merged.get("interval_minutes"))
    if not merged.get("enabled"):
        next_run = None
    else:
        next_run = next_run_at(merged)
    now = _iso(_now())
    with database.transaction() as conn:
        conn.execute(
            "UPDATE agent_schedules SET agent_id = ?, name = ?, message = ?, "
            "schedule_type = ?, time_of_day = ?, weekday = ?, interval_minutes = ?, "
            "timezone = ?, quiet_hours_start = ?, quiet_hours_end = ?, channels = ?, "
            "task_profile = ?, enabled = ?, next_run_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (
                merged["agent_id"], str(merged["name"])[:160], merged["message"],
                merged["schedule_type"], merged.get("time_of_day"),
                merged.get("weekday"), merged.get("interval_minutes"),
                merged.get("timezone") or "UTC", merged.get("quiet_hours_start"),
                merged.get("quiet_hours_end"), json.dumps(merged.get("channels") or ["inapp"]),
                json.dumps(merged.get("task_profile") or {}),
                1 if merged.get("enabled") else 0, next_run, now,
                schedule_id, user_id,
            ),
        )
    return get_schedule(schedule_id, user_id)


def delete_schedule(schedule_id: str, user_id: int) -> bool:
    with database.transaction() as conn:
        return bool(conn.execute(
            "DELETE FROM agent_schedules WHERE id = ? AND user_id = ?",
            (schedule_id, user_id)).rowcount)


def run_now(schedule_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Make a schedule due immediately; returns None when missing or disabled."""
    now = _iso(_now())
    with database.transaction() as conn:
        changed = conn.execute(
            "UPDATE agent_schedules SET next_run_at = ?, locked_until = NULL, "
            "updated_at = ? WHERE id = ? AND user_id = ? AND enabled = 1",
            (now, now, schedule_id, user_id),
        ).rowcount
    return get_schedule(schedule_id, user_id) if changed else None


def claim_due(limit: int = 20, lock_seconds: int = 300,
              now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Atomically claim due schedules; stale locks are retried."""
    now_dt = now or _now()
    now_iso = _iso(now_dt)
    lock_until = _iso(now_dt + timedelta(seconds=max(30, lock_seconds)))
    claimed: List[Dict[str, Any]] = []
    with database.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_schedules WHERE enabled = 1 "
            "AND next_run_at IS NOT NULL AND next_run_at <= ? "
            "AND (locked_until IS NULL OR locked_until < ?) "
            "ORDER BY next_run_at LIMIT ?",
            (now_iso, now_iso, max(1, min(int(limit), 100))),
        ).fetchall()
        for row in rows:
            changed = conn.execute(
                "UPDATE agent_schedules SET locked_until = ?, updated_at = ? "
                "WHERE id = ? AND enabled = 1 AND next_run_at <= ? "
                "AND (locked_until IS NULL OR locked_until < ?)",
                (lock_until, now_iso, row["id"], now_iso, now_iso),
            ).rowcount
            if changed:
                item = dict(row)
                item["locked_until"] = lock_until
                claimed.append(_decode(item))
    return claimed


def complete_run(schedule_id: str) -> Optional[Dict[str, Any]]:
    schedule = get_schedule(schedule_id)
    if not schedule:
        return None
    now = _iso(_now())
    with database.transaction() as conn:
        conn.execute(
            "UPDATE agent_schedules SET last_run_at = ?, next_run_at = ?, "
            "last_error = NULL, locked_until = NULL, updated_at = ? WHERE id = ?",
            (now, next_run_at(schedule), now, schedule_id),
        )
    return get_schedule(schedule_id)


def fail_run(schedule_id: str, error: str) -> Optional[Dict[str, Any]]:
    schedule = get_schedule(schedule_id)
    if not schedule:
        return None
    now = _iso(_now())
    with database.transaction() as conn:
        conn.execute(
            "UPDATE agent_schedules SET last_run_at = ?, next_run_at = ?, "
            "last_error = ?, locked_until = NULL, updated_at = ? WHERE id = ?",
            (now, next_run_at(schedule), str(error)[:2000], now, schedule_id),
        )
    return get_schedule(schedule_id)


def record_run(schedule_id: str, user_id: int, *, agent_id: Optional[str],
               run_id: Optional[str], scheduled_for: Optional[str], status: str,
               result: Optional[str] = None, error: Optional[str] = None,
               notification_id: Optional[str] = None,
               started_at: Optional[str] = None,
               completed_at: Optional[str] = None) -> str:
    run_row_id = str(uuid.uuid4())
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO agent_schedule_runs "
            "(id, schedule_id, user_id, agent_id, run_id, scheduled_for, status, "
            "result, error, notification_id, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_row_id, schedule_id, user_id, agent_id, run_id, scheduled_for,
             status, (result or "")[:20000] or None,
             (error or "")[:4000] or None, notification_id, started_at,
             completed_at or _iso(_now())),
        )
    return run_row_id


def list_runs(schedule_id: str, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_schedule_runs WHERE schedule_id = ? AND user_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (schedule_id, user_id, max(1, min(int(limit), 200))),
        ).fetchall()
    return [dict(row) for row in rows]


def purge_runs(older_than_days: int = 30) -> int:
    cutoff = _iso(_now() - timedelta(days=max(1, older_than_days)))
    with database.transaction() as conn:
        return int(conn.execute(
            "DELETE FROM agent_schedule_runs WHERE started_at < ?", (cutoff,)
        ).rowcount)
