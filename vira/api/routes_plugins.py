"""Plugin management API (administrator) and SDK discovery metadata."""
from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.plugins import store
from vira.plugins.api import DEFAULT_ALLOWED
from vira.plugins.manifest import PLUGIN_API_VERSION


class PluginConfigRequest(BaseModel):
    config: dict = {}


def build_plugin_router(kernel, admin_dep, user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/plugins")

    def manager():
        value = getattr(kernel, "plugin_manager", None)
        if value is None:
            raise errors.ServiceUnavailable("plugin manager unavailable", code="plugins_unavailable")
        return value

    @router.get("/sdk")
    async def plugin_sdk(user: UserPrincipal = Depends(user_dep)):
        return {
            "api_version": PLUGIN_API_VERSION,
            "permissions": sorted(DEFAULT_ALLOWED | {"tools.register.write"}),
            "lifecycle": ["setup", "start", "stop"],
            "manifest_files": ["vira-plugin.json", "plugin.json", "vira-plugin.toml"],
            "entrypoint": "plugin.py:PluginClass",
        }

    @router.get("/ui")
    async def plugin_ui(user: UserPrincipal = Depends(user_dep)):
        """UI contributions declared by loaded plugins (for admin/client shells)."""
        items = []
        for plugin in manager().list_plugins():
            ui = plugin.get("ui") or {}
            if ui and plugin.get("status") == "active":
                items.append({
                    "plugin": plugin["id"],
                    "name": plugin["name"],
                    "version": plugin["version"],
                    "mount": f"/api/v1/ext/{plugin['id']}",
                    **ui,
                })
        return {"contributions": items}

    @router.get("")
    async def list_plugins(actor: UserPrincipal = Depends(admin_dep)):
        return manager().status()

    @router.post("/discover")
    async def discover_plugins(actor: UserPrincipal = Depends(admin_dep)):
        discovered = manager().discover()
        return {"discovered": sorted(discovered), "plugins": manager().status()}

    @router.get("/{plugin_id}")
    async def get_plugin(plugin_id: str, actor: UserPrincipal = Depends(admin_dep)):
        for item in manager().list_plugins():
            if item["id"] == plugin_id:
                return item
        raise errors.NotFound("Plugin not found")

    @router.post("/{plugin_id}/enable")
    async def enable_plugin(plugin_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not await manager().set_enabled(plugin_id, True):
            raise errors.NotFound("Plugin not found")
        return {"plugin": _find(manager(), plugin_id)}

    @router.post("/{plugin_id}/disable")
    async def disable_plugin(plugin_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not await manager().set_enabled(plugin_id, False):
            raise errors.NotFound("Plugin not found")
        return {"plugin": _find(manager(), plugin_id)}

    @router.post("/{plugin_id}/reload")
    async def reload_plugin(plugin_id: str, actor: UserPrincipal = Depends(admin_dep)):
        try:
            await manager().reload_plugin(plugin_id)
        except ValueError:
            raise errors.NotFound("Plugin not found")
        except Exception as exc:
            raise errors.ValidationFailed(f"Plugin reload failed: {exc}")
        return {"plugin": _find(manager(), plugin_id)}

    @router.delete("/{plugin_id}", status_code=204)
    async def forget_plugin(plugin_id: str, actor: UserPrincipal = Depends(admin_dep)):
        # Unregister and forget the installed record; files stay on disk so an
        # operator can reinstall or remove them deliberately.
        await manager().unload_plugin(plugin_id)
        if not store.delete(plugin_id):
            raise errors.NotFound("Plugin not found")
        return Response(status_code=204)

    return router


def _find(manager, plugin_id: str):
    for item in manager.list_plugins():
        if item["id"] == plugin_id:
            return item
    return None
