"""Shared fixtures for offline testing."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

# The suite must be HERMETIC: it cannot depend on the developer's working
# directory. `AppConfig.load()` reads a CWD-relative `gar.yaml`, and the
# shipped `gar.example.yaml` selects the `ollama` provider — so as soon as
# that file existed (the documented `scripts/setup_dev.sh` copies it there),
# the suite reached for a real local LLM and failed with "connection refused"
# instead of exercising the code under test.
# Env overrides have the highest precedence in `AppConfig.load()`, so these
# neutralise every config load, including the ones buried in production code
# (`services/context.py`, `platform/job_runners.py`, ...).
# The embeddings provider is pinned too: left alone, an ambient
# `embeddings.provider: ollama` made the suite attempt a live HTTP call to
# localhost:11434 (it "passed" only because the provider swallows the error).
# NOTE: only string-valued settings are pinned here. The env walker cannot
# coerce a list (a list field becomes the raw string) — see FIX_PLAN P1-10,
# which is why `search.academic_providers` is cleared per-fixture instead.
os.environ["GAR_MODELS__EXTRACTOR__PROVIDER"] = "mock"
os.environ["GAR_MODELS__REASONING__PROVIDER"] = "mock"
os.environ["GAR_MODELS__SYNTHESIS__PROVIDER"] = "mock"
os.environ["GAR_SEARCH__WEB_PROVIDER"] = "none"
os.environ["GAR_EMBEDDINGS__PROVIDER"] = "hashing"
# Pin LOCAL_ONLY off so the suite stays hermetic regardless of an ambient
# gar.yaml (AGENTS.md §3). W2 C09 egress enforcement consults the policy on
# every fetch; without this pin, a developer's gar.yaml with
# platform.security.local_only: true would block offline tests.
os.environ["GAR_SECURITY__LOCAL_ONLY"] = "false"

from fakes import (FakeAcademicProvider, FakeSearchProvider, ScriptedLLM,
                   make_fake_transport)  # noqa: E402

from research_engine.core.config import AppConfig  # noqa: E402
from research_engine.pipeline.routing import ProviderRegistry  # noqa: E402


@pytest.fixture()
def cfg(tmp_path) -> AppConfig:
    c = AppConfig.load()
    c.storage.data_dir = str(tmp_path / "data")
    c.research.max_iterations = 2
    c.research.max_queries_per_iteration = 4
    c.resources.max_parallel_fetches = 2
    c.search.web_provider = "none"
    c.search.academic_providers = []
    return c


@pytest.fixture()
def fake_registry() -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register_search("web", FakeSearchProvider(hits_per_query=3))
    for name in ("openalex", "arxiv", "crossref", "semantic_scholar"):
        reg.register_academic(name, FakeAcademicProvider(n=2))
    return reg


@pytest.fixture()
def scripted_llm() -> ScriptedLLM:
    return ScriptedLLM()


class OfflineOrchestrator:
    """Orchestrator wired to offline fakes (scripted LLM, fake search, fake HTTP)."""

    def __new__(cls, cfg, project, registry=None, llm=None, fail_urls=None,
                startup_mode: bool = False):
        from research_engine.core.orchestrator import Orchestrator

        topics = project.question_raw.split()[:6] if (
            startup_mode or getattr(project, "mode", "") == "startup") else None

        class _Impl(Orchestrator):
            def _make_document_processor(self):
                from research_engine.pipeline.documents import DocumentProcessor
                return DocumentProcessor(self.cfg, self.repos, self.ws,
                                         transport=make_fake_transport(
                                             fail_urls=fail_urls or set(),
                                             startup_topics=topics))

        orch = _Impl(cfg, project, registry)
        shared = llm if llm is not None else ScriptedLLM()
        reasoning = ScriptedLLM() if shared is None else shared
        orch.router._cache = {"extractor": shared, "reasoning": reasoning, "synthesis": None}
        orch._offline_llm = shared
        return orch


@pytest.fixture()
def make_orchestrator(cfg, fake_registry):
    """factory(question, mode='academic', llm=None, fail_urls=None) -> orchestrator."""
    def factory(question, mode="academic", llm=None, fail_urls=None):
        from research_engine.core.ids import project_id_from_question
        from research_engine.models.project import ResearchProject
        project = ResearchProject(id=project_id_from_question(question),
                                  question_raw=question, mode=mode)
        return OfflineOrchestrator(cfg, project, fake_registry, llm=llm, fail_urls=fail_urls)
    return factory


@pytest.fixture()
def platform_ctx(tmp_path):
    """Isolated ServiceContext on a temp data dir; network disabled so jobs
    stay offline (fake-free path: providers configured to 'none')."""
    from research_engine.services.context import ServiceContext
    c = AppConfig.load()
    c.storage.data_dir = str(tmp_path / "data")
    c.research.max_iterations = 1
    c.search.web_provider = "none"
    c.search.academic_providers = []
    ctx = ServiceContext(cfg=c)
    yield ctx
    ctx.stop_scheduler()
