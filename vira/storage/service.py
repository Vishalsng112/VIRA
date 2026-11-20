"""Object metadata plus backend selection."""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from vira.auth import database
from .base import ObjectBackend
from .local import LocalObjectBackend

_backend: Optional[ObjectBackend] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_backend() -> ObjectBackend:
    global _backend
    if _backend is not None:
        return _backend
    kind = os.environ.get("VIRA_OBJECT_STORE", "local").lower()
    if kind == "s3":
        from .s3 import S3ObjectBackend
        _backend = S3ObjectBackend(
            bucket=os.environ.get("VIRA_S3_BUCKET", ""),
            access_key=os.environ.get("VIRA_S3_ACCESS_KEY", ""),
            secret_key=os.environ.get("VIRA_S3_SECRET_KEY", ""),
            region=os.environ.get("VIRA_S3_REGION", "us-east-1"),
            endpoint=os.environ.get("VIRA_S3_ENDPOINT", ""),
            prefix=os.environ.get("VIRA_S3_PREFIX", ""),
            path_style=os.environ.get("VIRA_S3_PATH_STYLE", "1") != "0",
        )
        logger.info("Object storage backend: s3 bucket={}", os.environ.get("VIRA_S3_BUCKET"))
    else:
        root = os.environ.get("VIRA_OBJECT_DIR", "./data/objects")
        _backend = LocalObjectBackend(root)
    return _backend


def reset_backend() -> None:
    """Test helper: re-read backend configuration."""
    global _backend
    _backend = None


def max_bytes() -> int:
    try:
        return int(os.environ.get("VIRA_OBJECT_MAX_BYTES", str(50 * 1024 * 1024)))
    except ValueError:
        return 50 * 1024 * 1024


async def put(content: bytes, content_type: str = "application/octet-stream",
              user_id: Optional[int] = None, organization_id: Optional[str] = None,
              object_key: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if len(content) > max_bytes():
        raise ValueError(f"object exceeds maximum size of {max_bytes()} bytes")
    digest = hashlib.sha256(content).hexdigest()
    key = object_key or f"blobs/{digest[:2]}/{digest}"
    backend = get_backend()
    storage_key = await backend.put(key, content, content_type)
    object_id = str(uuid.uuid4())
    now = _now()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO objects (id, user_id, organization_id, object_key, content_type, "
            "size_bytes, sha256, storage_backend, storage_key, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (object_id, user_id, organization_id, key[:500], content_type[:200],
             len(content), digest, backend.name, storage_key,
             json.dumps(metadata or {}, default=str), now),
        )
    return get_record(object_id)


def get_record(object_id: str) -> Optional[Dict[str, Any]]:
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM objects WHERE id = ?", (object_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["metadata"] = json.loads(item.get("metadata") or "{}")
    except ValueError:
        item["metadata"] = {}
    return item


def list_objects(user_id: Optional[int], organization_id: Optional[str] = None,
                 limit: int = 100, is_admin: bool = False) -> List[Dict[str, Any]]:
    with database.get_connection() as conn:
        if is_admin:
            rows = conn.execute(
                "SELECT * FROM objects ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        elif organization_id:
            rows = conn.execute(
                "SELECT * FROM objects WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?",
                (organization_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM objects WHERE user_id = ? AND organization_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
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


async def read(record: Dict[str, Any]) -> bytes:
    backend = get_backend()
    if backend.name != record.get("storage_backend"):
        raise RuntimeError(
            f"object was stored with backend {record.get('storage_backend')} "
            f"but current backend is {backend.name}"
        )
    return await backend.get(record["storage_key"])


async def delete(object_id: str) -> bool:
    record = get_record(object_id)
    if record is None:
        return False
    backend = get_backend()
    if backend.name == record.get("storage_backend"):
        try:
            await backend.delete(record["storage_key"])
        except Exception as exc:
            logger.warning("Object backend delete failed for {}: {}", object_id, exc)
    with database.transaction() as conn:
        conn.execute("DELETE FROM objects WHERE id = ?", (object_id,))
    return True


def can_access(record: Dict[str, Any], user_id: int, is_admin: bool = False) -> bool:
    if is_admin or record.get("user_id") == user_id:
        return True
    organization_id = record.get("organization_id")
    if organization_id:
        from vira.organizations import service as org_service
        return org_service.is_member(organization_id, user_id)
    return False
