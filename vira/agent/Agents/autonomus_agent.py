"""Autonomous behavior-learning agent.

The agent observes sensor events, learns rolling baselines, and emits
auditable decisions. It deliberately does not execute host commands directly.
"""
from collections import defaultdict, deque
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional
import time

from loguru import logger

from vira.agent.base import BaseAgent
from vira.agent.toolcalls import extract_json
from vira.agent_orchestration.registry import AgentCapability
from vira.agent_runtime.runtime import AgentContext


class AutonomousAgent(BaseAgent):
    """Learn normal sensor behavior and react to sustained deviations."""

    def __init__(
        self,
        runtime,
        window_size: int = 30,
        anomaly_sigma: float = 2.0,
        anomaly_minimum: float = 80.0,
        consecutive_anomalies: int = 3,
        decision_cooldown_seconds: float = 300.0,
        learning_interval: int = 10,
        llm_triage: bool = False,
        subscribed_events: Optional[List[str]] = None,
        **kwargs,
    ):
        super().__init__(
            name=kwargs.get("name", "AutonomousBehaviorAgent"),
            description=kwargs.get(
                "description",
                "Learns behavior patterns from sensor data and emits safe autonomous decisions.",
            ),
            runtime=runtime,
        )
        if window_size < 5:
            raise ValueError("window_size must be at least 5")
        if anomaly_sigma <= 0 or anomaly_minimum < 0:
            raise ValueError("anomaly thresholds must be positive")
        if consecutive_anomalies < 1 or learning_interval < 1:
            raise ValueError("consecutive_anomalies and learning_interval must be positive")
        if decision_cooldown_seconds < 0:
            raise ValueError("decision_cooldown_seconds cannot be negative")

        self.window_size = window_size
        self.anomaly_sigma = anomaly_sigma
        self.anomaly_minimum = anomaly_minimum
        self.consecutive_anomalies = consecutive_anomalies
        self.decision_cooldown_seconds = decision_cooldown_seconds
        self.learning_interval = learning_interval
        # Optional: ask the local LLM for severity + a short explanation of a
        # confirmed anomaly. The statistical detector stays the source of truth.
        self.llm_triage = llm_triage
        # State is kept per (device, metric): one device's load must never
        # distort another device's baseline.
        self._samples: Dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )
        self._anomaly_counts: Dict[str, int] = defaultdict(int)
        self._last_decisions: Dict[str, float] = {}
        self._observations = 0
        self._subscribed_events = subscribed_events or [
            "sensor.hardware.state",
            "sensor.activity.state",
        ]
        self._capabilities = [
            AgentCapability(
                name="learn_behavior",
                description="Learn rolling sensor baselines and emit autonomous decisions.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        ]

    async def think(self, context: AgentContext, **kwargs) -> Dict[str, Any]:
        event = kwargs.get("event")
        if event is None or not isinstance(event.data, dict):
            return {"decision": "ignore", "reason": "event has no structured data"}
        device_id = getattr(event, "device_id", None) or "unknown-device"
        metrics = self._extract_metrics(event.type, event.data)
        if not metrics:
            return {"decision": "ignore", "reason": "no numeric metrics", "event_type": event.type}

        anomalies = []
        for metric, value in metrics.items():
            key = f"{device_id}:{metric}"
            history = self._samples[key]
            baseline = self._baseline(history)
            history.append(value)
            if baseline and self._is_anomaly(value, baseline):
                self._anomaly_counts[key] += 1
                anomalies.append({
                    "device_id": device_id,
                    "metric": metric,
                    "value": value,
                    "baseline": round(baseline["mean"], 3),
                    "deviation": round(value - baseline["mean"], 3),
                    "consecutive_count": self._anomaly_counts[key],
                })
            else:
                self._anomaly_counts[key] = 0
        self._observations += 1
        return {
            "decision": "evaluate",
            "event_type": event.type,
            "device_id": device_id,
            "metrics": metrics,
            "anomalies": anomalies,
            "observation_count": self._observations,
        }

    async def plan(self, thought: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
        if thought.get("decision") != "evaluate":
            return []
        steps: List[Dict[str, Any]] = []
        if thought.get("observation_count", 0) % self.learning_interval == 0:
            steps.append({"action": "learn", "thought": thought})
        for anomaly in thought.get("anomalies", []):
            if anomaly["consecutive_count"] >= self.consecutive_anomalies:
                steps.append({"action": "decide", "anomaly": anomaly})
        return steps

    async def act(self, plan: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
        results = []
        for step in plan:
            if step["action"] == "learn":
                results.append(await self._store_pattern())
            elif step["action"] == "decide":
                decision = await self._make_decision(step["anomaly"], kwargs.get("event"))
                if decision:
                    results.append(decision)
        return results

    async def reflect(self, result: Any, **kwargs) -> Dict[str, Any]:
        return {"status": "processed", "observations": self._observations, "actions": len(result or [])}

    @staticmethod
    def _extract_metrics(event_type: str, data: Dict[str, Any]) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        paths = {
            "cpu.usage_percent": ("cpu", "usage_percent"),
            "memory.percent": ("memory", "percent"),
            "disk.percent": ("disk", "percent"),
            "gpu.load": ("gpu", "load"),
            "battery.percent": ("battery", "percent"),
        }
        if event_type == "sensor.hardware.state":
            for name, path in paths.items():
                value = data.get(path[0], {}).get(path[1])
                if isinstance(value, (int, float)):
                    metrics[name] = float(value)
        elif event_type == "sensor.activity.state":
            value = data.get("activity_score")
            if isinstance(value, (int, float)):
                metrics["activity_score"] = float(value)
        return metrics

    def _baseline(self, history: deque[float]) -> Optional[Dict[str, float]]:
        if len(history) < 5:
            return None
        values = list(history)
        return {"mean": mean(values), "stddev": pstdev(values)}

    def _is_anomaly(self, value: float, baseline: Dict[str, float]) -> bool:
        threshold = max(
            self.anomaly_minimum,
            baseline["mean"] + self.anomaly_sigma * baseline["stddev"],
        )
        return value >= threshold

    async def _store_pattern(self) -> Dict[str, Any]:
        """Persist learned baselines, one memory per device (device-scoped ACL)."""
        per_device: Dict[str, Dict[str, Any]] = defaultdict(dict)
        for key, history in self._samples.items():
            if not history:
                continue
            device_id, _, metric = key.partition(":")
            per_device[device_id][metric] = {
                "samples": len(history),
                "mean": round(mean(history), 3),
                "min": round(min(history), 3),
                "max": round(max(history), 3),
            }
        for device_id, summary in per_device.items():
            await self.runtime.memory_operation(
                self.agent_id,
                "store",
                content=f"Learned behavior pattern after {self._observations} observations: {summary}",
                memory_type="behavior_pattern",
                metadata={"type": "learned_behavior", "observations": self._observations,
                          "device_id": device_id},
                importance=0.3,
                device_id=device_id if device_id != "unknown-device" else None,
            )
        return {"learned_pattern": dict(per_device)}

    async def _triage(self, anomaly: Dict[str, Any]) -> Dict[str, Any]:
        """One short LLM call; any failure just leaves the decision unchanged."""
        prompt = (
            "You triage device anomalies. Reply with ONLY JSON: "
            '{"severity": "low|medium|high", "explanation": "<one sentence>"}\n'
            f"Metric {anomaly['metric']} on {anomaly.get('device_id')} is {anomaly['value']} "
            f"(baseline {anomaly['baseline']}) for {anomaly['consecutive_count']} consecutive samples."
        )
        try:
            response = await self.runtime.call_llm(self.agent_id, prompt, temperature=0.1, max_tokens=120)
            data = extract_json(getattr(response, "text", None) or str(response)) or {}
        except Exception as exc:
            logger.debug("LLM triage skipped: {}", exc)
            return {}
        severity = data.get("severity")
        out: Dict[str, Any] = {}
        if severity in ("low", "medium", "high"):
            out["severity"] = severity
        if isinstance(data.get("explanation"), str):
            out["explanation"] = data["explanation"][:300]
        return out

    async def _make_decision(self, anomaly: Dict[str, Any], event: Any) -> Optional[Dict[str, Any]]:
        metric = anomaly["metric"]
        device_id = anomaly.get("device_id")
        cooldown_key = f"{device_id}:{metric}"
        now = time.monotonic()
        if now - self._last_decisions.get(cooldown_key, 0.0) < self.decision_cooldown_seconds:
            return None
        self._last_decisions[cooldown_key] = now
        decision = {
            "device_id": device_id,
            "decision": "notify",
            "reason": "sustained_behavior_anomaly",
            "metric": metric,
            "value": anomaly["value"],
            "baseline": anomaly["baseline"],
            "source_event": getattr(event, "type", None),
            "agent_id": self.agent_id,
        }
        if self.llm_triage:
            decision.update(await self._triage(anomaly))
        await self.runtime.memory_operation(
            self.agent_id,
            "store",
            content=f"Autonomous decision: {decision}",
            memory_type="autonomous_decision",
            metadata={"type": "behavior_anomaly", "metric": metric, "device_id": device_id},
            importance=0.8,
            device_id=device_id if device_id != "unknown-device" else None,
        )
        await self.send_event("autonomous.decision", decision)
        logger.warning("Autonomous behavior decision: {}", decision)
        return decision