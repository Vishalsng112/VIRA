from abc import ABC, abstractmethod
from typing import Optional


class ObjectBackend(ABC):
    name = "base"

    @abstractmethod
    async def put(self, key: str, content: bytes, content_type: str) -> str:
        """Store bytes and return the backend storage key."""

    @abstractmethod
    async def get(self, storage_key: str) -> bytes:
        ...

    @abstractmethod
    async def delete(self, storage_key: str) -> None:
        ...
