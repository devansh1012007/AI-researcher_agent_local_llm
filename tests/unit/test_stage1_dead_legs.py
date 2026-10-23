"""Stage 1: no silent retrieval legs, honest counts, live traceability.

Covers the defects fixed in the first implementation stage:

- the ``forum`` route leg resolved to a provider that does not exist, so the
  PAIN branch of startup mode (pain discovery - a primary signal) had ALWAYS
  returned zero results, silently;
- ``semantic_scholar`` was routed on three branches but is not registered by
  the default config, so three more legs were permanently dead;
- two legs on the same provider and query returned the identical cached hit
  set and appended it twice, inflating ``results_count`` roughly twofold and
  destroying per-leg attribution;
- the watcher's academic leg called ``reg.academic``, an attribute
  ProviderRegistry does not have, so the exception was swallowed and the leg
  has never run; the web leg constructed a provider directly and therefore
  ignored ``web_provider: none``;
- ``EvidenceService.trace_claim`` read ``claim.evidence_ids``, a field Claim
  does not have, so every real claim raised AttributeError and the MCP
  get_claim/trace_claim tools returned an internal error.

Every test here pins the FIX, not the happy path: each one fails when its
defect is reintroduced. In particular the persisted query row (not the
returned tuple) is what is asserted, the provider report is asserted on the
success path as well as the no-hits path, and the watcher summary is asserted
from a real ``tick()``.
"""
from __future__ import annotations

from research_engine.models.evidence import Claim, Evidence
from research_engine.pipeline.routing import (LEG_NAMES, ProviderRegistry,
                                              route_for)


def _repos(tmp_path, project_id):
    """Per-project storage, wired the way the orchestrator wires it."""
    from research_engine.storage.database import Database
    from research_engine.storage.repositories import Repositories
    from research_engine.storage.workspace import Workspace
    ws = Workspace(str(tmp_path / "data"), project_id)
    return Repositories(Database(ws.db_path))


def _branch_and_query(repos, project_id, category):
    from research_engine.models.research import ResearchBranch, SearchQuery
    br = ResearchBranch(project_id=project_id, category=category,
                         question="pain?")
    br.ensure_id()
    repos.branches.save(br)
    q = SearchQuery(project_id=project_id, text="fleet costs", branch=br.id)
    q.ensure_id()
    repos.queries.save(q)
    return br, q


def _last_query(repos, project_id):
    """The query row just saved (the worker's executor reloads it)."""
    return repos.queries.all(project_id)[-1]


def _watcher(ctx, project_id):
    """A persisted watcher, scoped to the web leg.

    `action="notify_only"` keeps the tick from running the (slow) document
    extraction path: these tests are about the tick's reporting, not about
    incremental extraction.
    """
    from research_engine.models.job import Watcher as WatcherModel

    w = WatcherModel(project_id=project_id, query="fleet costs",
                     source_scope=["web"], action="notify_only")
    ctx.platform_db.save_watcher(w)
    return w


def _drain(queue):
    """Every event currently on the bus queue."""
    import queue as _queue

    out = []
    while True:
        try:
            out.append(queue.get_nowait())
        except _queue.Empty:
            return out


# ---------------------------------------------------------------------------
# Route map: every leg resolves, or is explicitly optional
# ---------------------------------------------------------------------------

