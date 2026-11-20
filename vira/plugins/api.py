"""Stable plugin SDK: the API third-party extensions build against.

Plugins never import kernel internals.  They receive a :class:`PluginContext`
and call its registration methods.  The manifest declares the permissions the
plugin needs; the manager enforces them before registration.

Minimal plugin::

    from vira.plugins.api import Plugin

    class MyPlugin(Plugin):
        async def setup(self, ctx):
            ctx.register_tool(MyTool())

        async def start(self):
            ...

        async def stop(self):
            ...
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from .manifest import PluginManifest

# Permission vocabulary.  Keep these coarse and stable.
PERM_TOOLS = "tools.register"
PERM_TOOLS_WRITE = "tools.register.write"
PERM_SENSORS = "sensors.register"
PERM_AGENTS = "agents.register"
PERM_EVENTS_READ = "events.read"
PERM_EVENTS_PUBLISH = "events.publish"
PERM_ROUTES = "http.routes"
PERM_STORAGE = "storage"
PERM_JOBS = "jobs.schedule"
PERM_CONFIG = "config.read"

DEFAULT_ALLOWED = {
    PERM_TOOLS, PERM_SENSORS, PERM_AGENTS, PERM_EVENTS_READ,
    PERM_EVENTS_PUBLISH, PERM_ROUTES, PERM_STORAGE, PERM_JOBS, PERM_CONFIG,
}


class PermissionDenied(RuntimeError):
    pass


class Plugin:
    """Base class for VIRA plugins.  Subclasses override the lifecycle hooks."""

    manifest: Optional[PluginManifest] = None

    async def setup(self, ctx: "PluginContext") -> None:
        """Register tools, routes, sensors, agents or event handlers."""

    async def start(self) -> None:
        """Start background work after setup."""

    async def stop(self) -> None:
        """Release resources.  The manager also cancels scheduled jobs."""


class PluginContext:
    """Registration surface handed to a plugin for one loaded instance."""

    def __init__(self, manager, plugin: Plugin, manifest: PluginManifest):
        self._manager = manager
        self._plugin = plugin
        self.manifest = manifest
        self.id = manifest.id
        self.config: Dict[str, Any] = dict(manifest.config)
        self.logger = logger.bind(plugin=manifest.id)
        self._subscriptions: List[tuple] = []

    # -- permissions ------------------------------------------------------
    def has(self, permission: str) -> bool:
        return permission in self.manifest.permissions

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise PermissionDenied(
                f"plugin {self.id!r} did not declare permission {permission!r}"
            )

    # -- registrations ----------------------------------------------------
    def register_tool(self, tool, qualified_name: Optional[str] = None) -> str:
        actions = list(getattr(getattr(tool, "permissions", None), "actions", []) or [])
        self.require(PERM_TOOLS)
        if any(action in ("write", "execute", "admin") for action in actions):
            self.require(PERM_TOOLS_WRITE)
        try:
            setattr(tool, "plugin_id", self.id)
        except Exception:
            pass
        registry = self._manager.tool_registry()
        if registry is None:
            raise RuntimeError("agent orchestrator/tool registry is not available")
        registry.register(tool, qualified_name=qualified_name)
        return qualified_name or tool.name

    def register_sensor(self, name: str, factory: Callable, config: Optional[Dict[str, Any]] = None) -> None:
        self.require(PERM_SENSORS)
        self._manager.register_sensor(self.id, name, factory, config or {})

    async def register_agent(self, agent) -> str:
        self.require(PERM_AGENTS)
        return await self._manager.register_agent(self.id, agent)

    def register_agent_definition(self, definition) -> None:
        self.require(PERM_AGENTS)
        from vira.agent.definitions import register_definition
        definition.source = f"plugin:{self.id}"
        register_definition(definition, owner=self.id)

    def register_router(self, router) -> None:
        self.require(PERM_ROUTES)
        self._manager.register_router(self.id, router)

    def on_event(self, event_type: str, handler: Callable[[Any], Awaitable[None]]) -> None:
        self.require(PERM_EVENTS_READ)
        bus = self._manager.event_bus()
        if bus is None:
            raise RuntimeError("event bus is not available")
        bus.subscribe(event_type, handler)
        self._subscriptions.append((event_type, handler))

    async def emit(self, event_type: str, data: Any = None) -> None:
        self.require(PERM_EVENTS_PUBLISH)
        await self._manager.emit(self.id, event_type, data)

    def schedule(self, handler: Callable[[], Awaitable[Any]], interval_seconds: float,
                 run_immediately: bool = False) -> asyncio.Task:
        self.require(PERM_JOBS)
        return self._manager.schedule(self.id, handler, interval_seconds, run_immediately)

    # -- namespaced storage ----------------------------------------------
    def get_state(self, key: str, default: Any = None) -> Any:
        self.require(PERM_STORAGE)
        return self._manager.storage_get(self.id, key, default)

    def set_state(self, key: str, value: Any) -> None:
        self.require(PERM_STORAGE)
        self._manager.storage_set(self.id, key, value)

    def delete_state(self, key: str) -> None:
        self.require(PERM_STORAGE)
        self._manager.storage_delete(self.id, key)

    @property
    def data_dir(self) -> Path:
        self.require(PERM_STORAGE)
        path = self._manager.data_dir(self.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup(self) -> None:
        bus = self._manager.event_bus()
        if bus is not None:
            for event_type, handler in self._subscriptions:
                try:
                    bus.unsubscribe(event_type, handler)
                except Exception:
                    pass
        self._subscriptions.clear()
