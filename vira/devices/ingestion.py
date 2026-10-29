"""Device event ingestion (design 7.4, 7.5, 9.2).

One code path serves remote endpoint devices *and* the server's own sensors:
the server is just another device (``is_server_local``).  Properties:

* device identity comes from the validated credential, never from the payload;
* ``actor_user_id`` is never accepted from a device (always NULL here);
* batches are validated, size-limited and idempotent by ``event_id``;
* durable event types write the event row and the outbox row in the same
  transaction, before the batch is acknowledged;
* the same ``event_id`` with different content is a conflict and is audited.
"""
import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from vira import errors
from vira.auth import database
from vira.auth.principals import DevicePrincipal, local_device_principal
from . import store
from .policy import ACTIVITY, DOMAIN, TELEMETRY, EventPolicy
from .ratelimit import RateLimiter

_TYPE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_\-]+)+$")
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

# Kernel callbacks (set by the kernel; absent in unit tests).
EnvelopeCallback = Callable[[Dict[str, Any]], Awaitable[None]]
KickCallback = Callable[[], Awaitable[Any]]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(content: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def default_priority(event_type: str) -> str:
    lowered = event_type.lower()
    if "error" in lowered or "crash" in lowered:
        return "CRITICAL"
    if "warning" in lowered:
        return "HIGH"
    if "telemetry" in lowered or lowered.startswith("sensor."):
        return "LOW"
    return "NORMAL"


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _uuid_or_none(value: Any, field: str, required: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{field} must be a UUID")


class _ItemError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class EventIngestionService:
    def __init__(
        self,
        policy: Optional[EventPolicy] = None,
        dispatch: Optional[EnvelopeCallback] = None,
        kick_outbox: Optional[KickCallback] = None,
    ):
        self.policy = policy or EventPolicy()
        self._dispatch = dispatch
        self._kick_outbox = kick_outbox
        self._limiter = RateLimiter(self.policy.events_per_minute, burst=self.policy.events_per_minute)

    # ------------------------------------------------------------------ #
    # validation
    # ------------------------------------------------------------------ #
    def _validate_item(self, item: Any, now: datetime) -> Dict[str, Any]:
        if not isinstance(item, dict):
            raise _ItemError("invalid_event", "Event must be an object")
        try:
            event_id = _uuid_or_none(item.get("event_id"), "event_id", required=True)
        except ValueError as exc:
            raise _ItemError("invalid_event_id", str(exc))
        event_type = item.get("type")
        if not isinstance(event_type, str) or len(event_type) > 128 or not _TYPE_RE.match(event_type):
            raise _ItemError("invalid_type", "type must be a dotted lowercase identifier")
        rule = self.policy.rule_for(event_type)
        if rule is None:
            raise _ItemError("type_not_allowed", "Event type is not permitted for devices")
        version = item.get("schema_version", 1)
        if not isinstance(version, int) or isinstance(version, bool) or \
                version not in self.policy.supported_schema_versions:
            raise _ItemError("unsupported_schema_version", "Unsupported schema_version")
        try:
            occurred = _parse_time(item.get("occurred_at"))
        except (ValueError, TypeError) as exc:
            raise _ItemError("invalid_timestamp", f"occurred_at: {exc}")
        if occurred > now + timedelta(seconds=self.policy.max_future_skew_seconds):
            raise _ItemError("invalid_timestamp", "occurred_at is too far in the future")
        if occurred < now - timedelta(days=self.policy.max_past_age_days):
            raise _ItemError("invalid_timestamp", "occurred_at is too old")
        component = item.get("source_component")
        if not isinstance(component, str) or not _COMPONENT_RE.match(component):
            raise _ItemError("invalid_source", "source_component is required (<=64 chars, [A-Za-z0-9_.:-])")
        instance = item.get("source_instance_id")
        if instance is not None and (not isinstance(instance, str) or not _COMPONENT_RE.match(instance)):
            raise _ItemError("invalid_source", "source_instance_id is invalid")
        sequence = item.get("device_sequence")
        if sequence is not None and (not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0):
            raise _ItemError("invalid_sequence", "device_sequence must be a non-negative integer")
        try:
            correlation_id = _uuid_or_none(item.get("correlation_id"), "correlation_id") or str(uuid.uuid4())
            causation_id = _uuid_or_none(item.get("causation_id"), "causation_id")
        except ValueError as exc:
            raise _ItemError("invalid_correlation", str(exc))
        payload = item.get("payload", {})
        if not isinstance(payload, dict):
            raise _ItemError("invalid_payload", "payload must be an object")
        payload_json = canonical_json(payload)
        if len(payload_json.encode("utf-8")) > self.policy.max_event_payload_bytes:
            raise _ItemError("payload_too_large", "Event payload exceeds the size limit")
        return {
            "event_id": event_id, "type": event_type, "rule": rule, "schema_version": version,
            "occurred_at": occurred.isoformat(), "source_component": component,
            "source_instance_id": instance, "device_sequence": sequence,
            "correlation_id": correlation_id, "causation_id": causation_id,
            "payload": payload, "payload_json": payload_json,
            "hash": content_hash({
                "type": event_type, "schema_version": version, "source_component": component,
                "source_instance_id": instance, "device_sequence": sequence,
                "occurred_at": occurred.isoformat(), "payload": payload,
            }),
        }

    # ------------------------------------------------------------------ #
    # core (synchronous; safe to run in a worker thread)
    # ------------------------------------------------------------------ #
    def ingest_sync(
        self,
        principal: DevicePrincipal,
        path_device_id: str,
        events: Any,
        correlation_id: Optional[str] = None,
        enforce_rate_limit: bool = True,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], bool]:
        """Return (response, ephemeral_envelopes, any_durable)."""
        if not principal.has_scope("events:write"):
            raise errors.Forbidden("Credential lacks events:write scope", code="missing_scope")
        if principal.device_id != path_device_id:
            database.record_auth_audit(
                "device", "events.ingest", False, resource=f"device:{principal.device_id}",
                device_id=principal.device_id, actor_type="device", correlation_id=correlation_id,
                details="credential/path device mismatch",
            )
            raise errors.Forbidden("Credential does not belong to this device", code="device_mismatch")
        device = store.get_device(principal.device_id)
        if not device or device["status"] in ("revoked", "retired"):
            raise errors.Unauthorized("Device revoked", code="device_revoked")
        if device["status"] != "active":
            raise errors.Forbidden("Device is not active; send a heartbeat first", code="device_not_active")
        if not isinstance(events, list) or not events:
            raise errors.ValidationFailed("events must be a non-empty list", code="invalid_batch")
        if len(events) > self.policy.max_batch_size:
            raise errors.PayloadTooLarge(
                f"Batch exceeds {self.policy.max_batch_size} events", code="batch_too_large")
        try:
            batch_bytes = len(canonical_json(events).encode("utf-8"))
        except (TypeError, ValueError):
            raise errors.ValidationFailed("events are not serialisable", code="invalid_batch")
        if batch_bytes > self.policy.max_batch_bytes:
            raise errors.PayloadTooLarge("Batch exceeds the byte limit", code="batch_too_large")
        if enforce_rate_limit and not principal.is_server_local:
            allowed, retry = self._limiter.allow(principal.device_id, cost=len(events))
            if not allowed:
                raise errors.RateLimited("Event rate limit exceeded", retry)

        now_dt = datetime.now(timezone.utc)
        received_at = now_dt.isoformat()
        results: List[Dict[str, Any]] = []
        valid: List[Tuple[int, Dict[str, Any]]] = []
        for index, item in enumerate(events):
            try:
                valid.append((index, self._validate_item(item, now_dt)))
                results.append({})
            except _ItemError as err:
                eid = item.get("event_id") if isinstance(item, dict) else None
                results.append({"event_id": eid if isinstance(eid, str) else None,
                                "status": "rejected", "code": err.code, "message": err.message})

        ephemeral: List[Dict[str, Any]] = []
        any_durable = False
        accepted_count = duplicate_count = conflict_count = 0
        last_sequence: Optional[int] = None
        conflicts: List[str] = []

        with database.transaction() as conn:
            for index, norm in valid:
                existing = store.get_event(norm["event_id"], conn)
                if existing:
                    if existing["device_id"] == principal.device_id and existing["payload_hash"] == norm["hash"]:
                        duplicate_count += 1
                        results[index] = {"event_id": norm["event_id"], "status": "duplicate"}
                    else:
                        conflict_count += 1
                        conflicts.append(norm["event_id"])
                        results[index] = {"event_id": norm["event_id"], "status": "rejected",
                                          "code": "event_id_conflict",
                                          "message": "event_id already used with different content"}
                    continue
                rule = norm["rule"]
                expires_at = (now_dt + timedelta(hours=rule.retention_hours)).isoformat()
                store.insert_event(conn, {
                    "event_id": norm["event_id"], "device_id": principal.device_id,
                    "actor_user_id": None,  # device telemetry never carries a human actor
                    "source_component": norm["source_component"],
                    "source_instance_id": norm["source_instance_id"],
                    "event_type": norm["type"], "event_class": rule.event_class,
                    "schema_version": norm["schema_version"],
                    "device_sequence": norm["device_sequence"],
                    "occurred_at": norm["occurred_at"], "received_at": received_at,
                    "correlation_id": norm["correlation_id"], "causation_id": norm["causation_id"],
                    "payload": norm["payload_json"] if rule.persist_payload else None,
                    "payload_hash": norm["hash"], "expires_at": expires_at,
                })
                if rule.keep_latest:
                    store.upsert_latest_state(
                        conn, principal.device_id, norm["type"], norm["event_id"],
                        norm["occurred_at"], received_at, norm["payload_json"])
                envelope = self._envelope(principal.device_id, norm, rule.event_class, received_at)
                if rule.event_class in (DOMAIN, ACTIVITY):
                    store.enqueue_outbox(conn, {**self._event_dict(envelope), "durable": True})
                    any_durable = True
                else:
                    ephemeral.append(envelope)
                accepted_count += 1
                if norm["device_sequence"] is not None:
                    last_sequence = max(last_sequence or 0, norm["device_sequence"])
                results[index] = {"event_id": norm["event_id"], "status": "accepted"}
            rejected_count = sum(1 for r in results if r.get("status") == "rejected")
            store.bump_ingest_stats(conn, principal.device_id, accepted_count > 0,
                                    rejected_count, last_sequence)
        for eid in conflicts:
            database.record_auth_audit(
                "device", "events.id_conflict", False, resource=f"event:{eid}",
                device_id=principal.device_id, actor_type="device", correlation_id=correlation_id,
                details="event_id reused with different content",
            )
        response = {
            "accepted": accepted_count, "duplicates": duplicate_count,
            "rejected": rejected_count, "results": results,
            "correlation_id": correlation_id,
        }
        return response, ephemeral, any_durable

    # ------------------------------------------------------------------ #
    # async wrappers
    # ------------------------------------------------------------------ #
    async def ingest(
        self,
        principal: DevicePrincipal,
        path_device_id: str,
        events: Any,
        correlation_id: Optional[str] = None,
        enforce_rate_limit: bool = True,
    ) -> Dict[str, Any]:
        response, ephemeral, any_durable = await asyncio.to_thread(
            self.ingest_sync, principal, path_device_id, events, correlation_id, enforce_rate_limit
        )
        # Post-commit delivery.  The batch is already durable; delivery failures
        # must not fail the acknowledgement (the outbox retries durable events).
        if self._dispatch:
            for envelope in ephemeral:
                try:
                    await self._dispatch(envelope)
                except Exception:  # pragma: no cover - defensive
                    pass
        if any_durable and self._kick_outbox:
            try:
                await self._kick_outbox()
            except Exception:  # pragma: no cover - defensive
                pass
        return response

    async def ingest_local(
        self,
        device_id: str,
        event_type: str,
        data: Any,
        source_component: str,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Server-side sensors publish through the same pipeline as remote devices."""
        item = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "schema_version": 1,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source_component": _safe_component(source_component),
            "source_instance_id": "server-local",
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "payload": data if isinstance(data, dict) else {"value": data},
        }
        return await self.ingest(
            local_device_principal(device_id), device_id, [item], correlation_id,
            enforce_rate_limit=False,
        )

    # ------------------------------------------------------------------ #
    # envelope helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _envelope(device_id: str, norm: Dict[str, Any], event_class: str, received_at: str) -> Dict[str, Any]:
        """Canonical stored envelope (design 7.5); identity fields are server-resolved."""
        return {
            "event_id": norm["event_id"],
            "type": norm["type"],
            "kind": "domain",
            "event_class": event_class,
            "schema_version": norm["schema_version"],
            "source": {"kind": "device_component", "component_id": norm["source_component"],
                       "instance_id": norm["source_instance_id"]},
            "device_id": device_id,
            "actor_user_id": None,
            "occurred_at": norm["occurred_at"],
            "received_at": received_at,
            "device_sequence": norm["device_sequence"],
            "correlation_id": norm["correlation_id"],
            "causation_id": norm["causation_id"],
            "payload": norm["payload"],
        }

    @staticmethod
    def _event_dict(envelope: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten the envelope to the ``Event.dict()`` shape used by the outbox/bus."""
        return {
            "type": envelope["type"],
            "data": envelope["payload"],
            "source": envelope["source"]["component_id"],
            "kind": envelope["kind"],
            "priority": default_priority(envelope["type"]),
            "event_id": envelope["event_id"],
            "correlation_id": envelope["correlation_id"],
            "causation_id": envelope["causation_id"],
            "timestamp": time.time(),
            "schema_version": envelope["schema_version"],
            "verified": True,  # authenticated device + allow-listed type
            "durable": envelope["event_class"] in (DOMAIN, ACTIVITY),
            "device_id": envelope["device_id"],
            "actor_user_id": None,
            "source_component": envelope["source"]["component_id"],
            "source_instance_id": envelope["source"]["instance_id"],
            "device_sequence": envelope["device_sequence"],
            "occurred_at": envelope["occurred_at"],
            "received_at": envelope["received_at"],
        }

    def to_event_dict(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        return self._event_dict(envelope)


def _safe_component(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:\-]", "_", str(name or "unknown"))[:64]
    return cleaned or "unknown"
