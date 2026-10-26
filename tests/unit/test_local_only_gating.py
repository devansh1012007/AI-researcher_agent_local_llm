"""LOCAL_ONLY gating tests for `security.local_only` (W6 / T-004).

`security.local_only: true` must force the resolved environment to
``LOCAL_ONLY`` so that `build_default_registry()` returns an empty registry
and no network provider is constructed (privacy guarantee, S2).

``security`` lives under ``platform`` (there is no top-level
``AppConfig.security`` field), so tests configure it via
``platform=PlatformConfig(security=SecurityConfig(local_only=True), ...)``.
"""

from __future__ import annotations

import logging

import pytest

from research_engine.core.config import AppConfig, PlatformConfig, SecurityConfig


def _local_only_cfg(mode: str = "online") -> AppConfig:
    return AppConfig(
        platform=PlatformConfig(
            mode=mode,
            security=SecurityConfig(local_only=True),
        )
    )


def test_local_only_forces_local_only():
    """`local_only=True` forces LOCAL_ONLY regardless of platform.mode."""
    cfg = _local_only_cfg("online")
    assert cfg.platform.effective_environment() == "LOCAL_ONLY"


def test_local_only_forces_local_only_even_in_local_mode():
    """`local_only=True` overrides the default `mode: local` (HYBRID)."""
    cfg = _local_only_cfg("local")
    assert cfg.platform.effective_environment() == "LOCAL_ONLY"


def test_local_only_default_preserves_hybrid():
    """The default `local_only` must not change today's HYBRID default.

    `local_only` defaults to False precisely so `AppConfig()` (mode: local)
    keeps resolving to HYBRID and the default registry still registers
    providers. This guards against silently darkening the default install.
    """
    cfg = AppConfig()
    assert cfg.platform.security.local_only is False
    assert cfg.platform.effective_environment() == "HYBRID"


def test_unknown_mode_resolves_to_local_only(caplog):
    """An unknown platform.mode resolves to LOCAL_ONLY and logs an error."""
    cfg = AppConfig(platform=PlatformConfig(mode="not_a_real_mode"))
    with caplog.at_level(logging.ERROR, logger="research_engine.core.config"):
        env = cfg.platform.effective_environment()
    assert env == "LOCAL_ONLY"
    assert "unknown platform.mode" in caplog.text


def test_local_only_registry_is_empty():
    """LOCAL_ONLY yields an empty default registry (no network providers)."""
    from research_engine.core.orchestrator import build_default_registry

    cfg = _local_only_cfg("local")
    reg = build_default_registry(cfg)
    assert reg.get_any("web") is None
    for name in ("openalex", "crossref", "arxiv", "semantic_scholar"):
        assert reg.get_any(name) is None
