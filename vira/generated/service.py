"""Lifecycle for generated tools and agents: draft → approve → enable."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from vira.agent.loop import AgentLoop, LoopConfig
from vira.generated import store
from vira.generated.tools import (
    GeneratedHttpTool,
    validate_agent_spec,
    validate_name,
    validate_spec,
)


class GeneratedError(Exception):
    pass


def checksum(spec: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def create_draft(*, kind: str, name: str, version: str, description: str,
                 spec: Dict[str, Any], created_by_user_id: Optional[int]) -> Dict[str, Any]:
    if kind not in store.KINDS:
        raise GeneratedError("kind must be tool or agent")
    clean_name = validate_name(name)
    clean_version = str(version or "1.0.0").strip()[:40] or "1.0.0"
    if store.find(kind, clean_name, clean_version):
        raise GeneratedError("an artifact with this kind, name and version already exists")
    try:
        clean_spec = validate_spec(spec) if kind == "tool" else validate_agent_spec(spec)
    except (TypeError, ValueError) as exc:
        raise GeneratedError(str(exc)) from exc
    return store.create(
        kind=kind,
        name=clean_name,
        version=clean_version,
        description=" ".join(str(description or "").split())[:500],
        spec=clean_spec,
        checksum=checksum(clean_spec),
        created_by_user_id=created_by_user_id,
    )


def approve(artifact_id: str, approved_by_user_id: int) -> Dict[str, Any]:
    current = store.get(artifact_id)
    if current is None:
        raise GeneratedError("artifact not found")
    if current["status"] != "draft":
        raise GeneratedError(f"only draft artifacts can be approved (current: {current['status']})")
    updated = store.set_status(artifact_id, "approved", approved_by_user_id=approved_by_user_id)
    if updated is None:
        raise GeneratedError("artifact not found")
    return updated


def reject(artifact_id: str, reason: str = "") -> Dict[str, Any]:
    current = store.get(artifact_id)
    if current is None:
        raise GeneratedError("artifact not found")
    if current["status"] not in ("draft", "approved"):
        raise GeneratedError(f"cannot reject a {current['status']} artifact")
    updated = store.set_status(artifact_id, "rejected", rejection_reason=reason)
    if updated is None:
        raise GeneratedError("artifact not found")
    return updated


def enable(artifact_id: str) -> Dict[str, Any]:
    current = store.get(artifact_id)
    if current is None:
        raise GeneratedError("artifact not found")
    if not current.get("approved_at"):
        raise GeneratedError("artifact must be approved before it can be enabled")
    if current["status"] not in ("approved", "disabled"):
        raise GeneratedError(f"cannot enable a {current['status']} artifact")
    updated = store.set_status(artifact_id, "enabled")
    if updated is None:
        raise GeneratedError("artifact not found")
    return updated


def disable(artifact_id: str) -> Dict[str, Any]:
    current = store.get(artifact_id)
    if current is None:
        raise GeneratedError("artifact not found")
    if current["status"] != "enabled":
        raise GeneratedError(f"cannot disable a {current['status']} artifact")
    updated = store.set_status(artifact_id, "disabled")
    if updated is None:
        raise GeneratedError("artifact not found")
    return updated


def sync_registry(registry) -> List[str]:
    """Register exactly the enabled generated tools; remove stale ones."""
    if registry is None:
        return []
    registry.remove_by_provider("generated")
    registered = []
    for artifact in store.list_artifacts(kind="tool", status="enabled", limit=500):
        try:
            tool = GeneratedHttpTool(
                artifact_id=artifact["id"],
                name=artifact["name"],
                description=artifact["description"],
                spec=artifact["spec"],
                status_provider=lambda artifact_id=artifact["id"]: store.get(artifact_id),
            )
        except (ValueError, TypeError):
            continue
        registry.register(tool, qualified_name=f"generated.{artifact['name']}")
        registered.append(f"generated.{artifact['name']}")
    return registered


def _available_tool_specs(runtime) -> List[Dict[str, Any]]:
    executor = getattr(runtime, "tool_executor", None)
    registry = getattr(executor, "_registry", None) if executor else None
    if not executor or not registry:
        return []
    specs = []
    for name in executor.list_tools():
        tool = registry.get(name)
        if tool is None:
            continue
        specs.append({
            "name": name,
            "description": getattr(tool, "description", ""),
            "parameters": tool.get_schema() if hasattr(tool, "get_schema") else {},
        })
    return specs


async def run_agent(artifact: Dict[str, Any], task: str, runtime, *,
                    user_id: Optional[int], device_id: Optional[str] = None,
                    organization_id: Optional[str] = None,
                    run_id: Optional[str] = None) -> Dict[str, Any]:
    """Execute an approved+enabled generated agent over a bounded tool loop."""
    if artifact.get("kind") != "agent":
        raise GeneratedError("artifact is not an agent")
    if artifact.get("status") != "enabled" or not artifact.get("approved_at"):
        raise GeneratedError("agent is not approved and enabled")
    spec = artifact.get("spec") or {}
    allowed = set(spec.get("tools") or [])
    specs = [
        item for item in _available_tool_specs(runtime)
        if item["name"] in allowed or item["name"].split(".")[-1] in allowed
    ]
    loop = AgentLoop(
        runtime,
        f"generated-{artifact['name']}",
        spec.get("system_prompt", ""),
        specs,
        LoopConfig(
            max_steps=int(spec.get("max_steps", 4)),
            max_prompt_chars=12000,
            max_tool_chars=3000,
            tool_timeout=60,
        ),
        temperature=float(spec.get("temperature", 0.2)),
        max_tokens=1024,
    )
    result = await loop.run(
        str(task or "").strip(), user_id=user_id, device_id=device_id,
        organization_id=organization_id, run_id=run_id,
    )
    return {
        "response": result.text,
        "tool_calls": result.tool_calls,
        "stopped": result.stopped,
        "artifact_id": artifact["id"],
        "version": artifact.get("version"),
    }
