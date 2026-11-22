"""VIRA-owned context, insight, chat and knowledge tools."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from ...contract import BaseTool, StrictModel, ToolContext, ToolError
from ..common import JsonOutput, TextOutput


class ContextInput(StrictModel):
    device_id: Optional[str] = None


class InsightsInput(StrictModel):
    device_id: Optional[str] = None
    days: int = Field(default=7, ge=1, le=90)
    include_apps: bool = True


class ChatStatisticsInput(StrictModel):
    pass


class KnowledgeSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=30)
    scopes: Optional[list[str]] = None
    kinds: Optional[list[str]] = None
    agent_role: Optional[str] = None


class ViraContextTool(BaseTool):
    namespace = "vira"
    name = "context"
    title = "Get user and device context"
    description = "Return linked devices, consent, battery, health and a short usage summary."
    when_to_use = (
        "Use before personalised recommendations when identity or device context matters."
    )
    when_not_to_use = "Do not use for raw event history or another user's data."
    category = "vira"
    tags = ("vira", "context", "devices", "battery", "health", "consent")
    input_model = ContextInput
    output_model = TextOutput

    async def run(self, params: ContextInput, context: ToolContext) -> TextOutput:
        if not context.user_id:
            raise ToolError("auth_required", "An authenticated VIRA user is required.")
        from vira.devices import consent, store as device_store
        from vira.insights.service import summarize_device

        devices = device_store.list_devices_for_user(context.user_id, limit=50)
        if not devices:
            return TextOutput(text="No linked devices.")
        selected = next(
            (d for d in devices if d["id"] == params.device_id), None
        ) if params.device_id else devices[0]
        if selected is None:
            raise ToolError("not_found", "That device is not linked to this user.")
        consent_rows = consent.list_for_device(selected["id"])
        latest = {
            row["event_type"]: row["payload"]
            for row in device_store.get_latest_state(selected["id"])
        }
        summary = summarize_device(selected["id"], 7)
        enabled = [row["collector"] for row in consent_rows if row["enabled"]]
        battery = latest.get("device.battery.state") or summary.get("battery") or {}
        health = latest.get("device.health.state") or summary.get("health") or {}
        text = "\n".join([
            f"User id: {context.user_id}",
            "Devices: " + ", ".join(
                f"{d['display_name']} ({d['platform']})" for d in devices[:5]
            ),
            f"Selected device: {selected['display_name']} ({selected['platform']})",
            f"Enabled collectors: {', '.join(enabled) or 'none'}",
            f"Battery: {battery}",
            f"Health: {health}",
            summary["summary"],
        ])
        return TextOutput(text=text)


class ViraInsightsTool(BaseTool):
    namespace = "vira"
    name = "insights"
    title = "Summarise device activity"
    description = "Return screen time, top apps, categories, focus, battery and health warnings."
    when_to_use = (
        "Use for questions about the user's usage, focus, productivity or wellbeing."
    )
    when_not_to_use = "Do not use for live web facts or other users' devices."
    category = "vira"
    tags = ("vira", "insights", "usage", "focus", "wellbeing", "screen-time")
    aliases = ("social", "apps", "screen", "time", "activity", "device", "usage")
    input_model = InsightsInput
    output_model = TextOutput

    async def run(self, params: InsightsInput, context: ToolContext) -> TextOutput:
        if not context.user_id:
            raise ToolError("auth_required", "An authenticated VIRA user is required.")
        from vira.devices import store as device_store
        from vira.insights.service import summarize_device

        devices = device_store.list_devices_for_user(context.user_id, limit=200)
        if not devices:
            raise ToolError(
                "no_devices",
                "No enrolled devices have sent data for this user yet.",
                next_steps=["Open VIRA Link and let it sync first."],
            )
        selected = None
        if params.device_id:
            selected = next((d for d in devices if d["id"] == params.device_id), None)
            if selected is None:
                raise ToolError("not_found", "That device is not linked to this user.")
        else:
            selected = devices[0]
        data = summarize_device(selected["id"], params.days, include_apps=params.include_apps)
        top = ", ".join(
            f"{app['label']} ({app['foreground_ms'] // 60000}m)"
            for app in data["top_apps"][:5]
        ) or "no app data"
        categories = ", ".join(
            f"{item['category']} ({item['foreground_ms'] // 60000}m)"
            for item in data.get("categories", [])[:5]
        ) or "no category data"
        warnings = data["health"].get("warnings", [])
        battery = data.get("battery") or {}
        lines = [
            f"Device: {selected['display_name']} ({selected.get('platform', 'unknown')})",
            data["summary"],
            f"Top apps: {top}." if params.include_apps else "Top apps: hidden for privacy.",
            f"Categories: {categories}.",
            f"Focus score: {data['focus'].get('score', 0)}/100. "
            f"Focus sessions: {data['totals'].get('focus_sessions', 0)}.",
        ]
        if battery:
            lines.append(
                f"Battery: {battery.get('level_percent', '?')}% "
                f"({'charging' if battery.get('charging') else 'on battery'})."
            )
        if warnings:
            lines.append("Health warnings: " + "; ".join(warnings))
        return TextOutput(text="\n".join(lines))


class ViraChatStatisticsTool(BaseTool):
    namespace = "vira"
    name = "chat_statistics"
    title = "Chat statistics"
    description = "Return the caller's total chat and message counts."
    when_to_use = "Use when the user asks how many chats or messages they have."
    when_not_to_use = "Do not use for message content."
    category = "vira"
    tags = ("vira", "chat", "statistics", "messages", "count")
    input_model = ChatStatisticsInput
    output_model = JsonOutput

    async def run(self, params: ChatStatisticsInput, context: ToolContext) -> JsonOutput:
        if not context.user_id:
            raise ToolError("auth_required", "An authenticated VIRA user is required.")
        from vira.auth import database
        return JsonOutput(payload=database.get_chat_statistics(context.user_id))


class ViraKnowledgeSearchTool(BaseTool):
    namespace = "vira"
    name = "knowledge_search"
    title = "Search VIRA knowledge"
    description = "Search durable knowledge, documents and episodic memory with scope metadata."
    when_to_use = (
        "Use for saved notes, prior decisions, documents or remembered facts."
    )
    when_not_to_use = "Do not use for live web facts; use web.research."
    category = "vira"
    tags = ("vira", "knowledge", "notes", "documents", "memory", "rag")
    input_model = KnowledgeSearchInput
    output_model = JsonOutput

    async def run(self, params: KnowledgeSearchInput, context: ToolContext) -> JsonOutput:
        if not context.user_id:
            raise ToolError("auth_required", "An authenticated VIRA user is required.")
        try:
            from vira.knowledge import service as knowledge_service
            results = await knowledge_service.search(
                params.query,
                user_id=context.user_id,
                agent_role=params.agent_role,
                agent_id=context.agent_id,
                conversation_id=context.conversation_id,
                organization_id=context.organization_id,
                scopes=params.scopes,
                limit=params.limit,
            )
        except Exception as exc:  # noqa: BLE001 - tool boundary
            raise ToolError("knowledge_search_failed", str(exc)) from exc
        items = [{
            "id": item.get("id"),
            "origin": item.get("_origin"),
            "scope": item.get("scope"),
            "status": item.get("status"),
            "kind": item.get("kind"),
            "title": item.get("title"),
            "content": item.get("excerpt") or item.get("content"),
            "score": item.get("score"),
            "confidence": item.get("confidence"),
            "source": item.get("source"),
        } for item in results]
        return JsonOutput(payload={"results": items})


TOOLS = [
    ViraContextTool,
    ViraInsightsTool,
    ViraChatStatisticsTool,
    ViraKnowledgeSearchTool,
]


class KnowledgeWriteInput(StrictModel):
    content: str = Field(min_length=1, max_length=20000)
    kind: str = "fact"
    scope: Optional[str] = None
    requested_by_user: bool = False
    agent_role: Optional[str] = None
    summary: Optional[str] = None
    confidence: float = 0.5
    importance: float = 0.0
    tags: Optional[list[str]] = None


class RagSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=30)


class ViraKnowledgeWriteTool(BaseTool):
    namespace = "vira"
    name = "knowledge_write"
    title = "Remember knowledge"
    description = "Persist a fact, decision or note in VIRA's scoped knowledge base."
    when_to_use = (
        "Use when the user explicitly asks you to remember something, or when a "
        "durable decision should be available later."
    )
    when_not_to_use = "Do not use for transient conversation details or guesses."
    category = "vira"
    tags = ("vira", "knowledge", "memory", "remember", "notes", "write")
    side_effects = "write"
    idempotent = False
    input_model = KnowledgeWriteInput
    output_model = JsonOutput

    async def run(self, params: KnowledgeWriteInput, context: ToolContext) -> JsonOutput:
        if not context.user_id:
            raise ToolError("auth_required", "An authenticated VIRA user is required.")
        try:
            from vira.knowledge import service as knowledge_service
            item = await knowledge_service.write(
                params.content,
                user_id=context.user_id,
                kind=params.kind,
                scope=params.scope,
                requested_by_user=params.requested_by_user,
                agent_role=params.agent_role,
                agent_id=context.agent_id,
                conversation_id=context.conversation_id,
                summary=params.summary,
                confidence=params.confidence,
                importance=params.importance,
                tags=params.tags or [],
                organization_id=context.organization_id,
            )
        except Exception as exc:  # noqa: BLE001 - tool boundary
            raise ToolError("knowledge_write_failed", str(exc)) from exc
        payload = item if isinstance(item, dict) else {"result": item}
        return JsonOutput(payload=payload)


class ViraRagSearchTool(BaseTool):
    namespace = "vira"
    name = "rag_search"
    title = "Search uploaded documents"
    description = "Search the user's uploaded/local document index."
    when_to_use = "Use for notes, PDFs, documents and reference material."
    when_not_to_use = "Do not use for live web facts or durable agent knowledge; use web.research or vira.knowledge_search."
    category = "vira"
    tags = ("vira", "rag", "documents", "files", "search", "knowledge")
    input_model = RagSearchInput
    output_model = JsonOutput

    async def run(self, params: RagSearchInput, context: ToolContext) -> JsonOutput:
        if not context.user_id:
            raise ToolError("auth_required", "An authenticated VIRA user is required.")
        try:
            from vira.rag import service as rag_service
            results = await rag_service.search(context.user_id, params.query, params.limit)
        except Exception as exc:  # noqa: BLE001 - tool boundary
            raise ToolError("rag_search_failed", str(exc)) from exc
        return JsonOutput(payload={"results": results})


TOOLS = [*TOOLS, ViraKnowledgeWriteTool, ViraRagSearchTool]
