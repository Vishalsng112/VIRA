"""Storage port for large tool results and generated artifacts."""
from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str
    metadata: Dict[str, Any]


class ArtifactStore(Protocol):
    async def put(
        self, content: bytes, content_type: str, metadata: Dict[str, Any] | None = None
    ) -> ArtifactRef:
        ...

    async def get(self, artifact_id: str) -> bytes:
        ...

    async def delete(self, artifact_id: str) -> None:
        ...
