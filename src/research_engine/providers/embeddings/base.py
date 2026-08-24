"""Embedding provider abstraction.

Optional by design (spec #45): the engine functions fully without embeddings.
Implementations:
  - OllamaEmbeddingProvider: local ollama embed models (e.g. nomic-embed-text)
  - OpenAICompatibleEmbeddingProvider: any /v1/embeddings server
  - HashingEmbeddingProvider: deterministic feature-hashing fallback (no model,
    no network) - weak semantics but stable, offline, and useful for tests.
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

import httpx


class EmbeddingProvider(ABC):
    name = "base"
    dim = 0

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic bag-of-words hashing embedding.

    Captures lexical overlap, not deep semantics. Good enough to demonstrate and
    test the semantic-retrieval path with zero dependencies; swap for a real
    embedding model when one is available locally.
    """

    name = "hashing"

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _bucket(self, token: str, salt: int = 0) -> int:
        h = hashlib.md5(f"{salt}:{token}".encode()).hexdigest()
        return int(h[:8], 16) % self.dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = [t for t in text.lower().split() if len(t) > 1]
        for i, tok in enumerate(tokens):
            idx = self._bucket(tok)
            sign = 1.0 if int(hashlib.md5(tok.encode()).hexdigest()[8], 16) % 2 else -1.0
            vec[idx] += sign * (1.0 + 1.0 / math.sqrt(i + 1))
            # add char-trigram buckets for robustness to morphology
            for j in range(len(tok) - 2):
                vec[self._bucket(tok[j:j+3], salt=1)] += 0.3
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def is_available(self) -> bool:
        return True


class OllamaEmbeddingProvider(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str = "nomic-embed-text",
                 base_url: str = "http://localhost:11434", timeout: float = 60.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.dim = 768  # nomic-embed-text default; verified on first call

    def embed(self, text: str) -> list[float]:
        resp = httpx.post(f"{self.base_url}/api/embeddings",
                          json={"model": self.model, "prompt": text[:4000]},
                          timeout=self.timeout)
        resp.raise_for_status()
        v = resp.json()["embedding"]
        self.dim = len(v)
        return v

    def is_available(self) -> bool:
        try:
            httpx.get(f"{self.base_url}/api/tags", timeout=2.0)
            return True
        except httpx.HTTPError:
            return False


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai_compatible"

    def __init__(self, model: str, base_url: str = "http://localhost:8000/v1",
                 api_key: str = "", timeout: float = 60.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.dim = 0

    def embed(self, text: str) -> list[float]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = httpx.post(f"{self.base_url}/embeddings", json={"model": self.model,
                          "input": text[:6000]}, headers=headers or None,
                          timeout=self.timeout)
        resp.raise_for_status()
        v = resp.json()["data"][0]["embedding"]
        self.dim = len(v)
        return v

    def is_available(self) -> bool:
        try:
            httpx.get(self.base_url, timeout=2.0)
            return True
        except httpx.HTTPError:
            return False


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (na * nb)