class TestRouteMap:
    def test_every_leg_resolves_or_is_explicitly_optional(self):
        """A leg naming a provider the default registry cannot register is a
        configuration error - it can never resolve, so it must not exist
        unless it is explicitly optional.

        The provider NAMES are enumerated here, but whether each one is
        actually REGISTERED is decided by the REAL default registry
        builder: a name the engine never registers must not be required by
        a non-optional leg.
        """
        from research_engine.core.config import AppConfig
        from research_engine.core.orchestrator import build_default_registry

        reg = build_default_registry(AppConfig())
        registered = {name for name in ("web", "openalex", "crossref", "arxiv",
                                        "semantic_scholar")
                      if reg.get_any(name) is not None}
        assert registered, "the default registry registered no provider at all"
        for name in LEG_NAMES:
            leg = route_for("GENERIC", [name]).legs[0]
            if leg.provider in registered:
                continue
            assert leg.optional, (
                f"leg {name!r} names provider {leg.provider!r}, which the "
                f"default registry does not register, and it is not optional")

    def test_default_routes_only_use_known_legs(self):
        from research_engine.pipeline.routing import DEFAULT_ROUTES
        for category, legs in DEFAULT_ROUTES.items():
            for name in legs:
                assert name in LEG_NAMES, (
                    f"route {category} names unknown leg {name!r}")

    def test_forum_leg_resolves_to_a_real_provider(self):
        """The PAIN branch must have a working forum leg."""
        legs = {leg.name: leg for leg in route_for("PAIN").legs}
        assert "forum" in legs, "the forum leg was removed from the PAIN route"
        assert legs["forum"].query_suffix, (
            "the forum leg must bias the query, otherwise it returns the "
            "same hits as the plain web leg")

    def test_refinement_legs_have_distinct_query_text(self):
        """Two legs on the same provider must search different queries,
        otherwise they return the same cached hits and double-count."""
        legs = route_for("CURRENT_STATE").legs
        by_provider = {}
        for leg in legs:
            by_provider.setdefault(leg.provider, []).append(leg.query_suffix)
        for provider, suffixes in by_provider.items():
            assert len(suffixes) == len(set(suffixes)), (
                f"provider {provider} has two legs with the same query text: "
                f"{suffixes}")

    def test_no_two_legs_on_one_provider_share_a_query_suffix(self):
        """Distinctness must hold across the WHOLE leg vocabulary.

        A per-route check is not enough: `government` and `documentation` are
        both web legs, but no single route contains both, so a collision
        between them is invisible to a check that only looks at one route.
        """
        by_provider: dict[str, list[tuple[str, str]]] = {}
        for name in sorted(LEG_NAMES):
            leg = route_for("GENERIC", [name]).legs[0]
            by_provider.setdefault(leg.provider, []).append(
                (name, leg.query_suffix))
        assert len(by_provider["web"]) >= 2, (
            "the check below would be vacuous with a single web leg")
        for provider, legs in by_provider.items():
            suffixes = [suffix for _, suffix in legs]
            assert len(suffixes) == len(set(suffixes)), (
                f"provider {provider} has two legs with the same query text: "
                f"{legs}")

    def test_the_documentation_leg_is_not_a_dead_site_operator(self):
        """`site:` takes a DOMAIN. "docs" and "developer" are not domains,
        so `site:docs OR site:developer` matched nothing on the live
        endpoint - a silent zero leg, the defect this map exists to remove.
        """
        legs = {leg.name: leg for leg in route_for("GENERIC", ["documentation"]).legs}
        suffix = legs["documentation"].query_suffix
        assert "site:docs" not in suffix, (
            "`site:docs` is not a domain; it returns zero hits")
        assert "site:developer" not in suffix, (
            "`site:developer` is not a domain; it returns zero hits")
        assert suffix.strip(), "the documentation leg must bias its query"

    def test_semantic_scholar_is_explicitly_optional(self):
        """It is not in the default academic provider list, so its absence
        must be a declared state rather than a silent zero."""
        legs = {leg.name: leg for leg in route_for("METHODS").legs}
        assert legs["semantic_scholar"].optional is True
        assert legs["openalex"].optional is False

    def test_unknown_source_preferences_are_dropped(self):
        """An LLM planner can emit any string. An unknown name must not
        become a leg that resolves to nothing."""
        legs = route_for("PAIN", ["reddit", "web"]).legs
        assert all(leg.name != "reddit" for leg in legs)
        assert any(leg.name == "web" for leg in legs)

    def test_preferences_do_not_drop_the_default_legs(self):
        legs = [leg.name for leg in route_for("PAIN", ["openalex"]).legs]
        assert "openalex" in legs
        assert "web" in legs and "forum" in legs

    def test_dropped_preferences_are_recorded_not_silent(self):
        """A planner that asks for a source we do not have must leave a
        trace, otherwise a mis-planned route looks like a planned one."""
        route = route_for("PAIN", ["github", "web"])
        assert "github" in route.dropped_legs
        assert [leg.name for leg in route.legs] == ["web", "forum"]

    def test_the_default_path_is_never_truncated(self):
        """The route cap applies to the default path too, so no default
        route may exceed it - otherwise a default route would lose a leg
        without a trace."""
        from research_engine.pipeline.routing import DEFAULT_ROUTES
        for category, names in DEFAULT_ROUTES.items():
            route = route_for(category)
            assert [leg.name for leg in route.legs] == list(names), (
                f"the default route for {category} was truncated: "
                f"{[leg.name for leg in route.legs]} != {names}")
            assert route.dropped_legs == [], (
                f"the default route for {category} dropped {route.dropped_legs}")

    def test_the_route_cap_bounds_the_legs_and_records_the_dropped_ones(self):
        """A branch must not fan out into an unbounded number of provider
        calls per query.

        The cap is a guard, so it needs a pin: nothing else in the engine
        depends on it, which is exactly how a runaway route would slip in.
        The names the cap removes must be RECORDED, not dropped silently -
        a planner that asked for six legs must be able to see that two of
        them did not run.
        """
        from research_engine.pipeline.routing import _MAX_LEGS

        wanted = ["web", "documentation", "forum", "government", "company",
                  "openalex"]
        assert len(wanted) > _MAX_LEGS, (
            "the fixture must exceed the cap for this test to mean anything")
        route = route_for("PAIN", wanted)

        assert len(route.legs) < len(wanted), (
            "the cap did not bite: the route kept every requested leg")
        assert len(route.legs) == _MAX_LEGS
        assert [leg.name for leg in route.legs] == wanted[:_MAX_LEGS]
        for name in wanted[_MAX_LEGS:]:
            assert name in route.dropped_legs, (
                f"the leg {name!r} was removed without a trace: "
                f"{route.dropped_legs}")


# ---------------------------------------------------------------------------
# Retrieval worker: per-leg outcomes, distinct counts
# ---------------------------------------------------------------------------

