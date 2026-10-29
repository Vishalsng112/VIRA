"""Typed principals (VIRA multi-device design, section 7.1).

Every authenticated request resolves to exactly one of these.  Authorization
code must derive identity from the principal, never from request-body fields.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = (ROLE_ADMIN, ROLE_USER)


@dataclass(frozen=True)
class UserPrincipal:
    """A human user authenticated by a browser/API session."""

    user_id: int
    username: str
    roles: Tuple[str, ...]
    session_id: str
    public_id: str = ""

    kind: str = "user"

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @property
    def is_admin(self) -> bool:
        return ROLE_ADMIN in self.roles


@dataclass(frozen=True)
class DevicePrincipal:
    """A registered endpoint device authenticated by a device credential."""

    device_id: str
    credential_id: str
    scopes: Tuple[str, ...]
    device_status: str
    is_server_local: bool = False

    kind: str = "device"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


@dataclass(frozen=True)
class ServicePrincipal:
    """A trusted internal component (workers, the in-process outbox, ...)."""

    service_id: str
    permissions: Tuple[str, ...] = ()
    kind: str = "service"

    def can(self, permission: str) -> bool:
        return permission in self.permissions or "*" in self.permissions


def local_device_principal(device_id: str) -> DevicePrincipal:
    """Principal used by the server's own in-process sensors.

    The server-local device has no stored credential: the process boundary is
    the trust boundary.  Events still go through the same ingestion service,
    allow-list and persistence path as remote devices.
    """
    return DevicePrincipal(
        device_id=device_id,
        credential_id="local",
        scopes=("events:write", "heartbeat"),
        device_status="active",
        is_server_local=True,
    )
