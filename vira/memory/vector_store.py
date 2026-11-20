"""Persistent embedding index for memories (SQLite-backed vector search)."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database
from .embeddings import cosine_any, get_embedding_provider


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def index_memory(memory_id: str, user_id: Optional[int], content: str) -> bool:
    provider = get_embedding_provider()
    vector = await provider.embed(content)
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO memory_embeddings (memory_id, user_id, model, dims, vector, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(memory_id) DO UPDATE SET "
            "model = excluded.model, dims = excluded.dims, vector = excluded.vector, "
            "updated_at = excluded.updated_at",
            (memory_id, user_id, provider.model, len(vector),
             json.dumps(vector), _now()),
        )
    return True


async def search(user_id: int, query: str, limit: int = 10,
                 agent_id: Optional[str] = None,
                 conversation_id: Optional[str] = None,
                 memory_type: Optional[str] = None) -> List[Dict[str, Any]]:
    provider = get_embedding_provider()
    query_vector = await provider.embed(query)
    clauses = ["e.user_id = ?"]
    values: List[Any] = [user_id]
    if agent_id:
        clauses.append("(m.agent_id = ? OR m.agent_id IS NULL)")
        values.append(agent_id)
    if conversation_id:
        clauses.append("(m.conversation_id = ? OR m.conversation_id IS NULL)")
        values.append(conversation_id)
    if memory_type:
        clauses.append("m.memory_type = ?")
        values.append(memory_type)
    values.append(max(limit * 10, 50))
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT m.*, e.vector AS _vector, e.model AS _model FROM memory_embeddings e "
            f"JOIN memories m ON m.id = e.memory_id WHERE {' AND '.join(clauses)} LIMIT ?",
            values,
        ).fetchall()
    scored = []
    for row in rows:
        item = dict(row)
        try:
            vector = json.loads(item.pop("_vector"))
        except (TypeError, ValueError):
            continue
        item.pop("_model", None)
        item["_score"] = round(cosine_any(query_vector, vector), 6)
        if item["_score"] > 0:
            scored.append(item)
    scored.sort(key=lambda item: item["_score"], reverse=True)
    return scored[:limit]


def delete_embedding(memory_id: str) -> None:
    with database.transaction() as conn:
        conn.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,))
