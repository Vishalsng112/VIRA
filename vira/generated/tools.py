"""Runtime adapter for an approval-gated generated HTTP tool.

Generated tools are deliberately narrow: one HTTPS GET, no custom headers, no
secrets, an explicit host allow-list and a JSON-schema-style parameter list.
Every invocation re-checks the approval state, so disabling or rejecting a tool
takes effect immediately even if it is still present in a live registry.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

from vira.tooling import ToolPermission, text_result

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def validate_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise a generated tool spec."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    if spec.get("type", "http") != "http":
        raise ValueError("only declarative 'http' generated tools are supported")
    if str(spec.get("method", "GET")).upper() != "GET":
        raise ValueError("generated tools only support GET")
    url = str(spec.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("generated tool url must be absolute https")
    allowed = spec.get("allowed_hosts") or [parsed.hostname]
    if not isinstance(allowed, list) or parsed.hostname not in allowed:
        raise ValueError("url host must be listed in allowed_hosts")
    parameters = spec.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    for key, schema in parameters.items():
        if not isinstance(key, str) or not isinstance(schema, dict):
            raise ValueError("each parameter needs a schema object")
        if schema.get("type") not in ("string", "integer", "number", "boolean"):
            raise ValueError("parameter types must be string/integer/number/boolean")
    query = spec.get("query") or {}
    if not isinstance(query, dict):
        raise ValueError("query must be an object")
    max_chars = int(spec.get("max_chars", 6000) or 6000)
    return {
        "type": "http",
        "method": "GET",
        "url": url,
        "allowed_hosts": [str(host) for host in allowed],
        "parameters": parameters,
        "query": query,
        "response_format": str(spec.get("response_format", "text")),
        "max_chars": max(200, min(max_chars, 20000)),
    }


def validate_agent_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    prompt = str(spec.get("system_prompt") or "").strip()
    if len(prompt) < 20:
        raise ValueError("system_prompt must be at least 20 characters")
    tools = spec.get("tools") or []
    if not isinstance(tools, list) or any(not isinstance(item, str) for item in tools):
        raise ValueError("tools must be a list of tool names")
    try:
        max_steps = int(spec.get("max_steps", 4))
    except (TypeError, ValueError):
        max_steps = 4
    return {
        "system_prompt": prompt[:8000],
        "tools": tools[:40],
        "max_steps": max(1, min(max_steps, 8)),
        "temperature": float(spec.get("temperature", 0.2) or 0.2),
    }


def validate_name(name: str) -> str:
    value = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not _NAME.match(value):
        raise ValueError("name must be 3-41 lowercase letters, digits or underscores")
    return value


class GeneratedHttpTool:
    def __init__(self, *, artifact_id: str, name: str, description: str,
                 spec: Dict[str, Any],
                 status_provider: Callable[[], Optional[Dict[str, Any]]]):
        self.spec = validate_spec(spec)
        self.artifact_id = artifact_id
        self.status_provider = status_provider
        self.server_name = "generated"
        self.generated_id = artifact_id
        self.name = name
        self.description = description or f"Generated HTTP tool: {name}"
        self.permissions = ToolPermission(actions=["read", "execute"])
        self.input_schema = {
            "type": "object",
            "properties": self.spec["parameters"],
            "required": [
                key for key, value in self.spec["parameters"].items()
                if value.get("required") is True
            ],
            "additionalProperties": False,
        }

    def get_schema(self):
        return self.input_schema

    def _check_enabled(self) -> None:
        current = self.status_provider()
        if not current or current.get("status") != "enabled" or not current.get("approved_at"):
            raise PermissionError(
                "This generated tool is not approved and enabled. "
                "An administrator must approve and enable it first."
            )

    def _build_url(self, params: Dict[str, Any]) -> str:
        spec = self.spec
        url = _PLACEHOLDER.sub(
            lambda match: str(params.get(match.group(1), "")), spec["url"]
        )
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in spec["allowed_hosts"]:
            raise ValueError("Generated tool URL host is not allowed")
        query = list(parse_qsl(parsed.query, keep_blank_values=True))
        for key, template in spec["query"].items():
            value = _PLACEHOLDER.sub(
                lambda match: str(params.get(match.group(1), "")), str(template)
            )
            query.append((str(key), value))
        return urlunparse(parsed._replace(query=urlencode(query)))

    async def execute(self, **kwargs: Any):
        try:
            self._check_enabled()
        except PermissionError as exc:
            return text_result(str(exc), is_error=True)
        params = {key: value for key, value in kwargs.items() if key in self.spec["parameters"]}
        missing = [
            key for key, schema in self.spec["parameters"].items()
            if schema.get("required") and key not in params
        ]
        if missing:
            return text_result(f"Missing required parameter(s): {', '.join(missing)}", is_error=True)
        try:
            url = self._build_url(params)
            from vira.tooling.services import webtools

            await webtools._check_public(url)
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"Accept": "application/json, text/plain"}) as response:
                    if response.status >= 400:
                        return text_result(
                            f"Generated tool request failed: HTTP {response.status}", is_error=True
                        )
                    body = await response.text(errors="replace")
            body = body[: self.spec["max_chars"]]
            if self.spec["response_format"] == "json":
                try:
                    parsed = json.loads(body)
                except ValueError as exc:
                    return text_result(
                        f"Generated tool returned invalid JSON: {exc}", is_error=True
                    )
                body = json.dumps(parsed, ensure_ascii=False, default=str)[: self.spec["max_chars"]]
            return text_result(body)
        except (PermissionError, ValueError, OSError, asyncio.TimeoutError, aiohttp.ClientError) as exc:
            return text_result(f"Generated tool error: {exc}", is_error=True)
