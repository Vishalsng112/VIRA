"""Agent tools for reading and writing VIRA's scoped knowledge base.

``knowledge_search`` merges durable knowledge, uploaded documents and episodic
memory.  ``knowledge_write`` is the agent's "remember this" path: it never
writes global knowledge directly and records who (user or agent) asked for the
write.
"""
import json
from typing import Any, List, Optional

from vira.knowledge import policy as knowledge_policy
from vira.knowledge import service as knowledge_service
from vira.knowledge.models import KnowledgeKind
from vira.tools import context as tool_context
from vira.tools.base import BaseTool, ToolPermission, text_result

_KINDS = [kind.value for kind in KnowledgeKind]


def _json(value: Any) -> Any:
    return text_result(json.dumps(value, ensure_ascii=False, default=str))


class KnowledgeSearchTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="knowledge_search",
            description=(
                "Search VIRA's knowledge base: durable agent learnings, the "
                "user's uploaded documents and episodic memory. Results are "
                "scoped (conversation/personal/agent/org/global) and carry a "
                "status so you can judge trust. Prefer this over rag_search."
            ),
            permissions=ToolPermission(actions=["read", "execute"]),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "scopes": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(knowledge_policy.ALL_SCOPES)},
                        "description": "Optional scope filter. Defaults to every scope you can read.",
                    },
                    "kinds": {
                        "type": "array",
                        "items": {"type": "string", "enum": _KINDS},
                    },
                    "agent_role": {
                        "type": "string",
                        "description": "Stable role name (for example 'researcher'), not the runtime agent id.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    async def execute(self, query: str = "", limit: int = 8,
                      scopes: Optional[List[str]] = None,
                      kinds: Optional[List[str]] = None,
                      agent_role: Optional[str] = None,
                      agent_id: Optional[str] = None,
                      conversation_id: Optional[str] = None,
                      user_id: Any = None,
                      organization_id: Optional[str] = None,
                      **_: Any) -> Any:
        try:
            numeric = int(user_id if user_id is not None
                          else tool_context.caller_user_id.get())
        except (TypeError, ValueError):
            return text_result("ERROR: authenticated user required.", is_error=True)
        org = organization_id or tool_context.organization_id.get()
        run_id = tool_context.run_id.get()
        try:
            results = await knowledge_service.search(
                query,
                user_id=numeric,
                agent_role=agent_role,
                agent_id=agent_id,
                conversation_id=conversation_id,
                organization_id=org,
                scopes=scopes,
                limit=limit,
            )
        except Exception as exc:
            return text_result(f"ERROR: {type(exc).__name__}: {exc}", is_error=True)

        items = []
        for item in results:
            items.append({
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
            })
        if run_id:
            for item in items:
                item["run_id"] = run_id
        return _json(items)


class KnowledgeWriteTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="knowledge_write",
            description=(
                "Persist something worth remembering. Set requested_by_user=true "
                "when the user explicitly asked you to remember it (stored as "
                "verified personal knowledge). Otherwise the item is saved as a "
                "draft in your agent role's scope and may later be promoted to "
                "shared knowledge. Never invents citations."
            ),
            permissions=ToolPermission(actions=["read", "write", "execute"]),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The knowledge to store, self-contained."},
                    "kind": {"type": "string", "enum": _KINDS},
                    "scope": {
                        "type": "string",
                        "enum": list(knowledge_policy.WRITABLE_SCOPES),
                        "description": "Optional explicit scope. global is promotion-only.",
                    },
                    "requested_by_user": {"type": "boolean"},
                    "agent_role": {"type": "string"},
                    "summary": {"type": "string"},
                    "confidence": {"type": "number"},
                    "importance": {"type": "number"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        )

    async def execute(self, content: str = "", kind: str = "fact",
                      scope: Optional[str] = None,
                      requested_by_user: bool = False,
                      agent_role: Optional[str] = None,
                      agent_id: Optional[str] = None,
                      conversation_id: Optional[str] = None,
                      summary: Optional[str] = None,
                      confidence: float = 0.5,
                      importance: float = 0.0,
                      tags: Optional[List[str]] = None,
                      user_id: Any = None,
                      organization_id: Optional[str] = None,
                      **_: Any) -> Any:
        try:
            numeric = int(user_id if user_id is not None
                          else tool_context.caller_user_id.get())
        except (TypeError, ValueError):
            return text_result("ERROR: authenticated user required.", is_error=True)
        if kind not in _KINDS:
            return text_result(f"ERROR: unknown kind '{kind}'", is_error=True)
        org = organization_id or tool_context.organization_id.get()
        try:
            item = await knowledge_service.write(
                content,
                user_id=numeric,
                kind=kind,
                scope=scope,
                requested_by_user=bool(requested_by_user),
                agent_role=agent_role,
                agent_id=agent_id,
                run_id=tool_context.run_id.get(),
                conversation_id=conversation_id,
                organization_id=org,
                summary=summary,
                confidence=float(confidence or 0.5),
                importance=float(importance or 0.0),
                tags=tags,
            )
        except PermissionError as exc:
            return text_result(f"ERROR: {exc}", is_error=True)
        except Exception as exc:
            return text_result(f"ERROR: {type(exc).__name__}: {exc}", is_error=True)
        return _json({
            "stored": True,
            "id": item.get("id"),
            "scope": item.get("scope"),
            "status": item.get("status"),
            "revision": item.get("revision"),
            "duplicate": item.get("duplicate", False),
        })
