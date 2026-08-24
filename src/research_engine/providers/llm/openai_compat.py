"""OpenAI-compatible provider: works with llama.cpp server, LM Studio, vLLM, etc."""
from __future__ import annotations

import httpx

from research_engine.providers.llm.base import LLMError, LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    DEFAULT_BASE_URL = "http://localhost:8000/v1"

    def _raw_complete(self, system: str, user: str) -> str:
        base = (self.cfg.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        headers = {}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        try:
            resp = httpx.post(f"{base}/chat/completions", json=payload,
                              headers=headers or None, timeout=self.cfg.timeout_seconds)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"openai-compatible call failed: {exc}") from exc


class LlamaCppProvider(OpenAICompatibleProvider):
    """llama.cpp's llama-server exposes the same OpenAI-compatible API."""
    DEFAULT_BASE_URL = "http://localhost:8080/v1"
