"""Observability and telemetry with automatic system & framework metrics"""
import asyncio
import time
from loguru import logger
import functools
from collections import defaultdict
from typing import Dict, List, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

try:
    import psutil
except ImportError:
    psutil = None
    logger.warning(
        "psutil not installed. System metrics will be unavailable. "
        "Install with: pip install psutil"
    )



@dataclass
class Metric:
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsManager:
    """
    Collects and exposes metrics for monitoring.

    Automatically gathers system metrics (CPU, memory, disk, network) in the
    background and provides counters/gauges/histograms for framework components.
    """

    def __init__(self, retention_minutes: int = 60):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._retention_seconds = retention_minutes * 60
        self._start_time = time.time()

        self._system_task: Optional[asyncio.Task] = None
        self._running = False

        self._event_counters = defaultdict(int)
        self._job_counters = defaultdict(int)
        self._module_counters = defaultdict(int)

    async def start(self):
        self._running = True
        if psutil is not None:
            self._system_task = asyncio.create_task(self._collect_system_metrics())
            logger.info("MetricsManager started with system metrics collection")
        else:
            logger.info("MetricsManager started (system metrics disabled)")

    async def stop(self):
        self._running = False
        if self._system_task:
            self._system_task.cancel()
            try:
                await self._system_task
            except asyncio.CancelledError:
                pass
        logger.info("MetricsManager stopped")

    def increment_counter(self, name: str, value: int = 1, labels: Dict[str, str] = None) -> None:
        key = self._build_key(name, labels)
        self._counters[key] += value

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        key = self._build_key(name, labels)
        self._gauges[key] = value

    def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        key = self._build_key(name, labels)
        self._histograms[key].append(value)
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-500:]

    def _build_key(self, name: str, labels: Dict[str, str] = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    # --- Framework‑specific helpers ---
    def record_event_published(self, event_type: str, source: str = "unknown") -> None:
        self.increment_counter("events_published_total", labels={"type": event_type, "source": source})
        self._event_counters[event_type] += 1

    def record_event_processed(self, event_type: str, duration_seconds: float) -> None:
        self.observe_histogram("event_processing_duration_seconds", duration_seconds,
                               labels={"type": event_type})

    def record_job_run(self, job_id: str, duration_seconds: float, success: bool = True) -> None:
        status = "success" if success else "failure"
        self.increment_counter("jobs_run_total", labels={"job_id": job_id, "status": status})
        self.observe_histogram("job_duration_seconds", duration_seconds, labels={"job_id": job_id})
        self._job_counters[job_id] += 1

    def record_module_load(self, module_name: str, duration_seconds: float) -> None:
        self.observe_histogram("module_load_duration_seconds", duration_seconds,
                               labels={"module": module_name})
        self._module_counters[module_name] += 1

    def record_module_start(self, module_name: str) -> None:
        # Active modules gauge: we'll just update with total count
        pass

    def record_error(self, error_type: str, source: str = "unknown") -> None:
        self.increment_counter("errors_total", labels={"type": error_type, "source": source})

    # --- System metrics background loop ---
    async def _collect_system_metrics(self):
        while self._running:
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                self.set_gauge("cpu_usage_percent", cpu_percent)
                load_avg = psutil.getloadavg()
                self.set_gauge("load_avg_1min", load_avg[0])
                self.set_gauge("load_avg_5min", load_avg[1])
                self.set_gauge("load_avg_15min", load_avg[2])

                mem = psutil.virtual_memory()
                self.set_gauge("memory_total_bytes", mem.total)
                self.set_gauge("memory_available_bytes", mem.available)
                self.set_gauge("memory_used_bytes", mem.used)
                self.set_gauge("memory_percent", mem.percent)

                disk = psutil.disk_usage('/')
                self.set_gauge("disk_total_bytes", disk.total)
                self.set_gauge("disk_used_bytes", disk.used)
                self.set_gauge("disk_free_bytes", disk.free)
                self.set_gauge("disk_percent", disk.percent)

                net = psutil.net_io_counters()
                self.set_gauge("network_bytes_sent_total", net.bytes_sent)
                self.set_gauge("network_bytes_recv_total", net.bytes_recv)

                self.set_gauge("process_count", len(psutil.pids()))
                try:
                    self.set_gauge("open_fds", len(psutil.Process().open_files()))
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error collecting system metrics: {e}")
            await asyncio.sleep(10)

    def get_metrics(self) -> Dict[str, Any]:
        uptime = time.time() - self._start_time
        hist_summary = {}
        for key, values in self._histograms.items():
            if values:
                sorted_vals = sorted(values)
                hist_summary[key] = {
                    "count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "p50": sorted_vals[int(len(sorted_vals) * 0.50)],
                    "p90": sorted_vals[int(len(sorted_vals) * 0.90)],
                    "p95": sorted_vals[int(len(sorted_vals) * 0.95)],
                    "p99": sorted_vals[int(len(sorted_vals) * 0.99)] if len(sorted_vals) > 100 else None,
                }
        return {
            "uptime_seconds": uptime,
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histogram_summary": hist_summary,
            "framework": {
                "events_by_type": dict(self._event_counters),
                "jobs_by_id": dict(self._job_counters),
                "modules_loaded": dict(self._module_counters),
            }
        }

    def reset(self):
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._event_counters.clear()
        self._job_counters.clear()
        self._module_counters.clear()