class TestLegOutcomes:
    def test_each_leg_records_its_own_outcome(self, cfg, fake_registry, tmp_path):
        """Every leg of the route must appear in leg_outcomes, so a leg that
        resolved to nothing is visible."""
        from research_engine.core.ids import project_id_from_question
        from research_engine.pipeline.retrieval import RetrievalWorker

        pid = project_id_from_question("leg outcome test")
        repos = _repos(tmp_path, pid)
        _branch_and_query(repos, pid, "PAIN")

        worker = RetrievalWorker(cfg, repos, fake_registry)
        _hits, _errors, outcomes, _dropped = worker._execute_one(
            pid, _last_query(repos, pid))

        legs = {leg.name for leg in route_for("PAIN").legs}
        assert {o["leg"] for o in outcomes} == legs
        assert all(o["status"] in ("hits", "unconfigured",
                                   "optional_unconfigured", "failed")
                   for o in outcomes)

    def test_each_leg_issues_its_own_query_text(self, cfg, fake_registry, tmp_path):
        """The per-leg query suffix must REACH the provider.

        The route map only proves the suffixes differ; this proves the worker
        uses them. With the suffix ignored, two legs on the same provider hit
        the same cache key and return the identical hit set - the original
        double-count defect.
        """
        from research_engine.core.ids import project_id_from_question
        from research_engine.pipeline.retrieval import RetrievalWorker

        pid = project_id_from_question("distinct query text test")
        repos = _repos(tmp_path, pid)
        _branch_and_query(repos, pid, "CURRENT_STATE")

        worker = RetrievalWorker(cfg, repos, fake_registry)
        worker._execute_one(pid, _last_query(repos, pid))

        legs = {leg.name: leg for leg in route_for("CURRENT_STATE").legs}
        expected = {"fleet costs",
                    "fleet costs" + legs["documentation"].query_suffix}
        web = fake_registry.get_search("web")
        seen = list(web.queries_seen)
        assert len(seen) >= 2, (
            f"the two web legs issued {len(seen)} queries: {seen}")
        assert len(set(seen)) == len(seen), (
            f"two legs issued the same query text: {seen}")
        assert set(seen) == expected, (
            f"the legs did not issue their own query text: {seen} != {expected}")

    def test_unconfigured_provider_is_reported_not_failed(self, cfg, tmp_path):
        """INV-012: an unconfigured provider is NOT a failure. But it must be
        reported, so the gap is visible instead of silently zero."""
        from research_engine.core.ids import project_id_from_question
        from research_engine.pipeline.retrieval import RetrievalWorker

        pid = project_id_from_question("unconfigured test")
        repos = _repos(tmp_path, pid)
        _branch_and_query(repos, pid, "PAIN")

        # An EMPTY registry: nothing is configured.
        worker = RetrievalWorker(cfg, repos, ProviderRegistry())
        hits, errors, outcomes, _dropped = worker._execute_one(
            pid, _last_query(repos, pid))

        assert hits == []
        assert errors == [], "an unconfigured provider must not be a failure"
        assert outcomes
        assert all(o["status"] == "unconfigured" for o in outcomes)

    def test_an_unregistered_optional_leg_is_a_distinct_state(self, cfg, tmp_path):
        """An optional leg the operator did not enable is a DECLARED state,
        not a configuration gap.

        The `optional` flag must have an observable effect, otherwise it is a
        flag nobody can act on.
        """
        from research_engine.core.ids import project_id_from_question
        from research_engine.pipeline.retrieval import RetrievalWorker

        pid = project_id_from_question("optional leg state test")
        repos = _repos(tmp_path, pid)
        # METHODS routes openalex, arxiv, semantic_scholar and web.
        _branch_and_query(repos, pid, "METHODS")

        worker = RetrievalWorker(cfg, repos, ProviderRegistry())
        _hits, errors, outcomes, _dropped = worker._execute_one(
            pid, _last_query(repos, pid))

        by_leg = {o["leg"]: o for o in outcomes}
        assert by_leg["semantic_scholar"]["status"] == "optional_unconfigured", (
            "an optional leg that is not registered must be reported as its "
            f"own state: {by_leg['semantic_scholar']}")
        assert by_leg["openalex"]["status"] == "unconfigured", (
            "a required leg that is not registered is a configuration gap")
        assert errors == [], "neither state is a failure"

    def test_the_persisted_query_row_carries_the_count_and_the_outcomes(
            self, cfg, tmp_path):
        """The PERSISTED row must carry the honest count and the per-leg
        audit trail.

        The previous assertions compared a set with itself and read the
        returned tuple, so neither the count nor the outcomes was actually
        pinned by anything.
        """
        from research_engine.core.ids import project_id_from_question
        from research_engine.models.research import RESULTS_COUNT_DISTINCT_URLS
        from research_engine.pipeline.retrieval import RetrievalWorker
        from research_engine.providers.search.base import RawSearchHit

        class SameHits:
            """The SAME two URLs for every query (two legs, one document)."""

            def search(self, query, max_results=10):
                return [RawSearchHit(url="https://example.org/a", title="A",
                                     snippet="s"),
                        RawSearchHit(url="https://example.org/b", title="B",
                                     snippet="s")]

        pid = project_id_from_question("persisted query row test")
        repos = _repos(tmp_path, pid)
        # PAIN routes two web legs, so the same two URLs arrive twice.
        _branch_and_query(repos, pid, "PAIN")

        reg = ProviderRegistry()
        reg.register_search("web", SameHits())
        worker = RetrievalWorker(cfg, repos, reg)
        q = _last_query(repos, pid)
        worker.execute_queries(pid, [q], budget_left=1)

        row = repos.queries.get(q.id)
        assert row is not None, "the query row was not persisted"
        assert row.results_count == 2, (
            f"the persisted count is not the distinct canonical-URL count: "
            f"{row.results_count}")
        assert row.results_count_schema_version == RESULTS_COUNT_DISTINCT_URLS, (
            "the persisted row does not say which meaning results_count has")
        assert row.leg_outcomes, "the persisted row carries no leg outcomes"
        assert {o["leg"] for o in row.leg_outcomes} == {"web", "forum"}

    def test_dropped_preferences_reach_the_persisted_query_row(
            self, cfg, tmp_path):
        """A refused source must be visible in a persisted artefact, not
        only in memory."""
        from research_engine.core.ids import project_id_from_question
        from research_engine.models.research import ResearchBranch, SearchQuery
        from research_engine.pipeline.retrieval import RetrievalWorker

        pid = project_id_from_question("dropped preferences test")
        repos = _repos(tmp_path, pid)
        br = ResearchBranch(project_id=pid, category="PAIN", question="pain?",
                            source_preferences=["github", "web"])
        br.ensure_id()
        repos.branches.save(br)
        q = SearchQuery(project_id=pid, text="fleet costs", branch=br.id)
        q.ensure_id()
        repos.queries.save(q)

        worker = RetrievalWorker(cfg, repos, ProviderRegistry())
        worker.execute_queries(pid, [q], budget_left=1)

        row = repos.queries.get(q.id)
        assert row is not None
        assert "github" in row.dropped_legs, (
            f"the dropped preference was not recorded: {row.dropped_legs}")


