"""Event ingestion policy: allow-list, classes, retention, limits.

Design refs: 7.4 (validation, limits, no arbitrary privileged event types),
FR-EVT-09 (high-volume telemetry is not kept as raw chat-like data),
NFR-PRIV-01 (per-event retention/deletion policy is configurable).
"""
import fnmatch
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Event classes
TELEMETRY = "telemetry"   # high volume; payload not retained unless configured
ACTIVITY = "activity"     # moderate volume; payload retained for a short time
DOMAIN = "domain"         # durable facts; payload retained, goes through the outbox

# Types a device may never emit, whatever the allow-list says.  These can
# trigger privileged behaviour or impersonate server/agent/user events.
ALWAYS_DENIED_PREFIXES = ("user.", "agent.", "command.", "kernel.", "system.", "autonomous.", "admin.")


@dataclass(frozen=True)
class TypeRule:
    pattern: str
    event_class: str
    persist_payload: bool
    keep_latest: bool
    retention_hours: int


DEFAULT_RULES: List[TypeRule] = [
    # Clipboard contents are sensitive: never retain the payload at rest.
    TypeRule("sensor.clipboard.*", TELEMETRY, False, False, 24),
    TypeRule("sensor.*", TELEMETRY, False, True, 24),
    TypeRule("device.telemetry.*", TELEMETRY, False, True, 24),
    TypeRule("file.*", ACTIVITY, True, False, 24 * 7),
    TypeRule("device.*", DOMAIN, True, False, 24 * 30),
]


@dataclass
class EventPolicy:
    rules: List[TypeRule] = field(default_factory=lambda: list(DEFAULT_RULES))
    max_batch_size: int = 100
    max_event_payload_bytes: int = 64 * 1024
    max_batch_bytes: int = 1024 * 1024
    max_future_skew_seconds: int = 300
    max_past_age_days: int = 30
    supported_schema_versions: tuple = (1,)
    events_per_minute: int = 1200          # per device
    heartbeats_per_minute: int = 30        # per device

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]]) -> "EventPolicy":
        cfg = cfg or {}
        policy = cls()
        for key in (
            "max_batch_size", "max_event_payload_bytes", "max_batch_bytes",
            "max_future_skew_seconds", "max_past_age_days",
            "events_per_minute", "heartbeats_per_minute",
        ):
            if key in cfg:
                setattr(policy, key, int(cfg[key]))
        if cfg.get("supported_schema_versions"):
            policy.supported_schema_versions = tuple(int(v) for v in cfg["supported_schema_versions"])
        rules = []
        for item in cfg.get("types") or []:
            rules.append(TypeRule(
                pattern=str(item["pattern"]),
                event_class=str(item.get("class", DOMAIN)),
                persist_payload=bool(item.get("persist_payload", True)),
                keep_latest=bool(item.get("keep_latest", False)),
                retention_hours=int(item.get("retention_hours", 24 * 30)),
            ))
        if rules:
            policy.rules = rules
        return policy

    def rule_for(self, event_type: str) -> Optional[TypeRule]:
        """First matching rule, or None if the type is not allowed."""
        lowered = event_type.lower()
        if lowered.startswith(ALWAYS_DENIED_PREFIXES):
            return None
        for rule in self.rules:
            if fnmatch.fnmatchcase(event_type, rule.pattern):
                return rule
        return None
