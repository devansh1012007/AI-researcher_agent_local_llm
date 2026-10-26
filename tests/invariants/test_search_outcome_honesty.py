"""INV-012: a failed retrieval is never reported as an empty one.

The per-leg outcome vocabulary is the audit trail of the retrieval
boundary. Every leg of a route ends in exactly one of four states:

    hits                  the provider was configured and answered
    unconfigured          the provider was never registered (offline mode)
    optional_unconfigured the provider is optional and was not enabled
    failed                the provider was configured and RAISED

Three of the four states were pinned by a test; `failed` was not. A
provider outage could therefore be recorded as a leg that "found
nothing" and the whole suite stayed green - which is exactly the
confusion INV-012 exists to prevent.

This file pins all four states on the PERSISTED query row (not on the
tuple the worker returns, which nothing persisted) and pins the two
neighbouring boundaries the same rule covers: the watcher's provider
classification and the novelty verifier's provider report. It also pins
that the REPORT says which meaning a result count carries - a number
whose meaning changed must not be rendered without its basis.

Fully offline: every provider here is an in-test fake, and the project
storage is a per-test SQLite file under tmp_path.
"""
from __future__ import annotations

from pathlib import Path

from research_engine.pipeline.routing import ProviderRegistry


def _project(tmp_path, question: str, category: str):
    """A per-project store with one branch and one query, wired the way the
    orchestrator wires it."""
    from research_engine.core.ids import project_id_from_question
    from research_engine.models.research import ResearchBranch, SearchQuery
    from research_engine.storage.database import Database
    from research_engine.storage.repositories import Repositories
    from research_engine.storage.workspace import Workspace

    pid = project_id_from_question(question)
    ws = Workspace(str(tmp_path / "data"), pid)
    repos = Repositories(Database(ws.db_path))
    br = ResearchBranch(project_id=pid, category=category, question="pain?")
    br.ensure_id()
    repos.branches.save(br)
    q = SearchQuery(project_id=pid, text="fleet costs", branch=br.id)
    q.ensure_id()
    repos.queries.save(q)
    return pid, repos, q


def _run(cfg, tmp_path, question, category, registry):
    """Run one query through the real retrieval worker; return the persisted
    query row."""
    from research_engine.pipeline.retrieval import RetrievalWorker

    pid, repos, q = _project(tmp_path, question, category)
    worker = RetrievalWorker(cfg, repos, registry)
    worker.execute_queries(pid, [q], budget_left=1)
    row = repos.queries.get(q.id)
    assert row is not None, "the query row was not persisted"
    return row


def _registry(*providers):
    """A registry holding academic providers, given as (name, provider)."""
    reg = ProviderRegistry()
    for name, prov in providers:
        reg.register_academic(name, prov)
    return reg


class TestLegOutcomeVocabulary:
    """The four leg states, asserted on the persisted row."""

    def test_a_failed_provider_is_persisted_as_a_failed_leg(self, cfg, tmp_path):
        """A REGISTERED provider that RAISES must leave a `failed` leg.

        This is the state nothing pinned: recording the outage as
        `{"status": "hits", "hits": 0}` (a leg that found nothing) left
        the whole suite green and made a total outage look like a quiet
        search.
        """
        class Boom:
            def search(self, query, max_results=10):
                raise RuntimeError("simulated outage")

        reg = ProviderRegistry()
        reg.register_search("web", Boom())
        row = _run(cfg, tmp_path, "failed leg outcome", "GENERIC", reg)

        by_leg = {o["leg"]: o for o in row.leg_outcomes}
        assert by_leg["web"]["status"] == "failed", (
            f"a provider outage was recorded as {by_leg['web']['status']!r}: "
            f"{row.leg_outcomes}")
        assert by_leg["web"]["error"], (
            "the failed leg carries no error text, so the outage leaves no "
            "trace beyond the status")
        assert by_leg["web"]["hits"] == 0
        assert row.failed is True, (
            "the failed leg did not mark the query as failed")
        assert row.failure_reason, "the failure reason was not recorded"

    def test_an_unconfigured_provider_is_not_a_failure(self, cfg, tmp_path):
        """A provider that was never registered is a declared state."""
        row = _run(cfg, tmp_path, "unconfigured leg outcome", "METHODS",
                   ProviderRegistry())

        by_leg = {o["leg"]: o for o in row.leg_outcomes}
        assert by_leg["semantic_scholar"]["status"] == "optional_unconfigured"
        assert by_leg["openalex"]["status"] == "unconfigured"
        assert row.failed is False, (
            "an unconfigured provider was recorded as a failure")
        assert row.failure_reason == ""

    def test_a_provider_that_found_nothing_is_a_hit_not_a_failure(self, cfg, tmp_path):
        """A provider that answered with zero hits is NOT an outage."""
        class Empty:
            def search(self, query, max_results=10):
                return []

        reg = ProviderRegistry()
        reg.register_search("web", Empty())
        row = _run(cfg, tmp_path, "empty leg outcome", "GENERIC", reg)

        by_leg = {o["leg"]: o for o in row.leg_outcomes}
        assert by_leg["web"]["status"] == "hits"
        assert by_leg["web"]["hits"] == 0
        assert row.failed is False, (
            "a search that returned nothing was recorded as a failure")