# ---------------------------------------------------------------------------
# Watcher: the academic leg must actually run
# ---------------------------------------------------------------------------

class TestWatcherLegs:
    def test_watcher_uses_the_injected_registry(self, cfg, tmp_path):
        """The academic leg must work; it never ran because it called
        reg.academic, which does not exist."""
        from research_engine.platform.watchers import WatchRunner
        from research_engine.providers.search.base import RawSearchHit

        class P:
            def __init__(self, name):
                self.name = name

            def search(self, query, max_results=10):
                return [RawSearchHit(url=f"https://{self.name}.org/x",
                                     title="t", snippet="s")]

        reg = ProviderRegistry()
        reg.register_search("web", P("web"))
        reg.register_academic("openalex", P("openalex"))

        runner = WatchRunner.__new__(WatchRunner)
        runner.ctx = type("C", (), {"cfg": cfg})()
        runner.registry = reg
        runner._unconfigured = []
        runner._failures = []

        hits = runner._search("fleet", ["web", "openalex"])
        domains = {h["url"].split("/")[2] for h in hits}
        assert domains == {"web.org", "openalex.org"}, (
            f"the watcher did not query both legs: {domains}")

    def test_watcher_honours_web_provider_none(self, cfg, monkeypatch):
        """An offline install must not have the watcher call out anyway.

        The assertion is on the CLASSIFICATION, not on the hit list: the
        web provider must be recorded as UNCONFIGURED - a declared
        configuration state - and NOT as a failure. `hits == []` alone
        proved nothing: a blocked outbound call produces the same empty
        list, so this test used to pass WITH the defect in place and only
        failed on a machine WITH network, which is the opposite of the
        repo's hermetic contract.

        The outbound path is blocked here, so the test is hermetic: a
        call-out fails it loudly instead of depending on the machine's
        connectivity.
        """
        import httpx
        from research_engine.core.orchestrator import build_default_registry
        from research_engine.platform.watchers import WatchRunner
        from research_engine.providers.search import duckduckgo

        def no_network(*a, **k):
            raise AssertionError("the watcher called out while offline")

        monkeypatch.setattr(httpx, "get", no_network)
        monkeypatch.setattr(httpx, "post", no_network)
        monkeypatch.setattr(httpx, "request", no_network)

        class Boom:
            """The web provider a call-out would use. It must never run."""

            def __init__(self, *a, **k):
                pass

            def search(self, query, max_results=10):
                raise AssertionError("the watcher called out while offline")

        # Any code path that CONSTRUCTS a web provider directly (the
        # original defect) now hits Boom and fails the test loudly.
        monkeypatch.setattr(duckduckgo, "DuckDuckGoProvider", Boom)

        # web_provider is "none" in the cfg fixture, so the registry must not
        # contain "web" at all.
        default_reg = build_default_registry(cfg)
        assert default_reg.get_search("web") is None, (
            "web_provider=none must not register a web provider")

        runner = WatchRunner.__new__(WatchRunner)
        runner.ctx = type("C", (), {"cfg": cfg})()
        runner.registry = default_reg
        runner._unconfigured = []
        runner._failures = []

        hits = runner._search("fleet", ["web"])

        assert hits == []
        assert runner._unconfigured == ["web"], (
            f"the absent web provider was not classified as unconfigured: "
            f"{runner._unconfigured}")
        assert runner._failures == [], (
            f"an offline run was classified as a provider failure: "
            f"{runner._failures}")

    def test_watcher_reports_provider_failure(self, cfg, tmp_path):
        """A provider failure must be recorded, not flattened into 'OK'."""
        from research_engine.platform.watchers import WatchRunner

        class Failing:
            def search(self, query, max_results=10):
                raise RuntimeError("simulated outage")

        reg = ProviderRegistry()
        reg.register_search("web", Failing())

        runner = WatchRunner.__new__(WatchRunner)
        runner.ctx = type("C", (), {"cfg": cfg})()
        runner.registry = reg
        runner._unconfigured = []
        runner._failures = []

        runner._search("fleet", ["web"])
        assert runner._failures, "the failure was swallowed"
        assert any("simulated outage" in f for f in runner._failures)

    def test_watcher_keeps_unconfigured_and_failed_apart(self, cfg, tmp_path):
        """The two states are told apart by WHERE they were recorded, never
        by the message text.

        A real outage whose message happens to contain "not configured" (an
        API key error, say) must not be downgraded to an unconfigured
        provider.
        """
        from research_engine.platform.watchers import WatchRunner

        class Failing:
            def search(self, query, max_results=10):
                raise RuntimeError("semantic scholar: API key not configured")

        reg = ProviderRegistry()
        reg.register_search("web", Failing())

        runner = WatchRunner.__new__(WatchRunner)
        runner.ctx = type("C", (), {"cfg": cfg})()
        runner.registry = reg
        runner._unconfigured = []
        runner._failures = []

        runner._search("fleet", ["web"])
        assert runner._failures, "a real failure was classified as unconfigured"
        assert not runner._unconfigured, (
            "a real failure was filed as an unconfigured provider")

    def test_tick_reports_degraded_when_a_provider_failed(self, cfg, tmp_path):
        """The tick summary must say DEGRADED when a provider failed.

        The old summary always said OK, and the failure-vs-unconfigured
        distinction was re-derived from the message text, so an outage could
        be reported as a healthy tick.
        """
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.platform.events import EventBus
        from research_engine.platform.watchers import WatchRunner
        from research_engine.services.context import ServiceContext

        class Failing:
            def search(self, query, max_results=10):
                raise RuntimeError("semantic scholar: API key not configured")

        orch = Orchestrator.create_project(cfg, "watcher degraded status test",
                                           mode="academic")
        ctx = ServiceContext(cfg=cfg)
        try:
            reg = ProviderRegistry()
            reg.register_search("web", Failing())
            runner = WatchRunner(ctx, EventBus(), registry=reg)
            summary = runner.tick(_watcher(ctx, orch.project.id))
            assert summary["status"] == "DEGRADED", (
                f"a provider outage was reported as a healthy tick: {summary}")
            assert summary.get("failures"), (
                f"the failure was not reported: {summary}")
        finally:
            ctx.stop_scheduler()

    def test_tick_reports_ok_when_the_providers_work(self, cfg, tmp_path):
        """The counterpart: a working tick must not be reported as degraded."""
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.platform.events import EventBus
        from research_engine.platform.watchers import WatchRunner
        from research_engine.providers.search.base import RawSearchHit
        from research_engine.services.context import ServiceContext

        class P:
            def search(self, query, max_results=10):
                return [RawSearchHit(url="https://example.org/ok", title="t",
                                     snippet="s")]

        orch = Orchestrator.create_project(cfg, "watcher ok status test",
                                           mode="academic")
        ctx = ServiceContext(cfg=cfg)
        try:
            reg = ProviderRegistry()
            reg.register_search("web", P())
            runner = WatchRunner(ctx, EventBus(), registry=reg)
            summary = runner.tick(_watcher(ctx, orch.project.id))
            assert summary["status"] == "OK", (
                f"a working tick was reported as degraded: {summary}")
        finally:
            ctx.stop_scheduler()

    def test_a_newly_discovered_url_publishes_source_updated(self, cfg, tmp_path):
        """The watcher must publish SourceUpdated, not EvidenceCreated.

        Nothing has been fetched or extracted at that point, so there is no
        evidence to announce. `platform/events.py` EVENT_TYPES is the
        authoritative list of event types.
        """
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.platform.events import EventBus
        from research_engine.platform.watchers import WatchRunner
        from research_engine.providers.search.base import RawSearchHit
        from research_engine.services.context import ServiceContext

        class P:
            def search(self, query, max_results=10):
                return [RawSearchHit(url="https://example.org/new", title="N",
                                     snippet="s")]

        orch = Orchestrator.create_project(cfg, "watcher event type test",
                                           mode="academic")
        ctx = ServiceContext(cfg=cfg)
        bus = EventBus()
        sub_id, queue = bus.subscribe(None)
        try:
            reg = ProviderRegistry()
            reg.register_search("web", P())
            runner = WatchRunner(ctx, bus, registry=reg)
            runner.tick(_watcher(ctx, orch.project.id))
        finally:
            bus.unsubscribe(sub_id)
            ctx.stop_scheduler()

        types = [e.type for e in _drain(queue)]
        assert "SourceUpdated" in types, f"no SourceUpdated event: {types}"
        assert "EvidenceCreated" not in types, (
            f"the watcher announced evidence it never extracted: {types}")


