"""Dependency-free hashed embeddings for local memory re-ranking.

This is deliberately lightweight: tokens are hashed into a fixed vector with
signed counts, then combined with lexical overlap.  It gives useful semantic-ish
retrieval on a local machine without downloading an embedding model, and can be
replaced by a real vector store later.
"""
import hashlib
import math
import os
import re
from collections import Counter
from typing import Iterable, List, Optional, Sequence, Tuple

import aiohttp
from loguru import logger

_WORD = re.compile(r"[a-zA-Z0-9_]{2,}")
_STOP = {
    "the", "and", "for", "with", "that", "this", "what", "how", "can", "you",
    "are", "was", "from", "have", "has", "not", "use", "about", "into",
}


def tokens(text: str) -> List[str]:
    return [word.lower() for word in _WORD.findall(text or "")
            if word.lower() not in _STOP]


def embed(text: str, dims: int = 256) -> List[float]:
    vector = [0.0] * dims
    counts = Counter(tokens(text))
    for token, count in counts.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def hybrid_score(query: str, content: str) -> float:
    query_tokens = set(tokens(query))
    content_tokens = set(tokens(content))
    if not query_tokens:
        return 0.0
    lexical = len(query_tokens & content_tokens) / len(query_tokens)
    vector = max(0.0, cosine(embed(query), embed(content)))
    return 0.7 * lexical + 0.3 * vector


def rank(query: str, items: Iterable[Tuple[object, str]], limit: int = 10):
    scored = [(hybrid_score(query, text), item) for item, text in items]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for score, item in scored if score > 0][:limit]


class EmbeddingProvider:
    name = "base"
    model = "hash"

    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError


class HashedEmbeddingProvider(EmbeddingProvider):
    name = "hash"
    model = "hashed-256"

    async def embed(self, text: str) -> List[float]:
        return embed(text)


class OllamaEmbeddingProvider(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str = "nomic-embed-text",
                 base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def embed(self, text: str) -> List[float]:
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(f"ollama embeddings HTTP {response.status}")
                    data = await response.json()
                    vector = data.get("embedding")
                    if isinstance(vector, list) and vector:
                        return [float(value) for value in vector]
        except Exception as exc:
            logger.warning("Ollama embedding failed; falling back to hashed: {}", exc)
        return embed(text)


_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider
    kind = os.environ.get("VIRA_EMBEDDING_PROVIDER", "hash").lower()
    if kind == "ollama":
        _provider = OllamaEmbeddingProvider(
            model=os.environ.get("VIRA_EMBEDDING_MODEL", "nomic-embed-text"),
            base_url=os.environ.get("VIRA_OLLAMA_URL", "http://localhost:11434"),
        )
    else:
        _provider = HashedEmbeddingProvider()
    return _provider


def cosine_any(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(size))
