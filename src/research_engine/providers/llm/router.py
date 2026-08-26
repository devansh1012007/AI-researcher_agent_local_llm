"""Role-based model routing.

extractor  -> small fast model for chunk-level extraction
reasoning  -> planner / gap analysis / contradiction detection
synthesis  -> final report writing
Phase 1 may point all three roles at the same physical model.
"""
from __future__ import annotations

import logging

from research_engine.core.config import AppConfig, LLMRoleConfig
from research_engine.providers.llm.base import LLMProvider, MockProvider
from research_engine.providers.llm.ollama import OllamaProvider
from research_engine.providers.llm.openai_compat import LlamaCppProvider, OpenAICompatibleProvider

log = logging.getLogger(__name__)

_PROVIDERS = {
    "mock": MockProvider,
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "llama_cpp": LlamaCppProvider,
}


def build_provider(cfg: LLMRoleConfig) -> LLMProvider:
    cls = _PROVIDERS.get(cfg.provider)
    if cls is None:
        log.warning("unknown provider %r; falling back to mock", cfg.provider)
        return MockProvider(cfg)
    return cls(cfg)


class ModelRouter:
    def __init__(self, app_cfg: AppConfig):
        self.app_cfg = app_cfg
        self._cache: dict[str, LLMProvider] = {}

    def for_role(self, role: str) -> LLMProvider:
        if role not in self._cache:
            role_cfg: LLMRoleConfig = getattr(self.app_cfg.models, role)
            inner = build_provider(role_cfg)
            # Phase 6 §24: single telemetry choke point — every production
            # LLM call is observed (provider/model/role/latency/schema).
            from research_engine.providers.llm.telemetry import (
                wrap_for_telemetry)
            self._cache[role] = wrap_for_telemetry(inner, role, role_cfg)
            log.info("router: role=%s -> %s/%s", role, role_cfg.provider, role_cfg.model)
        return self._cache[role]

    @property
    def extractor(self) -> LLMProvider:
        return self.for_role("extractor")

    @property
    def reasoning(self) -> LLMProvider:
        return self.for_role("reasoning")

    @property
    def synthesis(self) -> LLMProvider:
        return self.for_role("synthesis")
