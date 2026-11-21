"""Background worker for durable VIRA jobs.

Usage:
    python -m vira.worker --once
    python -m vira.worker --interval 5

The API process stays responsive; retention, rollups, backups and cleanup run
here.  Outbox publication remains in the API process until an external broker
is introduced.
"""
import argparse
import os
import yaml
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict

from loguru import logger

from vira.auth import database
from vira.jobs import queue as jobs
from vira.insights.rollup import refresh_daily
from vira.devices import store as device_store
from vira.devices import commands as command_store
from vira.devices import pairing as pairing_store
from vira.ops.backup import create_backup
from vira.knowledge.consolidation import run_consolidation
from vira import notifications
from vira.agent import schedules as agent_schedules


def _purge_retention(payload: Dict[str, Any]) -> str:
    events = device_store.purge_expired()
    finished = jobs.purge_finished(int(payload.get("job_days", 14)))
    sessions = database.purge_expired_sessions()
    commands = command_store.purge_expired()
    pairing = pairing_store.purge_expired()
    schedule_runs = agent_schedules.purge_runs(int(payload.get("schedule_run_days", 30)))
    return (f"events={events} jobs={finished} sessions={sessions} "
            f"commands={commands} pairing={pairing} schedule_runs={schedule_runs}")


def _deliver_notifications(payload: Dict[str, Any]) -> str:
    config = _section("notifications")
    result = notifications.deliver_pending(
        int(payload.get("limit", 50)),
        webhook_url=config.get("webhook_url") or None,
        timeout=float(config.get("webhook_timeout_seconds", 10)),
        max_attempts=int(config.get("max_attempts", 3)),
    )
    return (f"checked={result['checked']} delivered={result['delivered']} "
            f"failed={result['failed']}")



def _rollup(payload: Dict[str, Any]) -> str:
    written = refresh_daily(int(payload.get("days", 3)))
    return f"rollup_rows={written}"


def _backup(payload: Dict[str, Any]) -> str:
    path = create_backup(keep=int(payload.get("keep", 7)))
    return f"backup={path}"


def _broker_event(payload: Dict[str, Any]) -> str:
    # Durable broker messages are acknowledged by workers.  External brokers
    # deliver directly; this path keeps the database broker observable.
    return f"topic={payload.get('topic')}"


HANDLERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "broker.event": _broker_event,
    "retention.purge": _purge_retention,
    "insights.rollup": _rollup,
    "backup.database": _backup,
    "knowledge.consolidate": run_consolidation,
    "notifications.deliver": _deliver_notifications,
}

def _job_config() -> dict:
    try:
        with open("config.yaml", encoding="utf-8") as handle:
            return (yaml.safe_load(handle) or {}).get("jobs", {}) or {}
    except OSError:
        return {}


def _section(name: str) -> Dict[str, Any]:
    try:
        with open("config.yaml", encoding="utf-8") as handle:
            return (yaml.safe_load(handle) or {}).get(name, {}) or {}
    except OSError:
        return {}


def _periodic_jobs() -> list:
    cfg = _job_config()
    return [
        ("insights.rollup", {"days": int(cfg.get("rollup_days", 3))}, 300),
        ("retention.purge", {
            "job_days": int(cfg.get("retention_days", 14)),
            "schedule_run_days": int(cfg.get("schedule_run_retention_days", 30)),
        }, 3600),
        ("backup.database", {"keep": int(cfg.get("backup_keep", 7))}, 86400),
        ("knowledge.consolidate", {}, 21600),
        ("notifications.deliver", {"limit": 50}, 60),
    ]


class Worker:
    def __init__(self, worker_id: str = None):
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self._last_periodic: Dict[str, float] = {}

    def _enqueue_periodic(self) -> None:
        now = time.monotonic()
        for kind, payload, interval in _periodic_jobs():
            last = self._last_periodic.get(kind, 0)
            if now - last < interval:
                continue
            jobs.enqueue(kind, payload, dedupe_key=f"periodic:{kind}", max_attempts=3)
            self._last_periodic[kind] = now

    def run_once(self) -> int:
        jobs.reclaim_stale(1800)
        self._enqueue_periodic()
        claimed = jobs.claim(self.worker_id, limit=10)
        for job in claimed:
            handler = HANDLERS.get(job["kind"])
            try:
                if handler is None:
                    raise RuntimeError(f"unknown job kind: {job['kind']}")
                result = handler(job.get("payload") or {})
                jobs.complete(job["id"])
                logger.info("job {} ({}) done: {}", job["id"], job["kind"], result)
            except Exception as exc:
                jobs.fail(job["id"], str(exc))
                logger.exception("job {} ({}) failed", job["id"], job["kind"])
        return len(claimed)

    def run_forever(self, interval: float = 5.0) -> None:
        logger.info("VIRA worker {} started", self.worker_id)
        while True:
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("worker loop failed")
                processed = 0
            time.sleep(interval if processed == 0 else 0.2)


def main() -> None:
    parser = argparse.ArgumentParser(prog="vira-worker")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument("--interval", type=float, default=None, help="idle poll interval")
    args = parser.parse_args()
    database.init_db()
    worker = Worker()
    if args.once:
        processed = worker.run_once()
        logger.info("processed {} job(s)", processed)
    else:
        worker.run_forever(args.interval or float(_job_config().get("worker_interval", 5)))


if __name__ == "__main__":
    main()