# ---------------------------------------------------------------------------
# trace_claim: the provenance chain must work for a real claim
# ---------------------------------------------------------------------------

class TestTraceClaim:
    def test_trace_claim_on_a_real_claim(self, cfg, tmp_path):
        """This is the path the README advertises. It raised AttributeError
        for every real claim."""
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.services.context import ServiceContext
        from research_engine.services.knowledge_service import EvidenceService

        cfg.storage.data_dir = str(tmp_path / "data")
        orch = Orchestrator.create_project(cfg, "Trace claim chain test",
                                           mode="academic")
        pid = orch.project.id
        ev = Evidence(project_id=pid, claim_text="Fleet costs 10 per seat",
                      quote="It costs $10 per seat.",
                      source_url="https://example.org/a", source_id="s1",
                      document_id="d1")
        ev.ensure_id()
        orch.repos.evidence.save(ev)
        claim = Claim(project_id=pid, text="Fleet costs 10 per seat")
        claim.ensure_id()
        claim.supported_by = [ev.id]
        orch.repos.claims.save(claim)

        ctx = ServiceContext(cfg=cfg)
        chain = EvidenceService(ctx).trace_claim(pid, claim.id)

        assert len(chain) == 1
        assert chain[0]["evidence_id"] == ev.id
        assert chain[0]["role"] == "supports"
        assert chain[0]["quote"] == "It costs $10 per seat."

    def test_trace_claim_includes_contradicting_evidence(self, cfg, tmp_path):
        """The READER must handle `Claim.contradicted_by`.

        KNOWN GAP - read this before believing the test name:
        `Claim.contradicted_by` has NO production writer in this codebase
        (grep: the only place it is set is this test). So the "contradicts"
        role is UNREACHABLE in a live run today, and this test does not prove
        that contradictions are detected - it proves that the reader handles
        the field correctly when a caller populates it, so the chain is
        complete and future-proof. Writing a production writer for it is a
        separate change with its own invariants.
        """
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.services.context import ServiceContext
        from research_engine.services.knowledge_service import EvidenceService

        cfg.storage.data_dir = str(tmp_path / "data2")
        orch = Orchestrator.create_project(cfg, "Trace contradicting test",
                                           mode="academic")
        pid = orch.project.id
        ev = Evidence(project_id=pid, claim_text="Cost is 10",
                      quote="It costs $10 per seat.",
                      source_url="https://example.org/b", source_id="s2",
                      document_id="d2")
        ev.ensure_id()
        orch.repos.evidence.save(ev)
        claim = Claim(project_id=pid, text="Cost is 10")
        claim.ensure_id()
        claim.contradicted_by = [ev.id]
        orch.repos.claims.save(claim)

        ctx = ServiceContext(cfg=cfg)
        chain = EvidenceService(ctx).trace_claim(pid, claim.id)
        assert chain and chain[0]["role"] == "contradicts"


