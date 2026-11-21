"""Role-based model routing.

extractor  -> small fast model for chunk-level extraction
reasoning  -> planner / gap analysis / contradiction detection
synthesis  -> final report writing
Phase 1 may point all three roles at the same physical model.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from research_engine.core.config import AppConfig, LLMRoleConfig, SUPPORTED_LLM_PROVIDERS
from research_engine.core.http_policy import build_egress_policy
from research_engine.providers.llm.base import LLMProvider, MockProvider
from research_engine.providers.llm.ollama import OllamaProvider
from research_engine.providers.llm.openai_compat import LlamaCppProvider, OpenAICompatibleProvider

if TYPE_CHECKING:
    from research_engine.core.http_policy import EgressPolicy

log = logging.getLogger(__name__)

_PROVIDERS = {
    "mock": MockProvider,
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "llama_cpp": LlamaCppProvider,
}


def build_provider(cfg: LLMRoleConfig, policy: EgressPolicy | None = None) -> LLMProvider:
    # P1-1: never fall back silently to MockProvider on an unknown provider name.
    cls = _PROVIDERS.get(cfg.provider)
    if cls is None:
        supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
        raise ValueError(
            f"Unknown LLM provider {cfg.provider!r}; supported providers: {supported}"
        )
    provider = cls(cfg)
    # Deliver the egress policy to the constructed provider. Stored as a dynamic
    # instance attribute (rather than a constructor kwarg) so `build_provider(cfg)`
    # with `policy=None` (the default, used by existing callers) is completely
    # unchanged: `MockProvider` (llm/base.py, outside this write-set) does not
    # accept a `policy` kwarg, and constructor injection `cls(cfg, policy=...)`
    # would raise `TypeError` for it. Providers built via `ModelRouter` always
    # receive a resolved `EgressPolicy` (non-None) through this attribute.
    if policy is not None:
        setattr(provider, "policy", policy)
    return provider


class ModelRouter:
    def __init__(self, app_cfg: AppConfig):
        self.app_cfg = app_cfg
        self.policy = build_egress_policy(app_cfg)
        self._cache: dict[str, LLMProvider] = {}
        self.total_calls = 0
        # Validate every role at construction, not only when the first request
        # happens to touch it. This makes bad production configuration fail at
        # startup instead of halfway through a research run.
        for role in ("extractor", "reasoning", "synthesis"):
            role_cfg: LLMRoleConfig = getattr(self.app_cfg.models, role)
            role_cfg.validate_provider()
            if role_cfg.provider == "mock" and not self.app_cfg.models.allow_mock:
                raise ValueError(
                    "MockProvider is disabled for normal runs; set "
                    "models.allow_mock: true only for an explicit offline/test profile"
                )
        self.run_metadata = {
            role: {
                "provider": getattr(self.app_cfg.models, role).provider,
                "model": getattr(self.app_cfg.models, role).model,
                "mock": getattr(self.app_cfg.models, role).provider == "mock",
            }
            for role in ("extractor", "reasoning", "synthesis")
        }
        if any(item["mock"] for item in self.run_metadata.values()):
            log.warning("explicit MockProvider configuration enabled: %s", self.run_metadata)

    def for_role(self, role: str) -> LLMProvider:
        if role not in self._cache:
            role_cfg: LLMRoleConfig = getattr(self.app_cfg.models, role)
            self._cache[role] = build_provider(role_cfg, self.policy)
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
