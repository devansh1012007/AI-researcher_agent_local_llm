"""Centralized configuration.

One YAML file controls everything. Defaults are safe for a laptop.
Config precedence: defaults < YAML file < environment overrides (GAR_ prefix).
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from pydantic import BaseModel, Field

SUPPORTED_LLM_PROVIDERS: frozenset[str] = frozenset(
    {"mock", "ollama", "openai_compatible", "llama_cpp"}
)


class LLMRoleConfig(BaseModel):
    provider: str = "mock"  # mock | ollama | openai_compatible | llama_cpp
    model: str = "mock-model"
    base_url: str = ""
    api_key: str = ""  # for local servers that want any non-empty key
    temperature: float = 0.1
    max_tokens: int = 2048
    context_tokens: int = 8000
    timeout_seconds: float = 120.0

    def __init__(self, **data: Any):
        super().__init__(**data)
        self.validate_provider()

    def validate_provider(self) -> None:
        p = (self.provider or "").strip()
        if p not in SUPPORTED_LLM_PROVIDERS:
            supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
            raise ValueError(
                f"Unknown LLM provider {self.provider!r}; supported providers: {supported}"
            )


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


# Decision: one shared, FAIL-CLOSED predicate decides what counts as a
# loopback bind address.
# Why: the server (which binds) and the API (which authorises) must agree, or
# the token requirement silently disappears. They disagreed once: the CLI bound
# `--host` while the app read the configured host, so `research serve --host
# 0.0.0.0` served the whole API unauthenticated.
# Constraint: anything that is not PROVABLY loopback counts as external, so an
# unusual host string can never switch auth off. `0.0.0.0` and `::` are
# wildcards, not loopback.
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost."})


def is_loopback_host(host: str) -> bool:
    """True only for addresses that provably stay on this machine.

    Accepts loopback IPv4 (127.0.0.0/8), loopback IPv6 (::1) and the
    `localhost` name — the name is an operator-trusted alias, not a proof
    (a hosts entry could point it off-loopback). Everything else — a hostname,
    a LAN address, a wildcard bind, an exotic numeric form — is treated as
    external, so the strict direction is always the safe one.
    """
    h = (host or "").strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if h in _LOOPBACK_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(h)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            return False
        return ip.is_loopback
    except ValueError:
        return False


class McpConfig(BaseModel):
    enabled: bool = True


class SecurityConfig(BaseModel):
    # Decision: default False. `local_only=True` forces LOCAL_ONLY in
    # `effective_environment()` (fail-closed privacy gate: no network
    # providers are constructed under LOCAL_ONLY). The default must stay
    # False so `AppConfig()` (mode: local) keeps resolving to HYBRID —
    # today's behaviour — and existing tests that build the default
    # registry from `AppConfig()` still register providers. Operators opt
    # into strict local-only via `security.local_only: true` in gar.yaml.
    local_only: bool = False            # spec #100 environment modes
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
    mode: str = "local"                # offline | local | online (spec #100)
    profile: str = "balanced"          # minimal | balanced | high_memory | cpu_only | offline (#152)
    scheduler: SchedulerSection = Field(default_factory=SchedulerSection)
    api: ApiConfig = Field(default_factory=ApiConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    experiments: ExperimentsConfig = Field(default_factory=ExperimentsConfig)

    def effective_environment(self) -> str:
        """Resolve LOCAL_ONLY/HYBRID/ONLINE from mode + privacy switches.

        Input vocabulary: ``offline`` | ``local`` | ``online``.
        Mapping: ``offline`` -> LOCAL_ONLY (zero non-loopback egress),
        ``local`` -> HYBRID (loopback LLM + network retrieval, today's
        behaviour with a truthful label), ``online`` -> ONLINE.
        ``privacy_mode: true`` and ``local_only: true`` each force
        LOCAL_ONLY. An unknown mode resolves to LOCAL_ONLY and logs a loud
        error - fail closed. Also honours data_classification == 'LOCAL_ONLY'.
        """
        import logging

        log = logging.getLogger(__name__)
        if self.security.privacy_mode:
            return "LOCAL_ONLY"
        if self.security.local_only:
            log.info(
                "security.local_only is true: resolving environment to "
                "LOCAL_ONLY (fail closed; no network providers)",
            )
            return "LOCAL_ONLY"
        if (self.security.data_classification or "").upper() == "LOCAL_ONLY":
            return "LOCAL_ONLY"
        resolved = {
            "offline": "LOCAL_ONLY",
            "local": "HYBRID",
            "online": "ONLINE",
        }.get(self.mode.lower())
        if resolved is None:
            log.error(
                "unknown platform.mode %r: resolving to LOCAL_ONLY (fail closed). "
                "Valid modes: offline, local, online",
                self.mode,
            )
            return "LOCAL_ONLY"
        return resolved

    def apply_profile(self, resources: ResourceConfig | None = None) -> None:
        """Resource profiles (spec #152): named presets that lower limits."""
        llm_small_cap = max(1, resources.max_parallel_llm_tasks) if resources else 2
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
        if resources is not None and resources.max_parallel_llm_tasks != 1:
            self.scheduler.profile_caps.setdefault("LLM_SMALL", llm_small_cap)
            self.scheduler.profile_caps.setdefault("LLM_LARGE", max(1, resources.max_parallel_llm_tasks))
        overrides = profiles.get(self.profile)
        if not overrides:
            return
        for key, val in overrides.items():
            setattr(self.scheduler, key, val)


def _unwrap_optional(ann: Any) -> Any:
    origin = get_origin(ann)
    if origin is None:
        return ann
    args = [a for a in get_args(ann) if a is not type(None)]
    if len(args) == 1 and len(get_args(ann)) > 1:
        return args[0]
    return ann


def _coerce_env_value(raw: str, ann: Any, env_name: str, field_path: str) -> Any:
    target = _unwrap_optional(ann)
    origin = get_origin(target) or target
    if target is bool:
        low = raw.strip().lower()
        if low in {"1", "true", "yes"}:
            return True
        if low in {"0", "false", "no"}:
            return False
        raise ValueError(
            f"Invalid env override for {env_name} ({field_path}): expected boolean (true/false/1/0)"
        )
    if target is int:
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid env override for {env_name} ({field_path}): expected int"
            ) from exc
    if target is float:
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid env override for {env_name} ({field_path}): expected float"
            ) from exc
    if origin in (list, tuple, dict):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in env override {env_name} ({field_path}): expected {origin.__name__}"
            ) from exc
        if origin is list:
            if not isinstance(parsed, list):
                raise ValueError(
                    f"Invalid env override {env_name} ({field_path}): expected JSON list, got {type(parsed).__name__}"
                )
            return parsed
        if origin is tuple:
            if not isinstance(parsed, list):
                raise ValueError(
                    f"Invalid env override {env_name} ({field_path}): expected JSON array for tuple, got {type(parsed).__name__}"
                )
            return tuple(parsed)
        if origin is dict:
            if not isinstance(parsed, dict):
                raise ValueError(
                    f"Invalid env override {env_name} ({field_path}): expected JSON object for dict, got {type(parsed).__name__}"
                )
            return parsed
    return raw


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
        cfg.platform.apply_profile(cfg.resources)
        return cfg

    def apply_env_overrides(self) -> None:
        """GAR_SECTION__KEY=value overrides, e.g. GAR_MODELS__EXTRACTOR__PROVIDER=ollama."""

        def _walk(model: BaseModel, prefix: str) -> None:
            for name, field in type(model).model_fields.items():
                key = f"{prefix}{name}".upper()
                sub = getattr(model, name)
                env_name = "GAR_" + key.replace(".", "__")
                if isinstance(sub, BaseModel):
                    _walk(sub, key + "__")
                elif env_name in os.environ:
                    raw = os.environ[env_name]
                    ann = field.annotation
                    coerced = _coerce_env_value(raw, ann, env_name, f"{prefix}{name}")
                    setattr(model, name, coerced)
                    if isinstance(model, LLMRoleConfig) and name == "provider":
                        model.validate_provider()

        _walk(self, "")