# ---------------------------------------------------------------------------
# Novelty: an unconfigured provider must be distinguishable from "no hits"
# ---------------------------------------------------------------------------

class TestNoveltyReporting:
    def test_unconfigured_providers_are_named(self):
        from research_engine.reasoning.novelty import NoveltyVerifier

        out = NoveltyVerifier(ProviderRegistry()).verify("a novel hypothesis")
        assert out["novelty_status"] == "uncertain"
        assert "openalex" in out["unconfigured_providers"]
        assert "not configured" in out["reason"]

    def test_the_provider_report_is_present_on_the_success_path(self):
        """The provider report must be on EVERY path, not only the no-hits
        path.

        The success path used to return a verdict that named neither the
        unconfigured providers nor the failures, so a one-provider search was
        indistinguishable from a three-provider search.
        """
        from research_engine.providers.search.base import RawSearchHit
        from research_engine.reasoning.novelty import NoveltyVerifier

        class P:
            def search(self, query, max_results=10):
                return [RawSearchHit(
                    url="https://arxiv.org/abs/2401.1",
                    title="Deep learning for robotic grasping",
                    snippet="We study grasping with many benchmarks.")]

        reg = ProviderRegistry()
        reg.register_academic("openalex", P())
        out = NoveltyVerifier(reg).verify("novel method for robotic grasping")
        assert out["novelty_status"] != "uncertain"
        assert out["unconfigured_providers"] == ["arxiv", "semantic_scholar"], (
            "the success path does not report the unconfigured providers")
        assert out["provider_failures"] == []
        assert "not configured" in out["reason"]

    def test_a_provider_failure_is_recorded_not_swallowed(self):
        """A provider that RAISES must be named in the result.

        The failure list was appended to but never read by any assertion, so
        removing the append changed nothing the suite could see.
        """
        from research_engine.providers.search.base import RawSearchHit
        from research_engine.reasoning.novelty import NoveltyVerifier

        class Boom:
            def search(self, query, max_results=10):
                raise RuntimeError("simulated outage")

        class P:
            def search(self, query, max_results=10):
                return [RawSearchHit(
                    url="https://arxiv.org/abs/2401.2",
                    title="A prior work on grasping",
                    snippet="We study grasping with many benchmarks.")]

        reg = ProviderRegistry()
        reg.register_academic("openalex", P())
        reg.register_academic("arxiv", Boom())
        out = NoveltyVerifier(reg).verify("novel method for robotic grasping")
        assert out["provider_failures"], "the provider failure was swallowed"
        assert any("arxiv" in f and "simulated outage" in f
                   for f in out["provider_failures"]), (
            f"the failure does not name the provider: {out['provider_failures']}")
        assert "simulated outage" in out["reason"]

    def test_similarity_path_does_not_crash(self):
        """The similarity comparison passed a token list where a vector was
        expected, so this path could only ever return 'uncertain'."""
        from research_engine.providers.search.base import RawSearchHit
        from research_engine.reasoning.novelty import NoveltyVerifier

        class P:
            def search(self, query, max_results=10):
                return [RawSearchHit(
                    url="https://arxiv.org/abs/2401.1",
                    title="Deep learning for robotic grasping",
                    snippet="We study grasping with many benchmarks.")]

        reg = ProviderRegistry()
        reg.register_academic("openalex", P())
        out = NoveltyVerifier(reg).verify("novel method for robotic grasping")
        assert out["novelty_status"] in ("likely_novel", "possibly_novel",
                                         "incremental", "already_explored")
        assert out["top_similarity"] > 0


