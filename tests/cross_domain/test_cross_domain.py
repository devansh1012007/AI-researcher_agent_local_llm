"""Phase 4 §21–§26, §38–§41, §61–§65: cross-domain connections, standards,
cross-specialist contradictions, synthesis, flagship workflow."""
from __future__ import annotations

import pathlib
import tempfile
import time

import pytest


def _cfg(tmp_path):
    from research_engine.core.config import AppConfig
    cfg = AppConfig.load()
    cfg.storage.data_dir = str(tmp_path)
    cfg.search.web_provider = "none"
    cfg.search.academic_providers = []
    return cfg


def _orch(tmp_path, question="Find a startup opportunity from a "
                             "soft-robotics research gap", mode="startup"):
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.create_project(_cfg(pathlib.Path(tempfile.mkdtemp())),
                                       question, mode=mode)
    if not hasattr(orch, "cfg") or orch.cfg.storage.data_dir == "":
        pass
    return orch


def _seed_evidence(orch, items):
    from research_engine.models.evidence import Evidence
    from research_engine.models.research import Source
    pid = orch.project.id
    s = Source(project_id=pid, url="https://cd.example.com/1",
               canonical_url="https://cd.example.com/1",
               domain="cd.example.com", title="cross-domain corpus")
    s.ensure_id()
    orch.repos.sources.save(s)
    ids = []
    for claim, quote in items:
        e = Evidence(project_id=pid, claim_text=claim, quote=quote,
                     source_id=s.id, source_tier=3, status="SUPPORTED",
                     support_verdict="SUPPORTS")
        e.ensure_id()
        orch.repos.evidence.save(e)
        ids.append(e.id)
    return ids


TECH = ("The gripper prototype achieves 98% pick accuracy on the benchmark.",
        "prototype achieves 98% accuracy on benchmark")
CUSTOMER = ("Shop owners complain manual bookkeeping eats their weekends.",
            "complain manual bookkeeping eats weekends")
MARKET = ("The SMB bookkeeping segment spends heavily on software tools.",
          "segment spends on software tools")


