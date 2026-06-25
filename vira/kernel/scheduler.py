"""Async job scheduler for periodic and delayed execution"""
import asyncio
from loguru import logger
import heapq
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Callable, Awaitable, Any, Optional
from dataclasses import dataclass, field

# logger = logging.getLogger(__name__)


@dataclass(order=True)
class ScheduledJob:
    priority: float
    id: str = field(compare=False)
    run_at: datetime = field(compare=False)
    callback: Callable[[], Awaitable[None]] = field(compare=False)
    interval_seconds: Optional[float] = field(default=None, compare=False)


class Scheduler:
    """Async job scheduler supporting periodic and one-time tasks"""

    def __init__(self):
        self._job_queue: List[ScheduledJob] = []
        self._jobs_by_id: Dict[str, ScheduledJob] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.metrics_manager = None

    async def start(self):
        """Start the scheduler loop"""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Scheduler started")

    async def stop(self):
        """Stop the scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def schedule_once(self, callback: Callable[[], Awaitable[None]], delay_seconds: float) -> str:
        """Schedule a one-time job"""
        run_at = datetime.now() + timedelta(seconds=delay_seconds)
        job_id = str(uuid.uuid4())
        job = ScheduledJob(
            priority=run_at.timestamp(),
            id=job_id,
            run_at=run_at,
            callback=callback,
            interval_seconds=None,
        )
        heapq.heappush(self._job_queue, job)
        self._jobs_by_id[job_id] = job
        return job_id

    async def schedule_interval(self, callback: Callable[[], Awaitable[None]], interval_seconds: float) -> str:
        """Schedule a recurring job"""
        run_at = datetime.now() + timedelta(seconds=interval_seconds)
        job_id = str(uuid.uuid4())
        job = ScheduledJob(
            priority=run_at.timestamp(),
            id=job_id,
            run_at=run_at,
            callback=callback,
            interval_seconds=interval_seconds,
        )
        heapq.heappush(self._job_queue, job)
        self._jobs_by_id[job_id] = job
        return job_id

    async def cancel(self, job_id: str) -> bool:
        """Cancel a scheduled job"""
        if job_id in self._jobs_by_id:
            del self._jobs_by_id[job_id]
            # Rebuild heap (lazy removal)
            self._job_queue = [j for j in self._job_queue if j.id != job_id]
            heapq.heapify(self._job_queue)
            return True
        return False

    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all scheduled tasks"""
        return [
            {
                "id": j.id,
                "run_at": j.run_at.isoformat(),
                "interval": j.interval_seconds,
            }
            for j in self._job_queue
        ]

    async def _run_loop(self):
        """Main scheduler loop"""
        while self._running:
            now = datetime.now()
            ready_jobs = []

            while self._job_queue and self._job_queue[0].run_at <= now:
                job = heapq.heappop(self._job_queue)
                ready_jobs.append(job)

            for job in ready_jobs:
                start = time.time()
                success = True
                try:
                    await job.callback()
                except Exception as e:
                    success = False
                    logger.error(f"Scheduled job {job.id} failed: {e}")
                finally:
                    duration = time.time() - start
                    if self.metrics_manager:
                        self.metrics_manager.record_job_run(job.id, duration, success)

                # Reschedule recurring jobs
                if job.interval_seconds is not None and job.id in self._jobs_by_id:
                    new_job = ScheduledJob(
                        priority=(datetime.now() + timedelta(seconds=job.interval_seconds)).timestamp(),
                        id=job.id,
                        run_at=datetime.now() + timedelta(seconds=job.interval_seconds),
                        callback=job.callback,
                        interval_seconds=job.interval_seconds,
                    )
                    heapq.heappush(self._job_queue, new_job)
                    self._jobs_by_id[job.id] = new_job
                else:
                    if job.id in self._jobs_by_id:
                        del self._jobs_by_id[job.id]

            # Sleep until next job or default interval
            if self._job_queue:
                wait_seconds = max(0, (self._job_queue[0].run_at - datetime.now()).total_seconds())
                await asyncio.sleep(min(wait_seconds, 1.0))
            else:
                await asyncio.sleep(1.0)