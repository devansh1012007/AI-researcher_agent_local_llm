"""Centralized configuration.

One YAML file controls everything. Defaults are safe for a laptop.
Config precedence: defaults < YAML file < environment overrides (GAR_ prefix).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMRoleConfig(BaseModel):
    provider: str = "mock"  # mock | ollama | openai_compatible | llama_cpp
    model: str = "mock-model"
    base_url: str = ""
    api_key: str = ""  # for local servers that want any non-empty key
    temperature: float = 0.1
    max_tokens: int = 2048
    context_tokens: int = 8000
    timeout_seconds: float = 120.0


class LLMConfig(BaseModel):
    extractor: LLMRoleConfig = Field(default_factory=LLMRoleConfig)
    reasoning: LLMRoleConfig = Field(default_factory=LLMRoleConfig)
    synthesis: LLMRoleConfig = Field(default_factory=LLMRoleConfig)


class ResearchConfig(BaseModel):
    mode: str = "academic"  # academic | startup
    max_iterations: int = 3
    max_queries_per_iteration: int = 8
    max_documents: int = 50
    max_sources_total: int = 150
    max_llm_calls: int = 300
    max_wall_clock_minutes: int = 60
    min_evidence_per_gap_query: float = 0.05  # convergence signal
    new_evidence_threshold: float = 0.10  # fraction of prior evidence => converged
    duplicate_rate_converged: float = 0.7
    review_gates_enabled: bool = False  # when True, orchestrator pauses at gates


class NetworkConfig(BaseModel):
    timeout_seconds: float = 20.0
    max_retries: int = 3
    backoff_base_seconds: float = 1.5
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 GAR-ResearchBot/0.1"
    )
    respect_robots: bool = True


class ResourceConfig(BaseModel):
    max_parallel_fetches: int = 5
    max_parallel_llm_tasks: int = 1
    max_document_size_mb: float = 10.0
    max_chunk_chars: int = 6000
    chunk_overlap_chars: int = 400
    max_context_chars: int = 24000


class StorageConfig(BaseModel):
    data_dir: str = "research_data"


class EmbeddingsConfig(BaseModel):
    provider: str = "hashing"   # hashing | ollama | openai_compatible | none
    model: str = "nomic-embed-text"
    base_url: str = ""


class SearchConfig(BaseModel):
    web_provider: str = "duckduckgo"  # duckduckgo | searxng | none
    searxng_base_url: str = ""
    results_per_query: int = 10
    academic_providers: list[str] = Field(
        default_factory=lambda: ["openalex", "crossref", "arxiv"]
    )
    semantic_scholar_api_key: str = ""
    cache_ttl_hours: int = 168


class SchedulerSection(BaseModel):
    max_jobs: int = 1                  # concurrent research jobs (laptop reality)
    worker_threads: int = 4
    lease_seconds: float = 120.0
    heartbeat_seconds: float = 15.0
    profile_caps: dict[str, int] = Field(default_factory=dict)


class ApiConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"            # NEVER default to 0.0.0.0 (spec #67)
    port: int = 8000
    auth_token: str = ""               # required when host != 127.0.0.1


class McpConfig(BaseModel):
    enabled: bool = True


class SecurityConfig(BaseModel):
    local_only: bool = True            # spec #100 environment modes
    privacy_mode: bool = False         # spec #99: no external calls at all
    data_classification: str = "INTERNAL"   # PUBLIC|INTERNAL|SENSITIVE|LOCAL_ONLY
    allowed_roots: list[str] = Field(default_factory=list)  # filesystem sandbox (#65)
    redact_secrets_in_logs: bool = True


class ExperimentsConfig(BaseModel):
    enabled: bool = True
    sandbox: bool = True
    timeout_seconds: int = 1800
    memory_mb: int = 4096
    cpu_seconds: int = 1800
    network_enabled: bool = False      # default OFF (spec #37/#45)
    require_human_approval: bool = True


class PlatformConfig(BaseModel):
    mode: str = "local"                # LOCAL_ONLY | HYBRID | ONLINE (spec #100)
    profile: str = "balanced"          # minimal | balanced | high_memory | cpu_only | offline (#152)
    scheduler: SchedulerSection = Field(default_factory=SchedulerSection)
    api: ApiConfig = Field(default_factory=ApiConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    experiments: ExperimentsConfig = Field(default_factory=ExperimentsConfig)

    def effective_environment(self) -> str:
        """Resolve LOCAL_ONLY/HYBRID/ONLINE from mode + privacy switches."""
        if self.security.privacy_mode:
            return "LOCAL_ONLY"
        return {"local": "LOCAL_ONLY", "hybrid": "HYBRID",
                "online": "ONLINE"}.get(self.mode.lower(), "HYBRID")

    def apply_profile(self) -> None:
        """Resource profiles (spec #152): named presets that lower limits."""
        profiles = {
            "minimal": {"max_jobs": 1, "worker_threads": 2,
                        "profile_caps": {"NETWORK_LIGHT": 2, "LLM_SMALL": 1,
                                         "CPU_LIGHT": 1}},
            "cpu_only": {"worker_threads": 3,
                         "profile_caps": {"LLM_LARGE": 0, "LLM_SMALL": 1}},
            "offline": {"max_jobs": 1, "worker_threads": 2,
                        "profile_caps": {"NETWORK_LIGHT": 0, "NETWORK_HEAVY": 0}},
            "high_memory": {},
            "balanced": {},
        }
        overrides = profiles.get(self.profile)
        if not overrides:
            return
        for key, val in overrides.items():
            setattr(self.scheduler, key, val)


class AppConfig(BaseModel):
    models: LLMConfig = Field(default_factory=LLMConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    platform: PlatformConfig = Field(default_factory=PlatformConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AppConfig":
        data: dict[str, Any] = {}
        candidates = [Path(path)] if path else [Path("gar.yaml"), Path("gar.yml"), Path("config/gar.yaml")]
        cfg_file = next((c for c in candidates if c.exists()), None)
        if cfg_file:
            data = yaml.safe_load(cfg_file.read_text()) or {}
        cfg = cls.model_validate(data)
        cfg.apply_env_overrides()
        cfg.platform.apply_profile()
        return cfg

    def apply_env_overrides(self) -> None:
        """GAR_SECTION__KEY=value overrides, e.g. GAR_MODELS__EXTRACTOR__PROVIDER=ollama."""

        def _walk(model: BaseModel, prefix: str) -> None:
            for name, field in type(model).model_fields.items():
                key = f"{prefix}{name}".upper()
                env_key = key.replace("__", "__")
                sub = getattr(model, name)
                env_name = "GAR_" + key.replace(".", "__")
                if isinstance(sub, BaseModel):
                    _walk(sub, key + "__")
                elif env_name in os.environ:
                    raw = os.environ[env_name]
                    ann = field.annotation
                    try:
                        if ann is bool:
                            setattr(model, name, raw.lower() in {"1", "true", "yes"})
                        elif ann is int:
                            setattr(model, name, int(raw))
                        elif ann is float:
                            setattr(model, name, float(raw))
                        else:
                            setattr(model, name, raw)
                    except ValueError:
                        raise ValueError(f"Invalid env override {env_name}={raw!r} for {prefix}{name}")

        _walk(self, "")
