"""
MemoryOS Embedding Engine.
Supports local Ollama embeddings (nomic-embed-text / bge-m3) with an in-process
deterministic fallback provider for offline execution and testing.
"""

import hashlib
import json
import logging
import math
import os
import re
from typing import List
import httpx

from backend.config import DATA_DIR

logger = logging.getLogger("memoryos.embeddings")

DEFAULT_EMBED_MODEL = os.environ.get("MEMORYOS_EMBED_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_DIMENSION = 768


class LocalFallbackEmbeddingProvider:
    """
    In-process, zero-dependency 768-dimensional normalized dense embedding provider.
    Uses n-gram feature hashing with sublinear term weighting and L2 unit normalization.
    Guarantees deterministic, cosine-searchable dense vectors even when Ollama is stopped.
    """
    def __init__(self, dimension: int = EMBED_DIMENSION):
        self.dimension = dimension

    def embed_query(self, query: str) -> List[float]:
        return self._compute_dense_vector(query)

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        return [self._compute_dense_vector(doc) for doc in documents]

    def _compute_dense_vector(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dimension

        vector = [0.0] * self.dimension
        tokens = [t for t in re.findall(r"\b\w{2,}\b", text.lower()) if t]
        if not tokens:
            return [0.0] * self.dimension

        # Unigrams and bigrams
        terms = list(tokens)
        for i in range(len(tokens) - 1):
            terms.append(f"{tokens[i]}_{tokens[i+1]}")

        # Compute term frequency
        tf = {}
        for term in terms:
            tf[term] = tf.get(term, 0) + 1

        for term, count in tf.items():
            # Hash to dimension slot
            h = int(hashlib.md5(term.encode("utf-8")).hexdigest(), 16)
            slot = h % self.dimension
            sign = 1.0 if ((h >> 3) & 1) == 0 else -1.0
            weight = (1.0 + math.log(count)) * sign
            vector[slot] += weight

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 1e-9:
            vector = [v / norm for v in vector]

        return vector


class OllamaEmbeddingProvider:
    """Connects to local Ollama server for nomic-embed-text or bge-m3 dense embeddings."""
    def __init__(self, model: str = DEFAULT_EMBED_MODEL, base_url: str = OLLAMA_HOST):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.fallback = LocalFallbackEmbeddingProvider(EMBED_DIMENSION)

    def embed_query(self, query: str) -> List[float]:
        res = self.embed_documents([query])
        return res[0] if res else self.fallback.embed_query(query)

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        if not documents:
            return []

        try:
            # 1. Try modern Ollama /api/embed endpoint
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": documents}
                )
                if res.status_code == 200:
                    data = res.json()
                    if "embeddings" in data and len(data["embeddings"]) == len(documents):
                        return data["embeddings"]

                # 2. Try legacy single /api/embeddings in a loop if /api/embed not available
                embeddings: List[List[float]] = []
                for doc in documents:
                    r = client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.model, "prompt": doc}
                    )
                    if r.status_code == 200:
                        embeddings.append(r.json().get("embedding", []))
                    else:
                        raise ValueError(f"Ollama returned {r.status_code}")
                return embeddings
        except Exception as e:
            logger.debug(f"Ollama embedding unavailable ({e}), using in-process embedding fallback.")
            return self.fallback.embed_documents(documents)


_provider_instance = None


def get_embedding_provider():
    """Singleton getter for the active embedding provider."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = OllamaEmbeddingProvider()
    return _provider_instance

