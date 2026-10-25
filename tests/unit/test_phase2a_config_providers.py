"""Tests for Phase 2A configuration & provider contracts (P1-1, P1-7, P1-10, P1-12)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from research_engine.core.budget import Budget
from research_engine.core.config import AppConfig, LLMRoleConfig
from research_engine.models.project import ResearchProject
from research_engine.providers.llm.base import MockProvider
from research_engine.providers.llm.ollama import OllamaProvider
from research_engine.providers.llm.openai_compat import (
    LlamaCppProvider,
    OpenAICompatibleProvider,
)
from research_engine.providers.llm.router import build_provider


class TestP1_1_UnknownProviderFailsExplicitly:
    def test_unknown_provider_in_role_config_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider 'ollamma'"):
            LLMRoleConfig(provider="ollamma", model="qwen2.5:7b")

    def test_build_provider_unknown_raises_without_silent_mock_fallback(self):
        cfg = LLMRoleConfig(provider="mock", model="m")
        object.__setattr__(cfg, "provider", "ollamma")
        with pytest.raises(ValueError, match="Unknown LLM provider 'ollamma'"):
            build_provider(cfg)

    def test_supported_providers_map_to_expected_classes(self):
        assert isinstance(build_provider(LLMRoleConfig(provider="mock")), MockProvider)
        assert isinstance(build_provider(LLMRoleConfig(provider="ollama")), OllamaProvider)
        assert isinstance(
            build_provider(LLMRoleConfig(provider="openai_compatible")),
            OpenAICompatibleProvider,
        )
        assert isinstance(build_provider(LLMRoleConfig(provider="llama_cpp")), LlamaCppProvider)

    def test_doctor_reports_configuration_error_on_invalid_provider(self, tmp_path, monkeypatch):
        import research_engine.cli.main as cli
        bad_cfg = tmp_path / "bad_gar.yaml"
        bad_cfg.write_text("models:\n  reasoning:\n    provider: ollamma\n")
        monkeypatch.delenv("GAR_MODELS__REASONING__PROVIDER", raising=False)
        ns = type("A", (), {"config": str(bad_cfg)})()
        rc = cli.cmd_doctor(ns)
        assert rc == 1


class TestP1_7_ExampleConfigAndWiredKnobs:
    def test_example_config_loads_and_has_no_top_level_mode(self):
        import yaml
        example_path = Path(__file__).resolve().parents[2] / "gar.example.yaml"
        raw = yaml.safe_load(example_path.read_text())
        assert "mode" not in raw, "top-level mode is ignored; research.mode is the field"
        assert raw["research"]["mode"] == "academic"
        cfg = AppConfig.load(example_path)
        assert cfg.research.mode == "academic"

    def test_max_sources_total_wired_into_budget(self):
        cfg = AppConfig.load()
        cfg.research.max_sources_total = 5
        proj = ResearchProject(id="p_src", question_raw="q")
        b = Budget(cfg, proj)
        assert b.sources_left() == 5
        b.spend_sources(5)
        assert b.sources_left() == 0
        assert b.exhausted() == "sources"

    def test_scheduler_config_from_app_config_wires_lease_and_heartbeat(self):
        from research_engine.platform.scheduler import SchedulerConfig
        cfg = AppConfig.load()
        cfg.platform.scheduler.lease_seconds = 45.0
        cfg.platform.scheduler.heartbeat_seconds = 7.5
        scfg = SchedulerConfig.from_app_config(cfg)
        assert scfg.lease_seconds == 45.0
        assert scfg.heartbeat_seconds == 7.5


class TestP1_10_StructuredEnvOverrides:
    def test_empty_json_list_override(self, monkeypatch):
        monkeypatch.setenv("GAR_SEARCH__ACADEMIC_PROVIDERS", "[]")
        cfg = AppConfig.load()
        assert cfg.search.academic_providers == []
        assert isinstance(cfg.search.academic_providers, list)

    def test_single_provider_json_list_override(self, monkeypatch):
        monkeypatch.setenv("GAR_SEARCH__ACADEMIC_PROVIDERS", '["openalex"]')
        cfg = AppConfig.load()
        assert cfg.search.academic_providers == ["openalex"]

    def test_dict_override_for_profile_caps(self, monkeypatch):
        monkeypatch.setenv("GAR_PLATFORM__SCHEDULER__PROFILE_CAPS", '{"LLM_LARGE": 2}')
        cfg = AppConfig.load()
        assert cfg.platform.scheduler.profile_caps["LLM_LARGE"] == 2

    def test_invalid_json_for_list_field_raises_without_leaking_secret(self, monkeypatch):
        secret_val = "not-json-supersecret-token"
        monkeypatch.setenv("GAR_SEARCH__ACADEMIC_PROVIDERS", secret_val)
        with pytest.raises(ValueError) as exc_info:
            AppConfig.load()
        msg = str(exc_info.value)
        assert "GAR_SEARCH__ACADEMIC_PROVIDERS" in msg
        assert secret_val not in msg

    def test_scalar_overrides_remain_int_float_bool_str(self, monkeypatch):
        monkeypatch.setenv("GAR_RESEARCH__MAX_ITERATIONS", "7")
        monkeypatch.setenv("GAR_NETWORK__TIMEOUT_SECONDS", "12.5")
        monkeypatch.setenv("GAR_RESEARCH__REVIEW_GATES_ENABLED", "true")
        monkeypatch.setenv("GAR_SEARCH__WEB_PROVIDER", "searxng")
        cfg = AppConfig.load()
        assert cfg.research.max_iterations == 7
        assert cfg.network.timeout_seconds == 12.5
        assert cfg.research.review_gates_enabled is True
        assert cfg.search.web_provider == "searxng"


class TestP1_12_ServeHonorsGlobalConfigFlag:
    def test_serve_uses_config_file_for_host_token_and_port(self, tmp_path):
        import uvicorn
        from fastapi.testclient import TestClient
        import research_engine.cli.main as cli
        from research_engine.services import context as ctx_mod

        cfg_file = tmp_path / "custom_gar.yaml"
        cfg_file.write_text(
            f"storage:\n  data_dir: {str(tmp_path / 'data')!r}\n"
            "platform:\n  api:\n    host: '0.0.0.0'\n    port: 9123\n    auth_token: 'cfg-secret-tok'\n"
        )
        ctx_mod.reset_context()
        captured = {}

        def fake_run(app, **kwargs):
            captured["app"] = app
            captured["kwargs"] = kwargs

        orig_run = uvicorn.run
        uvicorn.run = fake_run
        try:
            ns = type("A", (), {"config": str(cfg_file), "host": None, "port": None})()
            cli.cmd_serve(ns)
            assert captured["kwargs"]["host"] == "0.0.0.0"
            assert captured["kwargs"]["port"] == 9123
            client = TestClient(captured["app"])
            assert client.get("/projects").status_code == 401
            assert client.get("/projects", headers={"X-API-Token": "wrong"}).status_code == 401
            assert client.get("/projects", headers={"X-API-Token": "cfg-secret-tok"}).status_code == 200
        finally:
            uvicorn.run = orig_run
            ctx_mod.reset_context()

    def test_serve_cli_host_override_takes_precedence_over_config_file(self, tmp_path):
        import uvicorn
        from fastapi.testclient import TestClient
        import research_engine.cli.main as cli
        from research_engine.services import context as ctx_mod

        cfg_file = tmp_path / "loopback_gar.yaml"
        cfg_file.write_text(
            f"storage:\n  data_dir: {str(tmp_path / 'data')!r}\n"
            "platform:\n  api:\n    host: '127.0.0.1'\n    port: 8000\n    auth_token: 'override-tok'\n"
        )
        ctx_mod.reset_context()
        captured = {}

        def fake_run(app, **kwargs):
            captured["app"] = app
            captured["kwargs"] = kwargs

        orig_run = uvicorn.run
        uvicorn.run = fake_run
        try:
            ns = type("A", (), {"config": str(cfg_file), "host": "0.0.0.0", "port": 8088})()
            cli.cmd_serve(ns)
            assert captured["kwargs"]["host"] == "0.0.0.0"
            assert captured["kwargs"]["port"] == 8088
            client = TestClient(captured["app"])
            assert client.get("/projects").status_code == 401
            assert client.get("/projects", headers={"X-API-Token": "override-tok"}).status_code == 200
        finally:
            uvicorn.run = orig_run
            ctx_mod.reset_context()
