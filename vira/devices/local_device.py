"""The VIRA server as an endpoint device (design section 1, 4.2).

The server installation owns one ``is_server_local`` device.  Its in-process
sensors emit events through :class:`LocalDeviceDispatcher`, which feeds the same
:class:`EventIngestionService` that remote endpoints use, so every stored event
has device provenance and the same allow-list, dedupe and retention rules.
"""
import asyncio
import json
import platform as _platform
from typing import Any, Dict, List, Optional

from loguru import logger

from vira import __version__
from vira.auth import database
from vira.auth.principals import DevicePrincipal, local_device_principal
from . import store
from .ingestion import EventIngestionService

_PLATFORM_MAP = {"linux": "linux", "darwin": "macos", "windows": "windows"}


def detect_platform() -> str:
    return _PLATFORM_MAP.get(_platform.system().lower(), "other")


class LocalDeviceManager:
    """Creates/maintains the server's own device record and its health."""

    def __init__(self, display_name: Optional[str] = None, share_with_all_users: bool = False):
        self._display_name = display_name or f"VIRA Server ({_platform.node() or 'localhost'})"
        self._share_with_all_users = share_with_all_users
        self.device_id: Optional[str] = None
        self._capabilities: List[str] = []

    def ensure(self) -> str:
        """Idempotently create the local device; return its id."""
        with database.transaction() as conn:
            device = store.get_server_local_device(conn)
            if device is None:
                device_id = store.insert_device(
                    conn, self._display_name, detect_platform(), "server",
                    _platform.release(), __version__, [], status="active",
                    created_by_user_id=None, is_server_local=True,
                )
            else:
                device_id = device["id"]
                if device["status"] != "active":
                    store.update_device_fields(conn, device_id, status="active", revoked_at=None)
        self.device_id = device_id
        self.sync_access()
        return device_id

    def sync_access(self) -> None:
        """Give the installation's administrators ownership of the server device.

        Device visibility is explicit (design 9.3): the server device is owned
        by every active administrator, and optionally shared as ``viewer`` with
        all other active users when ``devices.local.share_with_all_users``.
        """
        if not self.device_id:
            return
        with database.transaction() as conn:
            admins = conn.execute(
                "SELECT id FROM users WHERE role = 'admin' AND status = 'active'").fetchall()
            for row in admins:
                if store.get_access(int(row["id"]), self.device_id, conn) is None:
                    store.grant_access(conn, int(row["id"]), self.device_id, "owner", None)
            if self._share_with_all_users:
                others = conn.execute(
                    "SELECT id FROM users WHERE role != 'admin' AND status = 'active'").fetchall()
                for row in others:
                    if store.get_access(int(row["id"]), self.device_id, conn) is None:
                        store.grant_access(conn, int(row["id"]), self.device_id, "viewer", None)

    def principal(self) -> DevicePrincipal:
        if not self.device_id:
            raise RuntimeError("Local device not initialised")
        return local_device_principal(self.device_id)

    def heartbeat(self, capabilities: List[str]) -> None:
        if not self.device_id:
            return
        self._capabilities = capabilities
        with database.transaction() as conn:
            store.update_device_fields(
                conn, self.device_id, last_seen_at=store.utc_now(),
                capabilities=capabilities, client_version=__version__,
                os_version=_platform.release(),
            )


class LocalDeviceDispatcher:
    """Drop-in replacement for the dispatcher handed to server-side sensors.

    Sensors keep calling ``await dispatcher.publish(Event(...))``; the event is
    re-expressed as a device event of the server-local device and sent through
    the ingestion service.  Returns the number of events accepted (0 or 1).
    """

    def __init__(self, manager: LocalDeviceManager, ingestion: EventIngestionService):
        self._manager = manager
        self._ingestion = ingestion
        self._rejected: Dict[str, int] = {}

    async def publish(self, event) -> int:
        device_id = self._manager.device_id
        if not device_id:
            return 0
        try:
            result = await self._ingestion.ingest_local(
                device_id, event.type, event.data, event.source,
                correlation_id=event.correlation_id, causation_id=event.causation_id,
            )
        except Exception as exc:
            logger.error("Local device ingestion failed for {}: {}", event.type, exc)
            return 0
        if result["rejected"]:
            first = result["results"][0]
            count = self._rejected.get(event.type, 0) + 1
            self._rejected[event.type] = count
            if count == 1:  # log once per type to avoid flooding
                logger.warning(
                    "Server device event {} rejected by policy: {} ({})",
                    event.type, first.get("code"), first.get("message"))
            return 0
        return result["accepted"]

    # Sensors that fall back to an event bus only need ``publish``.
