"""Ollama provider via /api/chat."""
from __future__ import annotations

import httpx

from research_engine.providers.llm.base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    DEFAULT_BASE_URL = "http://localhost:11434"

    def _raw_complete(self, system: str, user: str) -> str:
        base = (self.cfg.base_url or self.DEFAULT_BASE_URL).rstrip("/")
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
            httpx.get(f"{base}/api/tags", timeout=2.0)
            return True
        except httpx.HTTPError:
            return False
