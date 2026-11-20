"""Plugin discovery, permission checks, lifecycle and SDK wiring.

The manager is intentionally independent of the API layer.  It discovers
manifest plugins (``vira-plugin.json``) and legacy single-file plugins, checks
declared permissions and dependencies, and hands each plugin a stable
:class:`~vira.plugins.api.PluginContext` for registration.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import re
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from vira.plugins import store
from vira.plugins.api import (
    DEFAULT_ALLOWED,
    Plugin,
    PluginContext,
    PermissionDenied,
)
from vira.plugins.manifest import ManifestError, PluginManifest


class ViraPlugin(Plugin):
    """Backwards-compatible legacy base class (``name`` in the constructor)."""

    def __init__(self, name: Optional[str] = None):
        self.name = name or self.__class__.__name__


def _parse_version(value: str) -> Tuple[int, int, int]:
    core = str(value or "0").split("+", 1)[0].split("-", 1)[0]
    parts = []
    for piece in core.split(".")[:3]:
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def _satisfies(version: str, constraint: str) -> bool:
    """Small semver subset: >=, <=, >, <, ==, ^ and ~."""
    constraint = (constraint or "").strip()
    if not constraint or constraint == "*":
        return True
    current = _parse_version(version)
    for part in constraint.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("^"):
            floor = _parse_version(part[1:])
            if current < floor or current[0] != floor[0]:
                return False
        elif part.startswith("~"):
            floor = _parse_version(part[1:])
            if current < floor or current[:2] != floor[:2]:
                return False
        else:
            for operator in (">=", "<=", "==", ">", "<"):
                if part.startswith(operator):
                    target = _parse_version(part[len(operator):])
                    if operator == ">=" and current < target:
                        return False
                    if operator == "<=" and current > target:
                        return False
                    if operator == "==" and current != target:
                        return False
                    if operator == ">" and current <= target:
                        return False
                    if operator == "<" and current >= target:
                        return False
                    break
            else:
                if current != _parse_version(part):
                    return False
    return True


class PluginManager:
    def __init__(self, plugins_dir: str, kernel=None, config=None):
        self.plugins_dir = Path(plugins_dir)
        self.kernel = kernel
        self._config = config
        self._manifests: Dict[str, PluginManifest] = {}
        self._instances: Dict[str, Plugin] = {}
        self._contexts: Dict[str, PluginContext] = {}
        self._routers: List[Tuple[str, Any]] = []
        self._sensor_configs: List[Dict[str, Any]] = []
        self._tasks: Dict[str, List[asyncio.Task]] = {}
        self._agents: Dict[str, List[str]] = {}
        self._errors: Dict[str, str] = {}

    # -- config helpers ---------------------------------------------------
    def _cfg(self, key: str, default: Any = None) -> Any:
        if self._config is None:
            return default
        try:
            if hasattr(self._config, "get"):
                return self._config.get(key, default)
        except Exception:
            pass
        return default

    def _allowed_permissions(self) -> set:
        configured = self._cfg("plugins.allowed_permissions")
        allowed = set(configured) if isinstance(configured, list) else set(DEFAULT_ALLOWED)
        if "tools.register.write" not in allowed and self._cfg("plugins.allow_write_tools", True):
            allowed.add("tools.register.write")
        denied = self._cfg("plugins.denied_permissions") or []
        if isinstance(denied, list):
            allowed -= set(denied)
        return allowed

    # -- discovery --------------------------------------------------------
    def discover(self) -> Dict[str, PluginManifest]:
        roots = [self.plugins_dir]
        extra = self._cfg("plugins.directories") or []
        if isinstance(extra, str):
            extra = [extra]
        roots.extend(Path(item).expanduser() for item in extra or [])
        env = os.environ.get("VIRA_PLUGIN_PATH", "")
        roots.extend(Path(item).expanduser() for item in env.split(":") if item)

        found: Dict[str, PluginManifest] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if entry.name.startswith((".", "_")):
                    continue
                try:
                    if entry.is_dir():
                        if any((entry / name).is_file() for name in
                               ("vira-plugin.json", "plugin.json", "vira-plugin.toml")):
                            manifest = PluginManifest.from_directory(entry)
                            found[manifest.id] = manifest
                    elif entry.suffix == ".py" and entry.name not in ("__init__.py", "base_plugin.py", "api.py", "manifest.py", "store.py"):
                        try:
                            source = entry.read_text(encoding="utf-8", errors="ignore")
                        except OSError:
                            continue
                        if not re.search(r"class\s+\w+\s*\([^)]*\b(?:ViraPlugin|Plugin)\b\s*[,)]", source):
                            continue
                        manifest = PluginManifest.legacy_python(entry)
                        found.setdefault(manifest.id, manifest)
                except Exception as exc:
                    logger.error("Invalid plugin at {}: {}", entry, exc)
                    self._errors[entry.name] = str(exc)
        # Entry-point plugins (pip packages exposing "vira.plugins").
        try:
            from importlib.metadata import entry_points
            eps = entry_points()
            selected = eps.select(group="vira.plugins") if hasattr(eps, "select") else []
            for ep in selected:
                try:
                    manifest = PluginManifest.from_dict({
                        "id": ep.name,
                        "name": ep.name.replace("-", " ").title(),
                        "version": "0.0.0",
                        "api_version": "1",
                        "entrypoint": f"entrypoint:{ep.value}",
                        "permissions": [],
                    })
                    manifest.entrypoint = f"entrypoint:{ep.name}"
                    found.setdefault(manifest.id, manifest)
                except Exception as exc:
                    logger.error("Invalid plugin entry point {}: {}", ep.name, exc)
        except Exception:
            pass
        self._manifests = found
        for manifest in found.values():
            store.upsert(manifest)
        return found

    # -- lifecycle --------------------------------------------------------
    async def load_plugins(self) -> None:
        discovered = self.discover()
        if not discovered:
            logger.info("No plugins discovered in {}", self.plugins_dir)
            return

        enabled: Dict[str, bool] = {}
        for plugin_id in discovered:
            row = store.get(plugin_id)
            enabled[plugin_id] = bool(row["enabled"]) if row else True

        loaded: set = set()
        loading: set = set()

        async def load_with_dependencies(plugin_id: str) -> None:
            if plugin_id in loaded or plugin_id in loading:
                return
            manifest = discovered.get(plugin_id)
            if manifest is None or not enabled.get(plugin_id, True):
                return
            loading.add(plugin_id)
            for dep_id, constraint in (manifest.requires or {}).items():
                if dep_id == "vira":
                    from vira import __version__
                    if not _satisfies(__version__, constraint):
                        raise ManifestError(
                            f"requires VIRA {constraint}, server is {__version__}")
                    continue
                if dep_id not in discovered:
                    raise ManifestError(f"missing plugin dependency {dep_id!r}")
                if not enabled.get(dep_id, True):
                    raise ManifestError(f"plugin dependency {dep_id!r} is disabled")
                dep = discovered[dep_id]
                if not _satisfies(dep.version, constraint):
                    raise ManifestError(
                        f"dependency {dep_id!r} {constraint} not satisfied by {dep.version}")
                await load_with_dependencies(dep_id)
                if dep_id not in self._instances:
                    raise ManifestError(f"plugin dependency {dep_id!r} failed to load")
            loading.discard(plugin_id)
            await self._load(manifest)
            loaded.add(plugin_id)

        for plugin_id in discovered:
            try:
                await load_with_dependencies(plugin_id)
            except Exception as exc:
                logger.error("Plugin {} failed dependency check: {}", plugin_id, exc)
                store.set_status(plugin_id, "error", str(exc))
                self._errors[plugin_id] = str(exc)
        logger.info("Loaded {} plugin(s)", len(self._instances))

    async def _load(self, manifest: PluginManifest) -> None:
        allowed = self._allowed_permissions()
        missing = sorted(set(manifest.permissions) - allowed)
        if missing and not manifest.legacy:
            message = f"permission(s) not allowed by server policy: {', '.join(missing)}"
            logger.error("Plugin {}: {}", manifest.id, message)
            store.set_status(manifest.id, "error", message)
            self._errors[manifest.id] = message
            raise PermissionDenied(message)

        store.set_status(manifest.id, "loading")
        try:
            plugin_class = self._import_entrypoint(manifest)
            try:
                instance = plugin_class()
            except TypeError:
                instance = plugin_class(manifest.name)
            instance.manifest = manifest
            if manifest.legacy and not manifest.permissions:
                manifest.permissions = sorted(allowed)
            context = PluginContext(self, instance, manifest)
            await instance.setup(context)
            await instance.start()
            self._instances[manifest.id] = instance
            self._contexts[manifest.id] = context
            self._errors.pop(manifest.id, None)
            store.set_status(manifest.id, "active")
            logger.info("Plugin active: {} v{} ({})", manifest.id, manifest.version, manifest.entrypoint)
        except Exception as exc:
            logger.error("Plugin {} failed to load: {}\n{}", manifest.id, exc, traceback.format_exc())
            store.set_status(manifest.id, "error", str(exc))
            self._errors[manifest.id] = str(exc)
            raise

    def _import_entrypoint(self, manifest: PluginManifest):
        if manifest.entrypoint.startswith("entrypoint:"):
            from importlib.metadata import entry_points
            value = manifest.entrypoint.split(":", 1)[1]
            group = "vira.plugins"
            for ep in entry_points().select(group=group):
                if ep.value == value or ep.name == value:
                    obj = ep.load()
                    return obj if isinstance(obj, type) else obj.__class__
            raise ImportError(f"plugin entry point {value!r} not found")

        target, sep, attr = manifest.entrypoint.partition(":")
        attr = attr or "auto"
        directory = Path(manifest.directory or self.plugins_dir)
        if target.endswith(".py"):
            path = (directory / target).resolve()
            if directory.resolve() not in path.parents and path != directory.resolve():
                raise ImportError("plugin entrypoint escapes its plugin directory")
            module_name = f"vira_plugin_{manifest.id.replace('.', '_')}_{uuid.uuid4().hex[:8]}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot import {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
            module = importlib.import_module(target)

        candidates = []
        if attr != "auto":
            obj = getattr(module, attr)
            candidates = [obj]
        else:
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, type) and issubclass(obj, Plugin) and obj is not Plugin:
                    if obj is not ViraPlugin or name != "ViraPlugin":
                        candidates.append(obj)
        for candidate in candidates:
            if isinstance(candidate, type) and issubclass(candidate, Plugin):
                return candidate
        raise ImportError(f"no Plugin subclass found in {manifest.entrypoint}")

    async def unload_plugin(self, plugin_id: str) -> bool:
        context = self._contexts.pop(plugin_id, None)
        instance = self._instances.pop(plugin_id, None)
        for task in self._tasks.pop(plugin_id, []):
            task.cancel()
        self._routers = [item for item in self._routers if item[0] != plugin_id]
        registry_component = self._orchestrator()
        agent_registry = getattr(registry_component, "registry", None) if registry_component else None
        if agent_registry is not None:
            for agent_id in self._agents.pop(plugin_id, []):
                try:
                    await agent_registry.unregister(agent_id)
                except Exception as exc:
                    logger.warning("Failed to unregister plugin agent {}: {}", agent_id, exc)
        if context:
            context.cleanup()
        try:
            from vira.agent.definitions import unregister_definitions
            unregister_definitions(plugin_id)
        except Exception:
            pass
        registry = self.tool_registry()
        if registry is not None and hasattr(registry, "remove_by_plugin"):
            registry.remove_by_plugin(plugin_id)
        if instance is not None:
            try:
                await instance.stop()
            except Exception as exc:
                logger.error("Plugin {} stop failed: {}", plugin_id, exc)
        if instance is not None or context is not None:
            store.set_status(plugin_id, "stopped")
            return True
        return False

    async def reload_plugin(self, plugin_id: str) -> bool:
        await self.unload_plugin(plugin_id)
        self.discover()
        manifest = self._manifests.get(plugin_id)
        if manifest is None:
            raise ValueError(f"plugin {plugin_id!r} not found")
        await self._load(manifest)
        return True

    async def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        if not store.set_enabled(plugin_id, enabled):
            return False
        if enabled:
            await self.reload_plugin(plugin_id)
        else:
            await self.unload_plugin(plugin_id)
            store.set_status(plugin_id, "disabled")
        return True

    async def stop_all(self) -> None:
        for plugin_id in list(self._instances):
            await self.unload_plugin(plugin_id)
        logger.info("All plugins stopped")

    # -- runtime helpers used by PluginContext ----------------------------
    def _orchestrator(self):
        if not self.kernel:
            return None
        orchestrator = getattr(self.kernel, "agent_orchestrator", None)
        if orchestrator is not None:
            return orchestrator
        modules = getattr(self.kernel, "module_manager", None)
        if modules is not None and hasattr(modules, "get_module"):
            return modules.get_module("AgentOrchestratorModule")
        return None

    def tool_registry(self):
        orchestrator = self._orchestrator()
        return getattr(orchestrator, "tool_registry", None) if orchestrator else None

    def event_bus(self):
        return getattr(self.kernel, "event_bus", None) if self.kernel else None

    @property
    def runtime(self):
        orchestrator = self._orchestrator()
        return getattr(orchestrator, "runtime", None) if orchestrator else None

    def register_sensor(self, plugin_id: str, name: str, factory: Callable,
                        config: Dict[str, Any]) -> None:
        qualified = f"plugin.{plugin_id}.{name}"
        if self.kernel and hasattr(self.kernel, "register_sensor"):
            self.kernel.register_sensor(qualified, factory)
        sensor_config = {"name": qualified, "factory_config": config}
        self._sensor_configs.append(sensor_config)

    async def register_agent(self, plugin_id: str, agent) -> str:
        orchestrator = self._orchestrator()
        registry = getattr(orchestrator, "registry", None) if orchestrator else None
        if registry is None:
            raise RuntimeError("agent registry is not available")
        if getattr(agent, "runtime", None) is None and self.runtime is not None:
            agent.runtime = self.runtime
        try:
            setattr(agent, "plugin_id", plugin_id)
        except Exception:
            pass
        if hasattr(agent, "initialize"):
            await agent.initialize()
        if hasattr(agent, "start"):
            await agent.start()
        await registry.register(agent)
        agent_id = getattr(agent, "agent_id", "")
        self._agents.setdefault(plugin_id, []).append(agent_id)
        return agent_id

    def register_router(self, plugin_id: str, router) -> None:
        self._routers.append((plugin_id, router))

    async def emit(self, plugin_id: str, event_type: str, data: Any = None) -> None:
        from vira.kernel.event_bus import Event
        bus = self.event_bus()
        if bus is None:
            return
        await bus.publish(Event(type=event_type, data=data or {}, source=f"plugin:{plugin_id}"))

    def schedule(self, plugin_id: str, handler: Callable, interval_seconds: float,
                 run_immediately: bool = False) -> asyncio.Task:
        interval = max(1.0, float(interval_seconds))

        async def loop() -> None:
            try:
                if run_immediately:
                    await handler()
                while True:
                    await asyncio.sleep(interval)
                    await handler()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Plugin {} scheduled job failed: {}", plugin_id, exc)

        task = asyncio.create_task(loop())
        self._tasks.setdefault(plugin_id, []).append(task)
        return task

    def storage_get(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return store.storage_get(plugin_id, key, default)

    def storage_set(self, plugin_id: str, key: str, value: Any) -> None:
        store.storage_set(plugin_id, key, value)

    def storage_delete(self, plugin_id: str, key: str) -> None:
        store.storage_delete(plugin_id, key)

    def data_dir(self, plugin_id: str) -> Path:
        root = Path(self._cfg("plugins.data_dir", "./data/plugins"))
        return root / plugin_id.replace("/", "_")

    # -- introspection ----------------------------------------------------
    def collect_routers(self) -> List[Tuple[str, Any]]:
        return list(self._routers)

    def pending_sensors(self) -> List[Dict[str, Any]]:
        return list(self._sensor_configs)

    def list_plugins(self) -> List[Dict[str, Any]]:
        items = []
        rows = {row["id"]: row for row in store.list_all()}
        for plugin_id, manifest in sorted(self._manifests.items()):
            row = rows.get(plugin_id, {})
            items.append({
                **manifest.as_dict(),
                "enabled": row.get("enabled", True),
                "status": row.get("status", "discovered"),
                "error": row.get("error") or self._errors.get(plugin_id),
                "loaded": plugin_id in self._instances,
            })
        return items

    def status(self) -> Dict[str, Any]:
        return {
            "loaded": len(self._instances),
            "discovered": len(self._manifests),
            "plugins": self.list_plugins(),
        }
