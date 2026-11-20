import hashlib
from pathlib import Path

from .base import ObjectBackend


class LocalObjectBackend(ObjectBackend):
    name = "local"

    def __init__(self, root: str = "./data/objects"):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        path = (self.root / digest[:2] / digest[2:]).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid object key")
        return path

    async def put(self, key: str, content: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    async def get(self, storage_key: str) -> bytes:
        path = Path(storage_key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid storage key")
        return path.read_bytes()

    async def delete(self, storage_key: str) -> None:
        path = Path(storage_key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid storage key")
        path.unlink(missing_ok=True)
