"""Device application service (design sections 4.2, 7.3, 9.3, 9.4).

No HTTP types here: routes translate ``vira.errors`` into responses.  Every
state-changing operation is audited.  Authorization lives in this layer (and in
``store``), not in the UI or route decorators (NFR-SEC-02).
"""
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from vira import errors
from vira.auth import auth, database
from vira.auth.principals import DevicePrincipal, UserPrincipal
from . import store
from .policy import EventPolicy
from .ratelimit import RateLimiter

PLATFORMS = ("android", "ios", "windows", "macos", "linux", "web", "other")
DEVICE_TYPES = ("phone", "tablet", "laptop", "desktop", "server", "browser", "iot", "other")
DEFAULT_SCOPES = ("events:write", "heartbeat")
_CAPABILITY_RE = re.compile(r"^[a-z0-9_.:-]{1,64}$")
CAPABILITY_STATES = ("available", "unavailable", "permission_denied", "degraded")

# Device state machine (design 9.4).  Revocation is terminal for the credential;
# a revoked device is never silently reactivated.
_TRANSITIONS = {
    "pending": {"active", "revoked", "retired"},
    "active": {"revoked", "retired"},
    "revoked": {"retired"},
    "retired": set(),
}


def can_transition(current: str, new: str) -> bool:
    return new in _TRANSITIONS.get(current, set())


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class DeviceService:
    def __init__(
        self,
        policy: Optional[EventPolicy] = None,
        credential_ttl_days: Optional[int] = 365,
    ):
        self.policy = policy or EventPolicy()
        self.credential_ttl_days = credential_ttl_days
        self._heartbeat_limiter = RateLimiter(self.policy.heartbeats_per_minute)
        self._last_touch: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # validation helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean_capabilities(capabilities: Optional[Iterable[str]]) -> List[str]:
        result: List[str] = []
        for cap in capabilities or []:
            if not isinstance(cap, str) or not _CAPABILITY_RE.match(cap):
                raise errors.ValidationFailed("Invalid capability name", code="invalid_capability")
            if cap not in result:
                result.append(cap)
        if len(result) > 64:
            raise errors.ValidationFailed("Too many capabilities", code="invalid_capability")
        return result

    @staticmethod
    def _clean_text(value: Optional[str], field: str, max_len: int, required: bool = False) -> Optional[str]:
        if value is None:
            if required:
                raise errors.ValidationFailed(f"{field} is required")
            return None
        value = value.strip()
        if required and not value:
            raise errors.ValidationFailed(f"{field} is required")
        if len(value) > max_len:
            raise errors.ValidationFailed(f"{field} must be at most {max_len} characters")
        return value

    # ------------------------------------------------------------------ #
    # views
    # ------------------------------------------------------------------ #
    def device_view(self, device: Dict[str, Any], role: Optional[str] = None,
                    with_health: bool = False) -> Dict[str, Any]:
        view = {
            "device_id": device["id"],
            "display_name": device["display_name"],
            "platform": device["platform"],
            "device_type": device["device_type"],
            "os_version": device.get("os_version"),
            "client_version": device.get("client_version"),
            "capabilities": device.get("capabilities", []),
            "capability_status": device.get("capability_status", {}),
            "status": device["status"],
            "is_server_local": device.get("is_server_local", False),
            "created_at": device.get("created_at"),
            "last_seen_at": device.get("last_seen_at"),
            "revoked_at": device.get("revoked_at"),
            "access_role": role,
        }
        if with_health:
            view["health"] = {
                "last_event_at": device.get("last_event_at"),
                "ingest_error_count": device.get("ingest_error_count", 0),
                "last_accepted_sequence": device.get("last_accepted_sequence"),
                "queue_backlog": device.get("queue_backlog"),
                "credential": store.credential_summary(device["id"]),
            }
        return view

    # ------------------------------------------------------------------ #
    # audit
    # ------------------------------------------------------------------ #
    @staticmethod
    def _audit(actor, action: str, allowed: bool, device_id: Optional[str],
               correlation_id: Optional[str] = None, target: Optional[str] = None,
               details: Optional[str] = None) -> None:
        if isinstance(actor, DevicePrincipal):
            database.record_auth_audit(
                "device", action, allowed, resource=f"device:{device_id}", device_id=device_id,
                correlation_id=correlation_id, details=details, actor_type="device", target=target,
            )
        else:
            database.record_auth_audit(
                "device", action, allowed, user_id=actor.user_id,
                session_id=getattr(actor, "session_id", None),
                resource=f"device:{device_id}" if device_id else None, device_id=device_id,
                correlation_id=correlation_id, details=details, target=target,
            )

    # ------------------------------------------------------------------ #
    # authorization
    # ------------------------------------------------------------------ #
    def authorize(
        self,
        actor: UserPrincipal,
        device_id: str,
        roles: Sequence[str] = ("owner", "operator", "viewer"),
        allow_admin: bool = False,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Return (device, access_role).  Deny by default.

        Unknown device *and* device the user has no grant on both yield 404 so
        existence is not disclosed.  A grant with insufficient role yields 403.
        """
        device = store.get_device(device_id)
        if not device:
            raise errors.NotFound("Device not found")
        role = store.get_access(actor.user_id, device_id)
        if role is None:
            if allow_admin and actor.is_admin:
                return device, None
            raise errors.NotFound("Device not found")
        if role not in roles:
            if allow_admin and actor.is_admin:
                return device, role
            raise errors.Forbidden("Insufficient device access", code="insufficient_device_access")
        return device, role

    # ------------------------------------------------------------------ #
    # registration and credentials
    # ------------------------------------------------------------------ #
    def _credential_expiry(self) -> Optional[str]:
        if not self.credential_ttl_days:
            return None
        return _iso(datetime.now(timezone.utc) + timedelta(days=self.credential_ttl_days))

    def register_device(
        self,
        actor: UserPrincipal,
        display_name: str,
        platform: str,
        device_type: str,
        os_version: Optional[str] = None,
        client_version: Optional[str] = None,
        capabilities: Optional[Iterable[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        display_name = self._clean_text(display_name, "display_name", 100, required=True)
        if platform not in PLATFORMS:
            raise errors.ValidationFailed(f"platform must be one of {list(PLATFORMS)}")
        if device_type not in DEVICE_TYPES:
            raise errors.ValidationFailed(f"device_type must be one of {list(DEVICE_TYPES)}")
        os_version = self._clean_text(os_version, "os_version", 100)
        client_version = self._clean_text(client_version, "client_version", 50)
        caps = self._clean_capabilities(capabilities)
        token = store.new_credential_token()
        with database.transaction() as conn:
            # The server picks every authoritative field: id, owner, state, scope.
            device_id = store.insert_device(
                conn, display_name, platform, device_type, os_version, client_version,
                caps, status="pending", created_by_user_id=actor.user_id,
            )
            credential_id = store.insert_credential(
                conn, device_id, token, DEFAULT_SCOPES, self._credential_expiry()
            )
            store.grant_access(conn, actor.user_id, device_id, "owner", actor.user_id)
            expires_at = conn.execute(
                "SELECT expires_at FROM device_credentials WHERE id = ?", (credential_id,)
            ).fetchone()["expires_at"]
        self._audit(actor, "device.register", True, device_id, correlation_id)
        device = store.get_device(device_id)
        result = self.device_view(device, role="owner")
        # Raw credential is returned exactly once and never stored or logged.
        result["credential"] = {
            "credential_id": credential_id,
            "token": token,
            "scopes": list(DEFAULT_SCOPES),
            "expires_at": expires_at,
        }
        return result

    def rotate_credential(
        self,
        actor: UserPrincipal,
        device_id: str,
        current_password: Optional[str],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        device, _ = self.authorize(actor, device_id, roles=("owner",), allow_admin=True)
        # Step-up authentication: re-verify the acting user's password.
        user = database.get_user_by_id(actor.user_id)
        if not current_password or not user or not auth.verify_password(current_password, user["password_hash"]):
            self._audit(actor, "device.credential.rotate", False, device_id, correlation_id,
                        details="step-up failed")
            raise errors.Forbidden("Password confirmation required", code="step_up_required")
        if device["status"] not in ("pending", "active"):
            raise errors.Conflict("Device is not rotatable in its current state", code="invalid_state")
        token = store.new_credential_token()
        with database.transaction() as conn:
            old_ids = store.revoke_credentials(conn, device_id)
            credential_id = store.insert_credential(
                conn, device_id, token, DEFAULT_SCOPES, self._credential_expiry(),
                rotated_from=old_ids[-1] if old_ids else None,
            )
            expires_at = conn.execute(
                "SELECT expires_at FROM device_credentials WHERE id = ?", (credential_id,)
            ).fetchone()["expires_at"]
        self._audit(actor, "device.credential.rotate", True, device_id, correlation_id)
        return {"device_id": device_id, "credential": {
            "credential_id": credential_id, "token": token,
            "scopes": list(DEFAULT_SCOPES), "expires_at": expires_at}}

    def authenticate_credential(self, token: Optional[str], required_scope: Optional[str] = None) -> DevicePrincipal:
        """Resolve a presented device credential to a DevicePrincipal (401 on failure)."""
        if not token or not token.startswith(store.CREDENTIAL_PREFIX):
            raise errors.Unauthorized("Invalid device credential", code="invalid_credential")
        found = store.find_credential(token)
        if not found or found["credential_revoked_at"]:
            raise errors.Unauthorized("Invalid device credential", code="invalid_credential")
        if found["expires_at"] and found["expires_at"] <= store.utc_now():
            raise errors.Unauthorized("Device credential expired", code="credential_expired")
        if found["device_status"] in ("revoked", "retired"):
            raise errors.Unauthorized("Device revoked", code="device_revoked")
        if required_scope and required_scope not in found["scopes"]:
            raise errors.Forbidden("Credential lacks required scope", code="missing_scope")
        now = time.monotonic()
        if now - self._last_touch.get(found["credential_id"], 0.0) > 60:
            self._last_touch[found["credential_id"]] = now
            store.touch_credential(found["credential_id"])
        return DevicePrincipal(
            device_id=found["device_id"],
            credential_id=found["credential_id"],
            scopes=found["scopes"],
            device_status=found["device_status"],
            is_server_local=found["is_server_local"],
        )

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def list_devices(self, actor: UserPrincipal, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        after = self._cursor(cursor)
        limit = min(max(limit, 1), 200)
        rows = store.list_devices_for_user(actor.user_id, limit + 1, after)
        page = rows[:limit]
        return {
            "devices": [self.device_view(d, role=d.get("access_role")) for d in page],
            "next_cursor": str(page[-1]["_cursor"]) if len(rows) > limit and page else None,
        }

    def list_fleet(self, actor: UserPrincipal, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        if not actor.is_admin:
            raise errors.Forbidden("Administrator role required")
        rows = store.list_all_devices(min(max(limit, 1), 200) + 1, self._cursor(cursor))
        page = rows[:min(max(limit, 1), 200)]
        return {
            "devices": [self.device_view(d, with_health=True) for d in page],
            "next_cursor": str(page[-1]["_cursor"]) if len(rows) > len(page) and page else None,
        }

    def get_device(self, actor: UserPrincipal, device_id: str) -> Dict[str, Any]:
        device, role = self.authorize(actor, device_id, allow_admin=True)
        view = self.device_view(device, role=role, with_health=True)
        if role in ("owner",) or (role is None and actor.is_admin):
            view["access"] = store.list_access(device_id)
        return view

    def update_device(self, actor: UserPrincipal, device_id: str, display_name: Optional[str] = None,
                      correlation_id: Optional[str] = None) -> Dict[str, Any]:
        device, role = self.authorize(actor, device_id, roles=("owner",), allow_admin=True)
        if display_name is None:
            raise errors.ValidationFailed("Nothing to update")
        display_name = self._clean_text(display_name, "display_name", 100, required=True)
        with database.transaction() as conn:
            store.update_device_fields(conn, device_id, display_name=display_name)
        self._audit(actor, "device.update", True, device_id, correlation_id)
        return self.device_view(store.get_device(device_id), role=role)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def _set_status(self, device: Dict[str, Any], new_status: str, revoke_creds: bool) -> None:
        if not can_transition(device["status"], new_status):
            raise errors.Conflict(
                f"Cannot change device from {device['status']} to {new_status}", code="invalid_state"
            )
        with database.transaction() as conn:
            fields = {"status": new_status}
            if new_status in ("revoked", "retired") and not device.get("revoked_at"):
                fields["revoked_at"] = store.utc_now()
            store.update_device_fields(conn, device["id"], **fields)
            if revoke_creds:
                store.revoke_credentials(conn, device["id"])

    def revoke_device(self, actor: UserPrincipal, device_id: str, correlation_id: Optional[str] = None) -> None:
        device, _ = self.authorize(actor, device_id, roles=("owner",), allow_admin=True)
        if device["is_server_local"]:
            raise errors.Conflict("The server's own device cannot be revoked", code="server_device_protected")
        if device["status"] == "revoked":
            return
        try:
            self._set_status(device, "revoked", revoke_creds=True)
        except errors.Conflict:
            self._audit(actor, "device.revoke", False, device_id, correlation_id, details="invalid state")
            raise
        self._audit(actor, "device.revoke", True, device_id, correlation_id)

    def retire_device(self, actor: UserPrincipal, device_id: str, correlation_id: Optional[str] = None) -> None:
        device, _ = self.authorize(actor, device_id, roles=("owner",), allow_admin=True)
        if device["is_server_local"]:
            raise errors.Conflict("The server's own device cannot be retired", code="server_device_protected")
        if device["status"] == "retired":
            return
        self._set_status(device, "retired", revoke_creds=True)
        self._audit(actor, "device.retire", True, device_id, correlation_id)

    # ------------------------------------------------------------------ #
    # access grants
    # ------------------------------------------------------------------ #
    def grant_access(self, actor: UserPrincipal, device_id: str, user_public_id: str, role: str,
                     correlation_id: Optional[str] = None) -> Dict[str, Any]:
        device, _ = self.authorize(actor, device_id, roles=("owner",), allow_admin=True)
        if role not in store.ACCESS_ROLES:
            raise errors.ValidationFailed(f"access_role must be one of {list(store.ACCESS_ROLES)}")
        if device["status"] in ("revoked", "retired"):
            raise errors.Conflict("Device is revoked or retired", code="invalid_state")
        target = database.get_user_by_public_id(user_public_id)
        if not target or target["status"] != "active":
            raise errors.NotFound("User not found")
        with database.transaction() as conn:
            current = store.get_access(int(target["id"]), device_id, conn)
            if current == "owner" and role != "owner" and \
                    store.count_active_owners(conn, device_id, excluding_user=int(target["id"])) == 0:
                raise errors.Conflict("A device must keep at least one owner", code="last_owner")
            store.grant_access(conn, int(target["id"]), device_id, role, actor.user_id)
        self._audit(actor, "device.access.grant", True, device_id, correlation_id,
                    target=user_public_id, details=f"role={role}")
        return {"device_id": device_id, "user_id": user_public_id, "access_role": role, "status": "active"}

    def revoke_access(self, actor: UserPrincipal, device_id: str, user_public_id: str,
                      correlation_id: Optional[str] = None) -> None:
        self.authorize(actor, device_id, roles=("owner",), allow_admin=True)
        target = database.get_user_by_public_id(user_public_id)
        if not target:
            raise errors.NotFound("User not found")
        with database.transaction() as conn:
            if store.get_access(int(target["id"]), device_id, conn) == "owner" and \
                    store.count_active_owners(conn, device_id, excluding_user=int(target["id"])) == 0 \
                    and not actor.is_admin:
                raise errors.Conflict("A device must keep at least one owner", code="last_owner")
            changed = store.revoke_access(conn, int(target["id"]), device_id)
        if not changed:
            raise errors.NotFound("Access grant not found")
        self._audit(actor, "device.access.revoke", True, device_id, correlation_id, target=user_public_id)

    def validate_user_device(self, actor: UserPrincipal, device_id: str) -> str:
        """Validate the optional device context of a user action (e.g. chat).

        The user must hold an owner/operator grant and the device must be
        active.  Anything else is reported as 404 so a client cannot probe for
        other users' device ids.
        """
        device = store.get_device(device_id)
        role = store.get_access(actor.user_id, device_id) if device else None
        if not device or role not in ("owner", "operator") or device["status"] != "active":
            raise errors.NotFound("Device not found", code="device_not_found")
        return device_id

    # ------------------------------------------------------------------ #
    # device-authenticated operations
    # ------------------------------------------------------------------ #
    def heartbeat(
        self,
        principal: DevicePrincipal,
        path_device_id: str,
        client_version: Optional[str] = None,
        os_version: Optional[str] = None,
        capabilities: Optional[Iterable[str]] = None,
        capability_status: Optional[Dict[str, str]] = None,
        queue_backlog: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if principal.device_id != path_device_id:
            self._audit(principal, "device.heartbeat", False, principal.device_id, correlation_id,
                        details="credential/path mismatch")
            raise errors.Forbidden("Credential does not belong to this device", code="device_mismatch")
        if not principal.is_server_local:
            allowed, retry = self._heartbeat_limiter.allow(principal.device_id)
            if not allowed:
                raise errors.RateLimited("Heartbeat rate limit exceeded", retry)
        device = store.get_device(principal.device_id)
        if not device or device["status"] in ("revoked", "retired"):
            raise errors.Unauthorized("Device revoked", code="device_revoked")
        statuses = {}
        for name, state in (capability_status or {}).items():
            if not _CAPABILITY_RE.match(name) or state not in CAPABILITY_STATES:
                raise errors.ValidationFailed("Invalid capability_status", code="invalid_capability")
            statuses[name] = state
        fields: Dict[str, Any] = {"last_seen_at": store.utc_now()}
        if client_version is not None:
            fields["client_version"] = self._clean_text(client_version, "client_version", 50)
        if os_version is not None:
            fields["os_version"] = self._clean_text(os_version, "os_version", 100)
        if capabilities is not None:
            fields["capabilities"] = self._clean_capabilities(capabilities)
        if capability_status is not None:
            fields["capability_status"] = statuses
        if queue_backlog is not None:
            fields["queue_backlog"] = max(0, int(queue_backlog))
        activated = False
        if device["status"] == "pending":
            fields["status"] = "active"
            activated = True
        with database.transaction() as conn:
            store.update_device_fields(conn, principal.device_id, **fields)
        if activated:
            self._audit(principal, "device.activate", True, principal.device_id, correlation_id)
        return {
            "device_id": principal.device_id,
            "status": "active" if activated else device["status"],
            "server_time": store.utc_now(),
        }

    # ------------------------------------------------------------------ #
    # events (read side)
    # ------------------------------------------------------------------ #
    def list_events(self, actor: UserPrincipal, device_id: str, limit: int = 50,
                    cursor: Optional[str] = None, event_type: Optional[str] = None,
                    include_payload: bool = False, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        device, role = self.authorize(actor, device_id, allow_admin=True)
        payload_ok = include_payload and role in ("owner", "operator")
        if include_payload and not payload_ok:
            self._audit(actor, "device.events.read_payload", False, device_id, correlation_id)
            raise errors.Forbidden("Raw event payload access requires owner/operator access",
                                   code="payload_access_denied")
        if payload_ok:
            self._audit(actor, "device.events.read_payload", True, device_id, correlation_id)
        limit = min(max(limit, 1), 200)
        rows = store.list_events(device_id, limit + 1, self._cursor(cursor) or None,
                                 event_type, include_payload=payload_ok)
        page = rows[:limit]
        next_cursor = str(page[-1]["_cursor"]) if len(rows) > limit and page else None
        for row in page:
            row.pop("_cursor", None)
        return {"events": page, "next_cursor": next_cursor}

    def latest_state(self, actor: UserPrincipal, device_id: str) -> Dict[str, Any]:
        self.authorize(actor, device_id, roles=("owner", "operator"))
        return {"device_id": device_id, "state": store.get_latest_state(device_id)}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _cursor(cursor: Optional[str]) -> int:
        if not cursor:
            return 0
        try:
            value = int(cursor)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            raise errors.BadRequest("Invalid cursor", code="invalid_cursor")
