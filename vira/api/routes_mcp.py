"""MCP marketplace, installed servers, per-user allow-list policies and tools."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from vira import errors
from vira.auth.principals import UserPrincipal
from vira.mcp import catalog, store


class McpInstallRequest(BaseModel):
    marketplace_id: Optional[str] = None
    name: Optional[str] = None
    description: str = ""
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = []
    url: Optional[str] = None
    env: Dict[str, str] = {}
    permissions: List[str] = ["read", "execute"]
    allowed_tools: List[str] = []
    denied_tools: List[str] = []
    categories: List[str] = []
    version: str = "1.0.0"
    enabled: Optional[bool] = None


class McpUpdateRequest(BaseModel):
    description: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    permissions: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    denied_tools: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    enabled: Optional[bool] = None


class McpPolicyRequest(BaseModel):
    subject_type: str = Field(pattern="^(default|user|role|org)$")
    subject_id: str
    allowed: bool = True
    allowed_tools: List[str] = []
    denied_tools: List[str] = []


def build_mcp_router(kernel, admin_dep, user_dep) -> APIRouter:
    router = APIRouter(prefix="/api/v1/mcp")

    def orchestrator():
        value = getattr(kernel, "agent_orchestrator", None)
        if value is None:
            modules = getattr(kernel, "module_manager", None)
            value = modules.get_module("AgentOrchestratorModule") if modules else None
        if value is None:
            raise errors.ServiceUnavailable("agent orchestrator unavailable")
        return value

    @router.get("/marketplace")
    async def marketplace(q: str = "", category: str = "",
                          user: UserPrincipal = Depends(user_dep)):
        return {"entries": catalog.search(q, category)}

    @router.get("/servers")
    async def list_servers(actor: UserPrincipal = Depends(admin_dep)):
        return {"servers": store.list_servers()}

    @router.post("/servers", status_code=201)
    async def install_server(body: McpInstallRequest,
                             actor: UserPrincipal = Depends(admin_dep)):
        if body.marketplace_id:
            entry = catalog.get(body.marketplace_id)
            if entry is None:
                raise errors.NotFound("Marketplace entry not found")
            payload = {
                "name": entry["name"],
                "description": entry["description"],
                "transport": entry["transport"],
                "command": entry["command"],
                "args": entry["args"],
                "url": entry.get("url"),
                "permissions": entry["permissions"],
                "categories": entry["categories"],
                "version": entry["version"],
                "source": f"marketplace:{entry['id']}",
                "enabled": body.enabled if body.enabled is not None else False,
            }
        else:
            if not body.name:
                raise errors.ValidationFailed("name or marketplace_id is required")
            payload = {
                "name": body.name,
                "description": body.description,
                "transport": body.transport,
                "command": body.command,
                "args": body.args,
                "url": body.url,
                "env": body.env,
                "permissions": body.permissions,
                "allowed_tools": body.allowed_tools,
                "denied_tools": body.denied_tools,
                "categories": body.categories,
                "version": body.version,
                "source": "manual",
                "enabled": body.enabled if body.enabled is not None else True,
            }
        record = store.upsert_server(payload, actor.user_id)
        if record["enabled"]:
            try:
                await orchestrator().connect_mcp_server(record["id"])
            except Exception as exc:
                raise errors.ValidationFailed(f"MCP server saved but connection failed: {exc}")
        return {"server": record}

    @router.patch("/servers/{server_id}")
    async def update_server(server_id: str, body: McpUpdateRequest,
                            actor: UserPrincipal = Depends(admin_dep)):
        existing = store.get_server(server_id)
        if existing is None:
            raise errors.NotFound("MCP server not found")
        merged = {**existing}
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                merged[key] = value
        record = store.upsert_server(merged, existing.get("created_by_user_id"))
        return {"server": record}

    @router.post("/servers/{server_id}/connect")
    async def connect_server(server_id: str, actor: UserPrincipal = Depends(admin_dep)):
        record = store.get_server(server_id)
        if record is None:
            raise errors.NotFound("MCP server not found")
        try:
            registered = await orchestrator().connect_mcp_server(server_id)
        except Exception as exc:
            raise errors.ValidationFailed(f"MCP connection failed: {exc}")
        return {"server": record, "tools": registered}

    @router.post("/servers/{server_id}/disconnect")
    async def disconnect_server(server_id: str, actor: UserPrincipal = Depends(admin_dep)):
        try:
            disconnected = await orchestrator().disconnect_mcp_server(server_id)
        except ValueError:
            raise errors.NotFound("MCP server not found")
        return {"disconnected": disconnected}

    @router.post("/servers/{server_id}/enable")
    async def enable_server(server_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not store.set_enabled(server_id, True):
            raise errors.NotFound("MCP server not found")
        try:
            await orchestrator().connect_mcp_server(server_id)
        except Exception as exc:
            raise errors.ValidationFailed(f"Enabled but connection failed: {exc}")
        return {"server": store.get_server(server_id)}

    @router.post("/servers/{server_id}/disable")
    async def disable_server(server_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not store.set_enabled(server_id, False):
            raise errors.NotFound("MCP server not found")
        try:
            await orchestrator().disconnect_mcp_server(server_id)
        except Exception:
            pass
        return {"server": store.get_server(server_id)}

    @router.delete("/servers/{server_id}", status_code=204)
    async def delete_server(server_id: str, actor: UserPrincipal = Depends(admin_dep)):
        try:
            await orchestrator().disconnect_mcp_server(server_id)
        except Exception:
            pass
        if not store.delete_server(server_id):
            raise errors.NotFound("MCP server not found")
        return Response(status_code=204)

    @router.get("/servers/{server_id}/policies")
    async def list_policies(server_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if store.get_server(server_id) is None:
            raise errors.NotFound("MCP server not found")
        return {"policies": store.list_policies(server_id)}

    @router.post("/servers/{server_id}/policies", status_code=201)
    async def set_policy(server_id: str, body: McpPolicyRequest,
                         actor: UserPrincipal = Depends(admin_dep)):
        if store.get_server(server_id) is None:
            raise errors.NotFound("MCP server not found")
        return {"policy": store.set_policy(
            server_id, body.subject_type, body.subject_id, body.allowed,
            body.allowed_tools, body.denied_tools,
        )}

    @router.delete("/policies/{policy_id}", status_code=204)
    async def delete_policy(policy_id: str, actor: UserPrincipal = Depends(admin_dep)):
        if not store.delete_policy(policy_id):
            raise errors.NotFound("Policy not found")
        return Response(status_code=204)

    @router.get("/tools")
    async def list_mcp_tools(actor: UserPrincipal = Depends(admin_dep)):
        registry = getattr(orchestrator(), "tool_registry", None)
        metadata = registry.metadata() if registry else []
        return {"tools": [item for item in metadata if item.get("provider") != "local"]}

    return router
