"""Shared fixtures for offline testing."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

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

    def __new__(cls, cfg, project, registry=None, llm=None, fail_urls=None):
        from research_engine.core.orchestrator import Orchestrator

        class _Impl(Orchestrator):
            def _make_document_processor(self):
                from research_engine.pipeline.documents import DocumentProcessor
                return DocumentProcessor(self.cfg, self.repos, self.ws,
                                         transport=make_fake_transport(fail_urls=fail_urls or set()))

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
