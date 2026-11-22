"""Pydantic-first tool contract for VIRA's domain MCP servers.

Pydantic models are the source of truth.  JSON Schema exposed to LLMs and MCP
clients is generated from those models, so the schema, runtime validation and
typed output stay in sync.
"""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Generic, Optional, TypeVar

from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class StrictModel(BaseModel):
    """Base model for all tool inputs and outputs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def text_result(text: str, is_error: bool = False) -> CallToolResult:
    """Small helper for MCP-style callers and tests."""
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=is_error)


class ToolSideEffects(str, Enum):
    none = "none"
    read = "read"
    network = "network"
    write = "write"
    execute = "execute"


class ToolPermission(StrictModel):
    actions: list[str] = Field(default_factory=lambda: ["read"])


class ToolExample(StrictModel):
    description: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolFailure(StrictModel):
    code: str
    message: str
    retryable: bool = False
    next_steps: list[str] = Field(default_factory=list)
    details: dict[str, Any] | None = None


class ToolError(Exception):
    """Expected, user-facing tool failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        next_steps: Optional[list[str]] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.next_steps = list(next_steps or [])
        self.details = details

    def as_failure(self) -> ToolFailure:
        return ToolFailure(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            next_steps=self.next_steps,
            details=self.details,
        )


class ToolEnvelope(StrictModel, Generic[OutputT]):
    """Uniform result returned by every tool."""

    ok: bool
    data: Optional[OutputT] = None
    error: Optional[ToolFailure] = None
    truncated: bool = False
    next_cursor: Optional[str] = None


class ToolMetadata(StrictModel):
    qualified_name: str
    namespace: str
    name: str
    title: str
    description: str
    when_to_use: str
    when_not_to_use: str = ""
    category: str
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    version: str = "1.0.0"
    side_effects: ToolSideEffects = ToolSideEffects.none
    idempotent: bool = True
    timeout_seconds: int = 30
    permissions: ToolPermission = Field(default_factory=ToolPermission)
    examples: list[ToolExample] = Field(default_factory=list)


@dataclass(frozen=True)
class ToolContext:
    """Caller and run identity passed to a tool explicitly.

    Tools never read ambient globals.  The agent runtime, HTTP caller or MCP
    server adapter is responsible for constructing this context.
    """

    user_id: Optional[int] = None
    agent_id: Optional[str] = None
    organization_id: Optional[str] = None
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    request_id: Optional[str] = None
    workspace_root: Optional[str] = None

    @classmethod
    def from_env(cls) -> "ToolContext":
        def _int(value: Optional[str]) -> Optional[int]:
            try:
                return int(value) if value else None
            except (TypeError, ValueError):
                return None

        return cls(
            user_id=_int(os.getenv("VIRA_CALLER_USER_ID")),
            agent_id=os.getenv("VIRA_AGENT_ID") or None,
            organization_id=os.getenv("VIRA_ORGANIZATION_ID") or None,
            conversation_id=os.getenv("VIRA_CONVERSATION_ID") or None,
            run_id=os.getenv("VIRA_RUN_ID") or None,
            request_id=os.getenv("VIRA_REQUEST_ID") or None,
            workspace_root=os.getenv("VIRA_WORKSPACE_ROOT") or None,
        )


