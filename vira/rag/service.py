"""Small persistent RAG backend: chunk, embed and retrieve local documents."""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vira.auth import database
from vira.memory.embeddings import cosine_any, get_embedding_provider


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> List[str]:
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= size:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= size:
            current = paragraph
        else:
            start = 0
            while start < len(paragraph):
                chunk = paragraph[start:start + size]
                chunks.append(chunk)
                start += max(1, size - overlap)
            current = ""
    if current:
        chunks.append(current)
    return chunks


async def ingest(user_id: int, title: str, content: str,
                 source: str = "manual", metadata: Optional[Dict[str, Any]] = None,
                 organization_id: Optional[str] = None) -> Dict[str, Any]:
    document_id = str(uuid.uuid4())
    now = _now()
    chunks = chunk_text(content)
    provider = get_embedding_provider()
    embed = getattr(provider, "embed", None)
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO rag_documents (id, user_id, organization_id, title, source, metadata, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (document_id, user_id, organization_id, title[:300], source[:100],
             json.dumps(metadata or {}, default=str), now, now),
        )
    for index, chunk in enumerate(chunks):
        vector = await provider.embed(chunk)
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO rag_chunks (id, document_id, user_id, chunk_index, content, metadata, "
                "model, dims, vector, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), document_id, user_id, index, chunk,
                 json.dumps(metadata or {}, default=str), provider.model,
                 len(vector), json.dumps(vector), now),
            )
    return {"id": document_id, "title": title, "chunks": len(chunks),
            "source": source, "created_at": now}


def list_documents(user_id: int, limit: int = 100,
                   organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        if organization_id:
            rows = conn.execute(
                "SELECT d.*, COUNT(c.id) AS chunks FROM rag_documents d "
                "LEFT JOIN rag_chunks c ON c.document_id = d.id "
                "WHERE d.organization_id = ? GROUP BY d.id ORDER BY d.created_at DESC LIMIT ?",
                (organization_id, min(max(limit, 1), 500)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT d.*, COUNT(c.id) AS chunks FROM rag_documents d "
                "LEFT JOIN rag_chunks c ON c.document_id = d.id "
                "WHERE d.user_id = ? AND d.organization_id IS NULL "
                "GROUP BY d.id ORDER BY d.created_at DESC LIMIT ?",
                (user_id, min(max(limit, 1), 500)),
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.get("metadata") or "{}")
        except ValueError:
            item["metadata"] = {}
        result.append(item)
    return result


def delete_document(user_id: int, document_id: str,
                    organization_id: Optional[str] = None) -> bool:
    with database.transaction() as conn:
        if organization_id:
            cur = conn.execute(
                "DELETE FROM rag_documents WHERE id = ? AND organization_id = ?",
                (document_id, organization_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM rag_documents WHERE id = ? AND user_id = ? "
                "AND organization_id IS NULL",
                (document_id, user_id),
            )
        return bool(cur.rowcount)


async def search(user_id: int, query: str, limit: int = 8,
                 document_id: Optional[str] = None,
                 organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
    provider = get_embedding_provider()
    query_vector = await provider.embed(query)
    if organization_id:
        clauses = ["d.organization_id = ?"]
        values: List[Any] = [organization_id]
    else:
        clauses = ["c.user_id = ?", "d.organization_id IS NULL"]
        values = [user_id]
    if document_id:
        clauses.append("c.document_id = ?")
        values.append(document_id)
    values.append(500)
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT c.id, c.document_id, c.chunk_index, c.content, c.vector, c.metadata, "
            "d.title, d.source FROM rag_chunks c JOIN rag_documents d ON d.id = c.document_id "
            f"WHERE {' AND '.join(clauses)} LIMIT ?",
            values,
        ).fetchall()
    scored = []
    for row in rows:
        item = dict(row)
        try:
            vector = json.loads(item.pop("vector"))
            item["metadata"] = json.loads(item.get("metadata") or "{}")
        except ValueError:
            continue
        score = cosine_any(query_vector, vector)
        if score > 0:
            item["score"] = round(score, 6)
            scored.append(item)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]