# ---------------------------------------------------------------------------
# C07: collision-free, monotonic entity ids
# ---------------------------------------------------------------------------

class TestUlidIds:
    """Entity ids must be unique across processes and ordered by creation.

    The previous implementation was a process-global counter with no
    persistence: two processes writing the same project database both minted
    ``ev_000001``, and the upsert (``ON CONFLICT(id) DO UPDATE``) silently
    overwrote the first row. These tests pin the replacement - a monotonic
    ULID - at the three levels where that defect lived: the id itself, the
    process boundary, and the database row.
    """

    @staticmethod
    def _freeze_clock(monkeypatch, seconds: float = 1_700_000_000.0,
                      reset: bool = True) -> None:
        """Pin the id clock to one millisecond.

        ``reset`` clears the module's last-timestamp/last-random state, which
        is what makes the test independent of whatever a previous test
        minted. It must be False when the clock is moved but the state must
        be carried over.
        """
        from research_engine.core import ids as ids_mod

        class _Clock:
            def time(self) -> float:
                return seconds

        # raising=False: the pinned clock and the state reset are only
        # meaningful for the ULID implementation - against any other one the
        # test must fail on its own assertion, not on a missing attribute.
        monkeypatch.setattr(ids_mod, "time", _Clock(), raising=False)
        if reset:
            monkeypatch.setattr(ids_mod, "_last_ms", 0, raising=False)
            monkeypatch.setattr(ids_mod, "_last_random", 0, raising=False)

    def test_ten_thousand_ids_in_one_millisecond_are_unique_and_increasing(self, monkeypatch):
        """10 000 ids minted inside one millisecond must be UNIQUE and
        strictly increasing.

        This pins the id itself and nothing else. Creation order for the
        graph store and for the duplicate repair comes from the row
        payload's `created_at`, NEVER from the id text (the id text is not
        a creation order - see `tests/unit/test_stage2_id_ordering.py`).
        """
        from research_engine.core.ids import next_id

        self._freeze_clock(monkeypatch)
        minted = [next_id("ev") for _ in range(10_000)]

        assert len(set(minted)) == 10_000, "ids minted in one millisecond collided"
        assert all(b > a for a, b in zip(minted, minted[1:])), (
            "ids minted in the same millisecond must be strictly increasing")

    def test_id_is_prefix_plus_crockford_base32(self):
        """The body is 26 Crockford base32 characters (no I, L, O or U)."""
        import re
        from research_engine.core.ids import next_id

        for prefix in ("ev", "clm", "ent"):
            ident = next_id(prefix)
            head, sep, body = ident.partition("_")
            assert head == prefix and sep == "_", f"the prefix was lost: {ident}"
            assert len(body) == 26, f"{ident} does not have a 26 character body"
            assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", body), (
                f"{ident} is not Crockford base32")

    def test_prefix_is_preserved(self):
        """The prefix discriminates types in the repositories, in natural
        keys and in graph prefixes - it is load-bearing."""
        from research_engine.core.ids import next_id

        assert next_id("ev").startswith("ev_")
        assert next_id("clm").startswith("clm_")

    def test_two_processes_minting_ids_do_not_collide(self, tmp_path):
        """Two processes writing the SAME project database must not mint the
        same id. With the old counter both minted ``clm_000001`` and the
        second write silently replaced the first row."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories

        project_id = "proj_ulid_collision"
        db_path = tmp_path / project_id / "db.sqlite"
        repos = Repositories(Database(db_path))

        script = (
            "import sys\n"
            "from research_engine.models.evidence import Claim\n"
            "from research_engine.storage.database import Database\n"
            "from research_engine.storage.repositories import Repositories\n"
            "db_path, project_id, text = sys.argv[1:4]\n"
            "repos = Repositories(Database(db_path))\n"
            "claim = Claim(project_id=project_id, text=text)\n"
            "claim.ensure_id()\n"
            "repos.claims.save(claim)\n"
            "print(claim.id)\n"
        )
        env = dict(os.environ)
        src = str(Path(__file__).resolve().parents[2] / "src")
        env["PYTHONPATH"] = os.pathsep.join(
            [p for p in (src, env.get("PYTHONPATH", "")) if p])

        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(db_path), project_id,
                 f"claim from process {i}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
            for i in range(2)
        ]
        minted = []
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, f"the subprocess failed: {err}"
            lines = [ln for ln in out.splitlines() if ln.strip()]
            assert lines, f"the subprocess printed no id (stdout={out!r})"
            minted.append(lines[-1])

        rows = repos.claims.all(project_id)
        assert len(rows) == 2, (
            f"expected 2 rows, got {len(rows)}: {[r.id for r in rows]}")
        assert minted[0] != minted[1], f"both processes minted {minted[0]}"
        assert {r.id for r in rows} == set(minted)
        # Both rows must still carry their own content: the old collision
        # destroyed the first row, it did not merely hide it.
        assert {r.text for r in rows} == {"claim from process 0",
                                          "claim from process 1"}

    def test_legacy_and_ulid_ids_coexist_without_overwriting(self, tmp_path):
        """A row written under the old counter scheme must stay readable and
        must not be overwritten by a new-format id."""
        from research_engine.models.evidence import Evidence
        from research_engine.storage.database import Database
        from research_engine.storage.repositories import Repositories

        repos = Repositories(Database(tmp_path / "db.sqlite"))
        project_id = "proj_legacy_mix"
        legacy = Evidence(id="ev_000042", project_id=project_id,
                          claim_text="legacy row")
        modern = Evidence(project_id=project_id, claim_text="ulid row")
        modern.ensure_id()

        repos.evidence.save(legacy)
        repos.evidence.save(modern)

        rows = repos.evidence.all(project_id)
        assert len(rows) == 2, "a legacy id and a ULID id must both survive"
        assert {r.id for r in rows} == {"ev_000042", modern.id}
        stored = repos.evidence.get("ev_000042")
        assert stored is not None and stored.claim_text == "legacy row"

    def test_a_forked_child_does_not_continue_the_parent_counter(self, monkeypatch):
        """A `fork()` WITHOUT a following `exec()` copies the parent's
        memory, so the child inherits the parent's `_last_random`.

        Without a pid check the child would take the same-millisecond
        branch and compute the SAME increment the parent computes - a
        byte-identical id, minted twice. The child re-seeds its random
        component instead.

        The fork is MODELLED, not performed: a fake `os` reports another
        pid, and the parent's module state is restored afterwards (a real
        fork hands the child its own copy of that memory). The entropy
        draws are deterministic, so the assertion cannot pass by luck.
        """
        import os as real_os
        from research_engine.core import ids as ids_mod
        from research_engine.core.ids import next_id

        class _ForkedOs:
            """`os` with a controllable pid and deterministic entropy."""

            def __init__(self):
                self.pid = real_os.getpid()
                self.draws = 0

            def getpid(self):
                return self.pid

            def urandom(self, n):
                self.draws += 1
                return bytes([self.draws]) * n

        forked_os = _ForkedOs()
        monkeypatch.setattr(ids_mod, "os", forked_os)
        monkeypatch.setattr(ids_mod, "_last_pid", real_os.getpid(),
                            raising=False)
        self._freeze_clock(monkeypatch)

        parent_first = next_id("ev")
        # the state the child would inherit
        saved = (ids_mod._last_pid, ids_mod._last_ms, ids_mod._last_random)

        forked_os.pid = real_os.getpid() + 1        # the child
        child = next_id("ev")

        # the child has its OWN copy of the memory: restore the parent's
        forked_os.pid = real_os.getpid()
        ids_mod._last_pid, ids_mod._last_ms, ids_mod._last_random = saved
        parent_next = next_id("ev")

        assert child != parent_next, (
            "the forked child continued the parent's counter and minted the "
            "same id")
        assert child != parent_first, (
            "the forked child reused the parent's random component")
        assert parent_next > parent_first, (
            "the parent must keep minting increasing ids after the fork")

    def test_ids_stay_increasing_when_the_clock_moves_backwards(self, monkeypatch):
        """An NTP correction must not hand out an id that sorts BEFORE an
        already minted one - the ordering consumers would then read the newer
        row as the older one."""
        from research_engine.core.ids import next_id

        self._freeze_clock(monkeypatch, 1_700_000_000.0)
        first = next_id("ev")
        self._freeze_clock(monkeypatch, 1_699_999_000.0, reset=False)
        second = next_id("ev")

        assert second > first, "a backwards clock must not break the id ordering"

    def test_concurrent_minting_never_duplicates_an_id(self):
        """The module lock is what keeps concurrent minting safe."""
        import threading
        from research_engine.core.ids import next_id

        minted: list[str] = []
        guard = threading.Lock()

        def worker():
            local = [next_id("ev") for _ in range(500)]
            with guard:
                minted.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(minted) == 4000
        assert len(set(minted)) == 4000, "concurrent minting produced a duplicate"
