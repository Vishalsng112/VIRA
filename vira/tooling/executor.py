import time
from typing import List, Optional

from loguru import logger
from mcp.types import CallToolResult, TextContent

from vira.auth import database
from vira.tooling.contract import BaseTool, ToolContext, text_result
from vira.tooling.registry import ToolRegistry
from vira.tooling import context as tool_context
from vira import security


class ToolExecutor:
    """Resolve, authorize, execute, and durably record tool calls."""

    def __init__(self, registry: ToolRegistry, security_manager,
                 approval_config: Optional[dict] = None):
        self._registry = registry
        self._security = security_manager
        self._approval_config = approval_config or {}

    @staticmethod
    def _serialize(result):
        return result.model_dump() if hasattr(result, "model_dump") else str(result)

    def _record(
        self,
        tool_name: str,
        request: dict,
        result,
        status: str,
        allowed: bool,
        action: str,
        started: float,
        error: Optional[str] = None,
        correlation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        database.record_tool_call(
            tool_name,
            request,
            self._serialize(result) if result is not None else None,
            status,
            allowed,
            action,
            time.perf_counter() - started,
            error=error,
            correlation_id=correlation_id,
            agent_id=agent_id,
        )

    async def execute(
        self,
        tool_name: str,
        required_action: Optional[str] = None,
        agent_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        caller_user_id: Optional[int] = None,
        organization_id: Optional[str] = None,
        **kwargs,
    ) -> CallToolResult:
        started = time.perf_counter()
        if caller_user_id is None:
            caller_user_id = tool_context.caller_user_id.get()
        if organization_id is None:
            organization_id = tool_context.organization_id.get()
        permission_allowed = False
        logger.debug("Executing tool {}", tool_name)
        tool = self._registry.get(tool_name)

        if tool is None:
            candidates = [
                (key, candidate)
                for key, candidate in self._registry._tools.items()
                if candidate.name == tool_name
            ]
            if len(candidates) == 1:
                tool = candidates[0][1]
            elif len(candidates) > 1:
                result = text_result(
                    f"Ambiguous tool name '{tool_name}': "
                    f"{[candidate[0] for candidate in candidates]}",
                    is_error=True,
                )
                self._record(tool_name, kwargs, result, "ambiguous", False, required_action,
                             started, correlation_id=correlation_id, agent_id=agent_id)
                return result

        if tool is None:
            result = text_result(
                f"Tool '{tool_name}' not found. Available tools: {self.list_tools()}",
                is_error=True,
            )
            self._record(tool_name, kwargs, result, "not_found", False, required_action,
                         started, correlation_id=correlation_id, agent_id=agent_id)
            return result

        if required_action is None:
            actions = list(getattr(tool.permissions, "actions", []) or [])
            required_action = next(
                (action for action in ("execute", "write", "read")
                 if action in actions),
                actions[0] if actions else "execute",
            )
        if required_action not in tool.permissions.actions:
            result = text_result(
                f"Permission denied: '{tool_name}' does not allow '{required_action}'",
                is_error=True,
            )
            self._record(tool_name, kwargs, result, "denied", False, required_action,
                         started, correlation_id=correlation_id, agent_id=agent_id)
            return result

        # MCP tools are additionally governed by server allow-list policies.
        server_name = getattr(tool, "server_name", None)
        if server_name:
            from vira.mcp import policy as mcp_policy
            from vira.mcp import store as mcp_store
            record = mcp_store.get_server_by_name(server_name)
            if record is not None:
                roles = ()
                if caller_user_id is not None:
                    user = database.get_user_by_id(int(caller_user_id))
                    roles = (user.get("role"),) if user and user.get("role") else ()
                if not mcp_policy.is_allowed(
                    record, tool.name, user_id=caller_user_id, roles=roles,
                    organization_id=organization_id,
                ):
                    result = text_result(
                        f"Permission denied: MCP tool '{server_name}.{tool.name}' is not allowed "
                        "for this caller.",
                        is_error=True,
                    )
                    self._record(tool_name, kwargs, result, "denied", False, required_action,
                                 started, correlation_id=correlation_id, agent_id=agent_id)
                    return result

        if self._security and not self._security.authorize(f"tool.execute.{tool_name}"):
            result = text_result(
                f"Permission denied by security manager for '{tool_name}'",
                is_error=True,
            )
            self._record(tool_name, kwargs, result, "denied", False, required_action,
                         started, correlation_id=correlation_id, agent_id=agent_id)
            return result
        permission_allowed = True

        # Destructive local actions require a human approval. Approved requests
        # are single-use and matched on the exact tool/action/arguments tuple.
        reason = security.approval_reason(
            tool_name, required_action, kwargs, self._approval_config)
        if reason:
            approved = security.find_approved(
                caller_user_id, tool_name, required_action,
                {k: v for k, v in kwargs.items() if k != "user_id"},
            )
            if not approved:
                request = security.request_approval(
                    tool_name, required_action,
                    {k: v for k, v in kwargs.items() if k != "user_id"},
                    user_id=caller_user_id,
                    agent_id=agent_id,
                    run_id=tool_context.run_id.get(),
                    reason=reason,
                    ttl_minutes=self._approval_config.get("ttl_minutes"),
                )
                result = text_result(
                    f"APPROVAL_REQUIRED: '{tool_name}' needs explicit approval "
                    f"({reason}). Ask the user to approve it in VIRA, then call "
                    f"the same tool again. approval_id={request.get('id')}",
                    is_error=True,
                )
                self._record(tool_name, kwargs, result, "approval_required", False,
                             required_action, started, correlation_id=correlation_id,
                             agent_id=agent_id)
                logger.info("Approval required for {} ({}): {}",
                            tool_name, caller_user_id, request.get("id"))
                return result

        try:
            # Tools that work on agent-scoped resources need the caller identity.
            tool_kwargs = dict(kwargs)
            if agent_id is not None and (
                    tool_name == "workspace.sandbox"
                    or getattr(tool, "wants_agent_id", False)):
                tool_kwargs["agent_id"] = agent_id
            if isinstance(tool, BaseTool):
                context = ToolContext(
                    user_id=caller_user_id,
                    agent_id=agent_id,
                    organization_id=organization_id,
                    run_id=tool_context.run_id.get(),
                    workspace_root=tool_context.workspace.get(),
                )
                envelope = await tool.invoke(tool_kwargs, context)
                result = CallToolResult(
                    content=[TextContent(type="text", text=envelope.model_dump_json())],
                    structuredContent=envelope.model_dump(mode="json"),
                    isError=not envelope.ok,
                )
            else:
                result = await tool.execute(**tool_kwargs)
            status = "failed" if getattr(result, "isError", False) else "succeeded"
            self._record(tool_name, kwargs, result, status, permission_allowed, required_action,
                         started, correlation_id=correlation_id, agent_id=agent_id)
            return result
        except Exception as exc:
            self._record(tool_name, kwargs, None, "failed", permission_allowed, required_action,
                         started, error=str(exc), correlation_id=correlation_id, agent_id=agent_id)
            raise

    def list_tools(self) -> List[str]:
        return self._registry.list()