class BaseTool(ABC, Generic[InputT, OutputT]):
    """Abstract domain tool.

    A concrete tool declares identity/metadata as class attributes, provides
    Pydantic input and output models, and implements :meth:`run`.
    """

    namespace: ClassVar[str] = "local"
    name: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    when_to_use: ClassVar[str] = ""
    when_not_to_use: ClassVar[str] = ""
    category: ClassVar[str] = "general"
    tags: ClassVar[tuple[str, ...]] = ()
    aliases: ClassVar[tuple[str, ...]] = ()
    version: ClassVar[str] = "1.0.0"
    side_effects: ClassVar[ToolSideEffects] = ToolSideEffects.none
    idempotent: ClassVar[bool] = True
    timeout_seconds: ClassVar[int] = 30
    permissions: ClassVar[ToolPermission] = ToolPermission(actions=["read"])
    examples: ClassVar[tuple[ToolExample, ...]] = ()
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    @classmethod
    def qualified_name(cls) -> str:
        return f"{cls.namespace}.{cls.name}" if cls.namespace else cls.name

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(
            qualified_name=cls.qualified_name(),
            namespace=cls.namespace,
            name=cls.name,
            title=cls.title,
            description=cls.description,
            when_to_use=cls.when_to_use,
            when_not_to_use=cls.when_not_to_use,
            category=cls.category,
            tags=list(dict.fromkeys(cls.tags)),
            aliases=list(dict.fromkeys(cls.aliases)),
            version=cls.version,
            side_effects=cls.side_effects,
            idempotent=cls.idempotent,
            timeout_seconds=cls.timeout_seconds,
            permissions=cls.permissions,
            examples=list(cls.examples),
        )

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return cls.input_model.model_json_schema()

    @classmethod
    def output_schema(cls) -> dict[str, Any]:
        return cls.output_model.model_json_schema()

    def get_schema(self) -> dict[str, Any]:
        """Adapter for VIRA's current ToolRegistry/ToolExecutor."""
        return type(self).input_schema()

    @classmethod
    def as_mcp_tool(cls) -> Tool:
        meta = cls.metadata()
        return Tool(
            name=cls.name,
            title=meta.title,
            description=meta.description,
            inputSchema=cls.input_schema(),
            outputSchema=ToolEnvelope[cls.output_model].model_json_schema(),
        )

    @abstractmethod
    async def run(self, params: InputT, context: ToolContext) -> OutputT:
        """Execute the tool with validated input."""
        raise NotImplementedError

    async def invoke(
        self,
        arguments: dict[str, Any] | None = None,
        context: Optional[ToolContext] = None,
    ) -> ToolEnvelope[OutputT]:
        ctx = context or ToolContext()
        try:
            params = self.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            return ToolEnvelope[OutputT](
                ok=False,
                error=ToolFailure(
                    code="invalid_arguments",
                    message="The tool arguments are invalid.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        try:
            data = await asyncio.wait_for(
                self.run(params, ctx), timeout=float(self.timeout_seconds)
            )
            if not isinstance(data, self.output_model):
                data = self.output_model.model_validate(data)
            return ToolEnvelope[OutputT](
                ok=True,
                data=data,
                truncated=bool(getattr(data, "truncated", False)),
                next_cursor=getattr(data, "next_cursor", None),
            )
        except asyncio.TimeoutError:
            return ToolEnvelope[OutputT](
                ok=False,
                error=ToolFailure(
                    code="timeout",
                    message=f"The tool exceeded its {self.timeout_seconds}s timeout.",
                    retryable=True,
                ),
            )
        except ToolError as exc:
            return ToolEnvelope[OutputT](ok=False, error=exc.as_failure())
        except Exception as exc:  # noqa: BLE001 - tool boundary
            return ToolEnvelope[OutputT](
                ok=False,
                error=ToolFailure(
                    code="tool_failed",
                    message=str(exc) or exc.__class__.__name__,
                ),
            )

    async def execute(self, **kwargs: Any) -> CallToolResult:
        """Adapter for VIRA's existing ToolRegistry/ToolExecutor."""
        context_keys = {
            "user_id", "caller_user_id", "agent_id", "organization_id",
            "conversation_id", "run_id", "request_id",
        }
        context = ToolContext(
            user_id=kwargs.get("user_id") or kwargs.get("caller_user_id"),
            agent_id=kwargs.get("agent_id"),
            organization_id=kwargs.get("organization_id"),
            conversation_id=kwargs.get("conversation_id"),
            run_id=kwargs.get("run_id"),
            request_id=kwargs.get("request_id"),
        )
        arguments = {key: value for key, value in kwargs.items() if key not in context_keys}
        envelope = await self.invoke(arguments, context)
        return CallToolResult(
            content=[TextContent(type="text", text=envelope.model_dump_json())],
            structuredContent=envelope.model_dump(mode="json"),
            isError=not envelope.ok,
        )


class EchoInput(StrictModel):
    text: str


class EchoOutput(StrictModel):
    text: str


class EchoTool(BaseTool):
    """Tiny reference tool used by contract tests and documentation."""

    namespace = "example"
    name = "echo"
    title = "Echo"
    description = "Return the supplied text unchanged."
    when_to_use = "Use for wiring tests or a minimal MCP server."
    when_not_to_use = "Do not use for real work."
    category = "utility"
    tags = ("echo", "test", "example")
    input_model = EchoInput
    output_model = EchoOutput

    async def run(self, params: EchoInput, context: ToolContext) -> EchoOutput:
        return EchoOutput(text=params.text)