class TestWatcherProviderClassification:
    """The watcher boundary: every provider state lands in exactly one of
    the two lists, and the two lists never overlap."""

    def _runner(self, cfg, registry):
        from research_engine.platform.watchers import WatchRunner

        runner = WatchRunner.__new__(WatchRunner)
        runner.ctx = type("C", (), {"cfg": cfg})()
        runner.registry = registry
        runner._unconfigured = []
        runner._failures = []
        return runner

    def test_every_provider_state_lands_in_exactly_one_list(self, cfg):
        """A working provider, a failing provider and an absent provider
        must be told apart by WHERE they are recorded."""
        class Failing:
            def search(self, query, max_results=10):
                raise RuntimeError("simulated outage")

        reg = ProviderRegistry()
        reg.register_search("web", Failing())
        reg.register_academic("arxiv", Failing())
        runner = self._runner(cfg, reg)
        runner._search("fleet", ["web", "arxiv", "openalex"])

        assert any("simulated outage" in f for f in runner._failures), (
            f"the failing providers were not recorded: {runner._failures}")
        assert "openalex" in runner._unconfigured, (
            f"the absent provider was not recorded: {runner._unconfigured}")
        assert not set(runner._failures) & set(runner._unconfigured), (
            "a provider was recorded as both failed and unconfigured")

    def test_an_unconfigured_provider_is_never_a_failure(self, cfg):
        """An offline install must not be reported as an outage."""
        from research_engine.core.orchestrator import build_default_registry

        runner = self._runner(cfg, build_default_registry(cfg))
        runner._search("fleet", ["web"])

        assert runner._unconfigured == ["web"], (
            f"the absent web provider was not classified as unconfigured: "
            f"{runner._unconfigured}")
        assert runner._failures == [], (
            f"an offline run was classified as a provider failure: "
            f"{runner._failures}")


class TestNoveltyProviderReport:
    """The novelty verifier must name the providers it could not use."""

    def test_the_report_is_present_on_both_paths(self):
        from research_engine.providers.search.base import RawSearchHit
        from research_engine.reasoning.novelty import NoveltyVerifier

        class Boom:
            def search(self, query, max_results=10):
                raise RuntimeError("simulated outage")

        class P:
            def search(self, query, max_results=10):
                return [RawSearchHit(
                    url="https://arxiv.org/abs/2401.1",
                    title="Deep learning for robotic grasping",
                    snippet="We study grasping with many benchmarks.")]

        # the no-hits path: nothing was found and everything failed
        empty = NoveltyVerifier(_registry(("openalex", Boom()))).verify(
            "a novel method")
        assert empty["novelty_status"] == "uncertain"
        assert empty["provider_failures"], (
            "the provider failure was swallowed on the no-hits path")
        assert empty["unconfigured_providers"] == ["arxiv", "semantic_scholar"]
        assert "simulated outage" in empty["reason"]

        # the success path: one provider answered, the others did not
        reg = ProviderRegistry()
        reg.register_academic("openalex", P())
        reg.register_academic("arxiv", Boom())
        out = NoveltyVerifier(reg).verify("a novel method for grasping")
        assert out["novelty_status"] != "uncertain"
        assert out["provider_failures"], (
            "the provider failure was swallowed on the success path")
        assert out["unconfigured_providers"] == ["semantic_scholar"]


class TestReportStatesTheHonestNumbers:
    """The report is the artefact a human reads: it must say which meaning
    a result count carries and what each leg did."""

    def test_the_report_renders_both_count_bases_and_the_leg_outcomes(self, cfg,
                                                                       tmp_path):
        from research_engine.models.project import ResearchProject
        from research_engine.models.research import (RESULTS_COUNT_DISTINCT_URLS,
                                                     RESULTS_COUNT_LEGACY_HITS,
                                                     ResearchPlan, SearchQuery)
        from research_engine.reports.generator import ReportGenerator
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories
        from research_engine.storage.workspace import Workspace

        pid = "proj_report_bases"
        ws = Workspace(str(tmp_path / "data"), pid)
        repos = Repositories(Database(ws.db_path))

        plan = ResearchPlan(project_id=pid, objective="o")
        plan.ensure_id()
        repos.plans.save(plan)

        legacy = SearchQuery(project_id=pid, text="legacy row", branch="br_x",
                              results_count=7,
                              results_count_schema_version=RESULTS_COUNT_LEGACY_HITS,
                              leg_outcomes=[{"leg": "web", "provider": "web",
                                             "status": "hits", "hits": 7,
                                             "error": ""}])
        legacy.ensure_id()
        repos.queries.save(legacy)

        modern = SearchQuery(project_id=pid, text="distinct row", branch="br_x",
                              results_count=3,
                              results_count_schema_version=RESULTS_COUNT_DISTINCT_URLS,
                              leg_outcomes=[{"leg": "web", "provider": "web",
                                             "status": "failed", "hits": 0,
                                             "error": "boom"},
                                            {"leg": "forum", "provider": "web",
                                             "status": "unconfigured", "hits": 0,
                                             "error": ""}],
                              dropped_legs=["github"])
        modern.ensure_id()
        repos.queries.save(modern)

        project = ResearchProject(id=pid, question_raw="q", mode="academic")
        gen = ReportGenerator(cfg, None, repos, ws)
        md = Path(gen.write_plan(project)).read_text(encoding="utf-8")

        assert "legacy hits" in md, (
            "the report does not say that the legacy row counts raw hits")
        assert "distinct urls" in md, (
            "the report does not say that the other row counts distinct URLs")
        assert "web:hits(7)" in md, f"the leg outcome was not rendered: {md}"
        assert "web:failed(boom)" in md, f"the failed leg was not rendered: {md}"
        assert "forum:unconfigured" in md, (
            f"the unconfigured leg was not rendered: {md}")
        assert "dropped:github" in md, (
            f"the dropped leg was not rendered: {md}")