class TestConnections:
    def test_propose_natural_key_dedupes(self):
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        ev = _seed_evidence(orch, [TECH])
        from research_engine.specialists.cross_domain import (
            CrossDomainRepos, RESEARCH_GAP_TO_STARTUP, propose_connection)
        gap = type("G", (), {"id": "gap_demo"})()
        c1 = propose_connection(
            orch, source_domain="research", target_domain="startup",
            source_entity="gap_demo", target_entity="opp_demo",
            relationship=RESEARCH_GAP_TO_STARTUP,
            rationale="gripper capability maps to produce-handling pain",
            evidence_ids=ev)
        c2 = propose_connection(
            orch, source_domain="research", target_domain="startup",
            source_entity="gap_demo", target_entity="opp_demo",
            relationship=RESEARCH_GAP_TO_STARTUP,
            rationale="duplicate proposal", evidence_ids=ev)
        assert c1.id == c2.id
        repos = CrossDomainRepos(orch.db)
        assert len(repos.connections.all(orch.project.id)) == 1

    def test_unknown_relationship_rejected(self):
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        from research_engine.specialists.cross_domain import propose_connection
        with pytest.raises(ValueError):
            propose_connection(orch, source_domain="a", target_domain="b",
                               source_entity="x", target_entity="y",
                               relationship="VIBES_BASED", rationale="r",
                               evidence_ids=[])

    def test_confidence_computed_from_evidence_quality(self):
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        ev = _seed_evidence(orch, [TECH])
        from research_engine.specialists.cross_domain import (
            RESEARCH_GAP_TO_STARTUP, propose_connection)
        c = propose_connection(
            orch, source_domain="research", target_domain="startup",
            source_entity="g1", target_entity="o1",
            relationship=RESEARCH_GAP_TO_STARTUP,
            rationale="capability→application", evidence_ids=ev)
        assert 0.0 < c.confidence <= 1.0
        # empty-evidence connection has zero confidence (INV-015)
        c2 = propose_connection(
            orch, source_domain="research", target_domain="startup",
            source_entity="g1", target_entity="o2",
            relationship=RESEARCH_GAP_TO_STARTUP,
            rationale="no evidence attached", evidence_ids=["ghost"])
        assert c2.confidence == 0.0

    def test_research_to_market_standard_requires_triple(self):
        """§61: breakthrough alone ≠ startup evidence."""
        from research_engine.specialists.cross_domain import (
            RESEARCH_GAP_TO_STARTUP, propose_connection, validate_connection)
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        tech_only = _seed_evidence(orch, [TECH])
        c = propose_connection(
            orch, source_domain="research", target_domain="startup",
            source_entity="g1", target_entity="o1",
            relationship=RESEARCH_GAP_TO_STARTUP, rationale="r",
            evidence_ids=tech_only)
        res = validate_connection(orch, c.id)
        assert res["status"] == "PROPOSED" and \
            set(res["unmet_classes"]) >= {"customer_problem", "market"}

        full = _seed_evidence(orch, [CUSTOMER, MARKET]) + tech_only
        c2 = propose_connection(
            orch, source_domain="research", target_domain="startup",
            source_entity="g1", target_entity="o2",
            relationship=RESEARCH_GAP_TO_STARTUP, rationale="r2",
            evidence_ids=full)
        res2 = validate_connection(orch, c2.id)
        assert res2["status"] == "VALIDATED", res2

    def test_contested_when_alternatives_and_unmet(self):
        from research_engine.specialists.cross_domain import (
            CUSTOMER_PAIN_TO_TECHNOLOGY, propose_connection,
            validate_connection)
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        cust_only = _seed_evidence(orch, [CUSTOMER])
        c = propose_connection(
            orch, source_domain="startup", target_domain="technology",
            source_entity="pain1", target_entity="meth1",
            relationship=CUSTOMER_PAIN_TO_TECHNOLOGY,
            rationale="maybe solvable",
            evidence_ids=cust_only,
            alternative_explanations=["process change could suffice"])
        res = validate_connection(orch, c.id)
        assert res["status"] == "CONTESTED"


class TestCrossDomainContradictions:
    def test_additive_fields_preserve_inv009(self):
        from research_engine.models.analysis import Contradiction
        k = Contradiction(project_id="p",
                          statement_a="market opportunity strong",
                          statement_b="technical cost prohibitive",
                          conflict_type="CROSS_DOMAIN_FEASIBILITY_VS_MARKET",
                          evidence_a_ids=["ev_a"], evidence_b_ids=["ev_b"],
                          specialist_a="startup", specialist_b="technology",
                          domain_difference="market vs engineering economics")
        k.ensure_id()
        assert k.evidence_a_ids and k.evidence_b_ids  # INV-009 intact
        assert k.specialist_a == "startup"

    def test_synthesis_surfaces_open_cross_contradictions(self):
        from research_engine.models.analysis import Contradiction
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        k = Contradiction(project_id=orch.project.id,
                          statement_a="market opportunity appears strong",
                          statement_b="compute cost currently prohibitive",
                          conflict_type="CROSS_DOMAIN_COST_VS_DEMAND",
                          evidence_a_ids=["ea"], evidence_b_ids=["eb"],
                          specialist_a="startup", specialist_b="technology")
        k.ensure_id()
        orch.repos.contradictions.save(k)
        from research_engine.specialists.synthesis import synthesize
        s = synthesize(orch)
        assert any(x["id"] == k.id
                   for x in s["cross_domain_contradictions"])


