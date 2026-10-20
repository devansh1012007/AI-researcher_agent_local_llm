"""P0-04 end-to-end: a search-provider outage must never be reported as
CONVERGED research.

The unit tests in test_convergence_semantics.py feed the analyzer a
hand-built stats dict, so they say nothing about whether the production
wiring can ever produce a non-zero failure count. This file drives the REAL
chain: a provider that raises → the retrieval worker records the failure →
the orchestrator counts it → the convergence decision sees it.
"""
from __future__ import annotations

import pytest

from research_engine.models.enums import StopReason


def _ddg():
    from research_engine.providers.search.duckduckgo import DuckDuckGoProvider
    return DuckDuckGoProvider(timeout=1)


def _searxng():
    from research_engine.providers.search.duckduckgo import SearxngProvider
    return SearxngProvider("http://127.0.0.1:1", timeout=1)


def _openalex():
    from research_engine.providers.academic.openalex import OpenAlexProvider
    return OpenAlexProvider(timeout=1)


def _arxiv():
    from research_engine.providers.academic.arxiv import ArxivProvider
    return ArxivProvider(timeout=1)


def _crossref():
    from research_engine.providers.academic.crossref import CrossrefProvider
    return CrossrefProvider(timeout=1)


def _semantic_scholar():
    from research_engine.providers.academic.semantic_scholar import (
        SemanticScholarProvider,
    )
    return SemanticScholarProvider(timeout=1)


def _registry(*, fail: bool, hits: int = 3):
    from conftest import FakeAcademicProvider, FakeSearchProvider
    from research_engine.pipeline.routing import ProviderRegistry
    reg = ProviderRegistry()
    reg.register_search("web", FakeSearchProvider(hits_per_query=hits, fail=fail))
    for name in ("openalex", "arxiv", "crossref", "semantic_scholar"):
        reg.register_academic(name, FakeAcademicProvider(fail=fail))
    return reg


def _orchestrator(cfg, registry, question: str):
    from conftest import OfflineOrchestrator
    from research_engine.core.ids import project_id_from_question
    from research_engine.models.project import ResearchProject
    project = ResearchProject(id=project_id_from_question(question),
                              question_raw=question, mode="academic")
    return OfflineOrchestrator(cfg, project, registry)


class TestSearchFailureIsRecorded:
    def test_a_failed_query_is_marked_failed_on_the_query_row(self, cfg):
        """The failure is persisted, not flattened into an empty result."""
        orch = _orchestrator(cfg, _registry(fail=True), "record the failure please")
        orch.run()
        queries = orch.repos.queries.all(orch.project.id)
        assert queries, "no query rows were persisted"
        failed = [q for q in queries if q.failed]
        assert failed, "the provider outage was not recorded on any query"
        assert failed[0].failure_reason, "the failure reason was not recorded"

    def test_a_successful_but_empty_search_is_not_a_failure(self, cfg):
        """A search that succeeded and found nothing is NOT a failure.

        This is the distinction the old code collapsed: both cases produced
        an empty result list.
        """
        orch = _orchestrator(cfg, _registry(fail=False, hits=0),
                             "an empty search is not a failure")
        orch.run()
        queries = orch.repos.queries.all(orch.project.id)
        assert queries, "no query rows were persisted"
        assert not [q for q in queries if q.failed], (
            "a search that returned no results was recorded as a failure"
        )

    def test_an_unconfigured_provider_is_not_a_failure(self, cfg):
        """Offline mode must not look like a provider outage.

        A provider that was never registered is a deliberate configuration
        state (`web_provider: none`), not a failure. Counting it as one
        would report an intentional offline run as degraded.
        """
        from research_engine.pipeline.routing import ProviderRegistry
        orch = _orchestrator(cfg, ProviderRegistry(),
                             "no providers configured is not an outage")
        orch.run()
        queries = orch.repos.queries.all(orch.project.id)
        assert not [q for q in queries if q.failed], (
            "an unconfigured provider was recorded as a failure"
        )
        assert orch.project.stop_reason != StopReason.PROVIDER_DEGRADED, (
            "an offline run was reported as a provider outage"
        )


class TestProviderContract:
    """INV-012: the provider wrappers RAISE on failure.

    Before this, every provider swallowed the error and returned [], so the
    failure was destroyed one layer above the code that needed to know
    about it.
    """

    def test_duckduckgo_raises_when_every_attempt_fails(self, monkeypatch):
        import httpx
        import pytest
        from research_engine.providers.search.base import SearchProviderError
        from research_engine.providers.search.duckduckgo import DuckDuckGoProvider

        def boom(*a, **k):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "get", boom)
        monkeypatch.setattr(httpx, "post", boom)
        with pytest.raises(SearchProviderError):
            DuckDuckGoProvider(timeout=1).search("anything")

    def test_duckduckgo_returns_empty_for_a_served_page_with_no_hits(self, monkeypatch):
        """A 200 response with no results is NOT a failure — it is empty."""
        import httpx
        from research_engine.providers.search.duckduckgo import DuckDuckGoProvider

        class _Resp:
            status_code = 200
            text = "<html><body>no results here</body></html>"

        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
        assert DuckDuckGoProvider(timeout=1).search("anything") == []

    @pytest.mark.parametrize("factory", [
        pytest.param(lambda: _ddg(), id="duckduckgo"),
        pytest.param(lambda: _searxng(), id="searxng"),
        pytest.param(lambda: _openalex(), id="openalex"),
        pytest.param(lambda: _arxiv(), id="arxiv"),
        pytest.param(lambda: _crossref(), id="crossref"),
        pytest.param(lambda: _semantic_scholar(), id="semantic_scholar"),
    ])
    def test_every_in_tree_provider_raises_on_a_transport_error(self, monkeypatch, factory):
        """EVERY provider honours the contract — not just DuckDuckGo.

        Each provider used to swallow the transport error and return [], so a
        total outage was invisible. This is the contract test that makes a
        silent regression in any one of them fail.
        """
        import httpx
        from research_engine.providers.search.base import SearchProviderError

        def boom(*a, **k):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "get", boom)
        monkeypatch.setattr(httpx, "post", boom)
        with pytest.raises(SearchProviderError):
            factory().search("anything")

    def test_a_rate_limit_is_a_failure_not_an_empty_result(self, monkeypatch):
        """HTTP 429 means the search did not happen: that is a failure."""
        import httpx
        from research_engine.providers.search.base import SearchProviderError
        from research_engine.providers.academic.semantic_scholar import (
            SemanticScholarProvider,
        )

        class _Resp:
            status_code = 429
            text = ""

        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
        with pytest.raises(SearchProviderError):
            SemanticScholarProvider(timeout=1).search("anything")

    def test_a_failing_provider_is_reported_not_flattened(self, cfg):
        """The worker records the failure; it does not turn it into []."""
        orch = _orchestrator(cfg, _registry(fail=True), "the failure must be reported")
        orch.run()
        failed = [q for q in orch.repos.queries.all(orch.project.id) if q.failed]
        assert failed, "the provider failure was flattened into an empty result"
        assert "outage" in failed[0].failure_reason


class TestSearchOutageIsNotConvergence:
    def test_total_search_outage_is_never_converged(self, cfg):
        """The headline defect: a total outage reported as CONVERGED."""
        orch = _orchestrator(cfg, _registry(fail=True),
                             "does a provider outage get reported as converged")
        orch.run()
        stop = orch.project.stop_reason
        assert stop == StopReason.PROVIDER_DEGRADED, (
            f"a total search outage was reported as {stop}, not PROVIDER_DEGRADED"
        )
        assert stop != StopReason.CONVERGED
