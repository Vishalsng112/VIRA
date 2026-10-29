"""Event visibility ACL shared by the SSE stream and event-list APIs (design 9.3).

Deny by default.  An event is visible to a user principal only if:

1. it carries a ``device_id`` and the user holds an active grant on that device
   (payload is redacted for ``viewer`` grants), or
2. it has no device but is addressed to that user (``actor_user_id`` or
   ``data.user_id``), or
3. it is a device-less system event and the user is an administrator.
"""
import time
from typing import Any, Callable, Dict, Optional

from vira.auth import database
from . import store

PAYLOAD_ROLES = ("owner", "operator")
_REDACTED_KEYS = ("data", "payload")


def _event_user_id(event: Dict[str, Any]) -> Optional[int]:
    actor = event.get("actor_user_id")
    if isinstance(actor, int):
        return actor
    data = event.get("data")
    if isinstance(data, dict) and isinstance(data.get("user_id"), int):
        return data["user_id"]
    return None


class AccessCache:
    """Per-subscriber cache of {device_id: role} with a short TTL.

    A short TTL keeps revocation effective on long-lived streams without
    querying the database for every telemetry event.
    """

    def __init__(self, user_id: int, ttl: float = 3.0, loader: Optional[Callable[[int], Dict[str, str]]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self._user_id = user_id
        self._ttl = ttl
        self._loader = loader or store.accessible_device_ids
        self._clock = clock
        self._loaded_at = -1e9
        self._roles: Dict[str, str] = {}

    def roles(self) -> Dict[str, str]:
        now = self._clock()
        if now - self._loaded_at > self._ttl:
            self._roles = self._loader(self._user_id)
            self._loaded_at = now
        return self._roles

    def invalidate(self) -> None:
        self._loaded_at = -1e9


def authorize_event(event: Dict[str, Any], user_id: int, is_admin: bool, cache: AccessCache) -> Optional[Dict[str, Any]]:
    """Return the event as the user may see it, or None if not visible."""
    device_id = event.get("device_id")
    if device_id:
        role = cache.roles().get(device_id)
        if role is None:
            return None
        if role in PAYLOAD_ROLES:
            return event
        redacted = dict(event)
        for key in _REDACTED_KEYS:
            if key in redacted:
                redacted[key] = None
        redacted["redacted"] = True
        return redacted
    owner = _event_user_id(event)
    if owner is not None:
        return event if owner == user_id else None
    return event if is_admin else None
