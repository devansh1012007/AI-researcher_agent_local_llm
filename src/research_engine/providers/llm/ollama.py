"""Ollama provider via /api/chat."""
from __future__ import annotations

import httpx
from urllib.parse import urlparse

from research_engine.core.http_policy import EgressPolicy
from research_engine.providers.llm.base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, cfg, policy: EgressPolicy | None = None):
        super().__init__(cfg)
        self.policy = policy

    def _require(self, host: str, what: str) -> None:
        if self.policy is not None:
            self.policy.require(host, what)

    def _raw_complete(self, system: str, user: str) -> str:
        base = (self.cfg.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._require(urlparse(base).hostname or "", "ollama chat")
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.cfg.temperature,
                "num_predict": self.cfg.max_tokens,
                "num_ctx": self.cfg.context_tokens,
            },
        }
        try:
            resp = httpx.post(f"{base}/api/chat", json=payload,
                              timeout=self.cfg.timeout_seconds)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except (httpx.HTTPError, KeyError) as exc:
            raise LLMError(f"ollama call failed: {exc}") from exc

    def is_available(self) -> bool:
        try:
            base = (self.cfg.base_url or self.DEFAULT_BASE_URL).rstrip("/")
            self._require(urlparse(base).hostname or "", "ollama tags")
            httpx.get(f"{base}/api/tags", timeout=2.0)
            return True
        except httpx.HTTPError:
            return False