class TestSynthesis:
    def test_matrix_preserves_domain_boundaries_and_queue(self):
        """§40/§63/§65: dimensions stay separate; weakest queues first."""
        from research_engine.models.analysis import Connection
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        # one strong technical connection only → technical HIGH, others UNKNOWN
        c = Connection(project_id=orch.project.id,
                       source_domain="research", target_domain="technology",
                       source_entity="m1", target_entity="cap1",
                       relationship="TECHNOLOGY_TO_PRODUCT",
                       confidence=0.9, status="VALIDATED")
        c.ensure_id()
        from research_engine.specialists.cross_domain import CrossDomainRepos
        CrossDomainRepos(orch.db).connections.save(c)
        o_seed = None
        from research_engine.specialists.synthesis import synthesize
        s = synthesize(orch)
        m = s["decision_matrix"]
        assert m["technical"]["label"] == "HIGH"
        assert m["regulatory"]["label"] == "UNKNOWN"
        q = s["weakest_dimensions_queue"]
        assert q and q[0]["dimension"] != "regulatory"  # unknowns excluded
        assert q[0]["confidence"] <= q[-1]["confidence"]

    def test_synthesis_is_read_only(self):
        from research_engine.specialists.extension_audit import (
            store_fingerprint)
        orch = _orch(pathlib.Path(tempfile.mkdtemp()))
        before = store_fingerprint([pathlib.Path(orch.ws.db_path)])
        from research_engine.specialists.synthesis import synthesize
        synthesize(orch)
        synthesize(orch)
        after = store_fingerprint([pathlib.Path(orch.ws.db_path)])
        assert before == after


class TestFlagshipWorkflow:
    def setup_method(self):
        from research_engine.specialists.runtime import reset_registry
        reset_registry()

    def _boot(self, tmp_path):
        from research_engine.platform.events import EventBus
        from research_engine.platform.job_runners import (
            make_specialist_runner)
        from research_engine.platform.scheduler import (
            PersistentScheduler, SchedulerConfig)
        from research_engine.storage.platform_db import PlatformDB
        cfg = _cfg(pathlib.Path(tmp_path))
        cfg.storage.data_dir = str(tmp_path)
        from research_engine.core.orchestrator import Orchestrator
        orch = Orchestrator.create_project(
            cfg, "Find a startup opportunity from a soft-robotics "
                 "research gap", mode="startup")
        orch.repos.projects.save(orch.project)

        # seed evidence so every stage has material
        _seed_evidence(orch, [TECH, CUSTOMER, MARKET])

        db = PlatformDB(pathlib.Path(cfg.storage.data_dir))
        bus = EventBus()
        sched = PersistentScheduler(db, SchedulerConfig(
            worker_threads=1, poll_interval=0.02, lease_seconds=30,
            heartbeat_seconds=999))

        class Ctx:
            pass
        c = Ctx()
        c.cfg = cfg
        c.bus = bus
        c.platform_db = db
        runner = make_specialist_runner(c, cfg)
        sched.register_runner("SPECIALIST_TASK", lambda t: runner(t))
        return orch, db, sched

    def test_gap_to_startup_chain_with_handoffs(self, tmp_path):
        from research_engine.specialists.bootstrap import (
            ensure_builtin_specialists)
        ensure_builtin_specialists()
        from research_engine.specialists.workflows import run_flagship
        orch, db, sched = self._boot(pathlib.Path(tmp_path) / "d")
        sched.start()
        try:
            results = run_flagship(
                type("C", (), {"platform_db": db})(), orch.project.id,
                "soft robotics gap to startup", wait_fn=None)
        finally:
            pass
        # wait_fn polls internally; stop after completion
        time.sleep(0.1)
        sched.stop()
        assert len(results) == 3
        for r in results:
            task = r["task"]
            assert task.status == "SUCCEEDED", getattr(task, "error", "")
        # handoffs flowed: stage 2 and 3 tasks carry handoff payloads
        invocations = db.list_specialist_invocations(orch.project.id)
        by_sid = {i["specialist_id"]: i for i in invocations}
        assert set(by_sid) >= {"literature", "technology", "startup"}
        tech_task = results[1]["task"]
        assert (tech_task.payload or {}).get("handoff", {}).get(
            "source_specialist") == "literature"
        startup_task = results[2]["task"]
        ho = (startup_task.payload or {}).get("handoff", {})
        assert ho.get("source_specialist") == "technology"
        # literature's created evidence ids traveled into technology handoff
        lit_created = results[0]["task"].result.get("created", {})
        assert lit_created.get("gap_ids") or \
            lit_created.get("claim_ids") or \
            ho.get("evidence_ids")
