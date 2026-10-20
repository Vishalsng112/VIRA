"""Private local filesystem artifact storage."""
import hashlib
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from .base import ArtifactRef


class LocalArtifactStore:
    def __init__(self, root: str = "./data/artifacts"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(
        self, content: bytes, content_type: str, metadata: Dict[str, Any] | None = None
    ) -> ArtifactRef:
        artifact_id = str(uuid4())
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / artifact_id
        path.write_bytes(content)
        return ArtifactRef(
            artifact_id=artifact_id,
            storage_key=str(path),
            content_type=content_type,
            size_bytes=len(content),
            sha256=digest,
            metadata=metadata or {},
        )

    async def get(self, artifact_id: str) -> bytes:
        path = (self.root / artifact_id).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("Invalid artifact ID")
        return path.read_bytes()

    async def delete(self, artifact_id: str) -> None:
        path = (self.root / artifact_id).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("Invalid artifact ID")
        path.unlink(missing_ok=True)
