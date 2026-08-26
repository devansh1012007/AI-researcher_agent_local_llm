"""Phase 5 §19: builtin domain specialist pipelines (offline, deterministic).

Each builtin runs END-TO-END through the real SPECIALIST_TASK runner with a
seeded context pack — the same path production uses (§77 contract harness
covers every registered specialist).
"""
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


def _seed_startup_entities(orch):
    """Shared competitor/pricing entities (§53) for competitive+foresight."""
    from research_engine.specialists.startup.models import (
        CompetitorProfile, PricingPlan)
    from research_engine.specialists.startup.repos import get_startup_repos
    srepos = get_startup_repos(orch)
    pid = orch.project.id
    c = CompetitorProfile(project_id=pid, name="LedgerBot",
                          classification="direct", product="bookkeeping")
    c.ensure_id()
    srepos.competitor_profiles.save_natural(c)
    for price in ("15 dollars per month", "20 dollars per month"):
        p = PricingPlan(project_id=pid, competitor_name="LedgerBot",
                        tier_name="starter", price_raw=price,
                        billing_period="monthly")
        p.ensure_id()
        srepos.pricing_plans.save_natural(p)
    return srepos


def _seed_evidence(orch, items):
    from research_engine.models.evidence import Evidence
    from research_engine.models.research import Source
    pid = orch.project.id
    s = Source(project_id=pid, url="https://seed.example.com/1",
               canonical_url="https://seed.example.com/1",
               domain="seed.example.com", title="seed corpus")
    s.ensure_id()
    orch.repos.sources.save(s)
    for claim, quote in items:
        e = Evidence(project_id=pid, claim_text=claim, quote=quote,
                     source_id=s.id, source_tier=4,
                     status="EXTRACTED")
        e.ensure_id()
        orch.repos.evidence.save(e)


CORPUS = {
    "lit": [("The transformer method outperforms prior baselines on X.",
             "The transformer method outperforms prior baselines."),
            ("No public benchmark exists for this task family.",
             "there is no public benchmark for this task family.")],
    "tech": [("Deployment requires a GPU with 24GB VRAM minimum.",
              "requires a GPU with 24GB VRAM"),
             ("Integration with existing ERP systems is unsupported.",
              "integration with existing ERP systems is unsupported")],
    "comp": [("Reviewers compare it to an alternative called SheetWiz.",
              "an alternative called SheetWiz instead of spreadsheets"),
             ("LedgerBot raised pricing twice this year per reviews.",
              "raised pricing twice this year")],
    "fore": [("A new open-source model release cut costs sharply.",
              "new open-source model release cut costs sharply"),
             ("New regulation will require audit logs for bookkeeping AI.",
              "regulation will require audit logs")],
}


class _Ctx:
    pass


def _setup(tmp_path, question="Assess feasibility and market for "
                              "AI bookkeeping automation"):
    from research_engine.core.orchestrator import Orchestrator
    from research_engine.platform.events import EventBus
    from research_engine.platform.job_runners import make_specialist_runner
    from research_engine.platform.scheduler import (
        PersistentScheduler, SchedulerConfig)
    from research_engine.storage.platform_db import PlatformDB
    cfg = _cfg(pathlib.Path(tempfile.mkdtemp()))
    cfg.storage.data_dir = str(tmp_path)
    orch = Orchestrator.create_project(cfg, question, mode="startup")
    orch.repos.projects.save(orch.project)
    db = PlatformDB(pathlib.Path(cfg.storage.data_dir))
    bus = EventBus()
    seen: list = []
    import queue as _q
    _, ev_q = bus.subscribe()
    sched = PersistentScheduler(db, SchedulerConfig(
        worker_threads=1, poll_interval=0.02, lease_seconds=30,
        heartbeat_seconds=999))
    ctx = _Ctx()
    ctx.cfg = cfg
    ctx.bus = bus
    ctx.platform_db = db
    runner = make_specialist_runner(ctx, cfg)
    sched.register_runner("SPECIALIST_TASK", lambda t: runner(t))
    return orch, db, seen, ev_q, sched


def _submit_and_wait(db, sched, pid, sid, timeout=10):
    from research_engine.models.job import JobTask, ResearchJob
    job = ResearchJob(project_id=pid, type="SPECIALIST_TASK")
    db.save_job(job)
    db.add_task(JobTask(job_id=job.id, type="SPECIALIST_TASK",
                        resource_profile="CPU_LIGHT",
                        payload={"project_id": pid, "type":
                                 "SPECIALIST_TASK",
                                 "specialist_id": sid, "mode":
                                 "ANALYZE"}))
    sched.start()
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ts = db.tasks_for_job(job.id)
            if ts and ts[0].status in ("SUCCEEDED", "FAILED",
                                       "DEAD_LETTER"):
                break
            time.sleep(0.05)
    finally:
        sched.stop()
        time.sleep(0.03)
    return ts[0]


class TestBuiltinSpecialists:
    def setup_method(self):
        from research_engine.specialists.runtime import reset_registry
        reset_registry()

    def test_all_builtins_registered_and_healthy(self):
        from research_engine.specialists.bootstrap import (
            ensure_builtin_specialists)
        from research_engine.specialists.runtime import (
            HealthState, get_registry)
        ensure_builtin_specialists()
        reg = get_registry()
        ids = {r.descriptor.specialist_id for r in reg.list_active()}
        assert {"literature", "technology", "competitive", "foresight",
                "startup"} <= ids
        for r in reg.list_active():
            assert r.health.state == HealthState.AVAILABLE

    @pytest.mark.parametrize("sid,key", [
        ("literature", "lit"), ("technology", "tech"),
        ("competitive", "comp"), ("foresight", "fore"),
    ])
    def test_pipeline_end_to_end(self, tmp_path, sid, key):
        orch, db, seen, ev_q, sched = _setup(
            pathlib.Path(tmp_path) / "d")
        _seed_evidence(orch, CORPUS[key])
        if sid in ("competitive", "foresight"):
            _seed_startup_entities(orch)
        task = _submit_and_wait(db, sched, orch.project.id, sid)
        assert task.status == "SUCCEEDED", getattr(task, "error", "")
        result = task.result or {}
        out = result.get("output", {})
        assert out.get("specialist_id") == sid
        stages = [s["stage"] for s in
                  out.get("artifacts", {}).get("stages", [])]
        assert stages, f"{sid} produced no stage trail"

    def test_technology_flags_missing_cost_constraints(self, tmp_path):
        orch, db, seen, ev_q, sched = _setup(
            pathlib.Path(tmp_path) / "d")
        # only hardware+software evidence; cost/integration/deployment/
        # performance stay unknown → gaps must be created
        _seed_evidence(orch, CORPUS["tech"][:2])
        before_gaps = len(orch.repos.gaps.all(orch.project.id))
        task = _submit_and_wait(db, sched, orch.project.id, "technology")
        assert task.status == "SUCCEEDED"
        gaps = orch.repos.gaps.all(orch.project.id)
        assert len(gaps) > before_gaps
        joined = " ".join(g.description.lower() for g in gaps)
        assert "cost" in joined or "deployment" in joined

    def test_competitive_shares_startup_entities(self, tmp_path):
        orch, db, seen, ev_q, sched = _setup(
            pathlib.Path(tmp_path) / "d")
        _seed_evidence(orch, CORPUS["comp"])
        _seed_startup_entities(orch)
        task = _submit_and_wait(db, sched, orch.project.id, "competitive")
        assert task.status == "SUCCEEDED"
        findings_text = " ".join(f["text"] for f in
                                 task.result["output"]["findings"])
        assert "LedgerBot" in findings_text
        assert "1 competitor profiles; 2 pricing observations" in \
            findings_text

    def test_foresight_maps_trend_to_direction(self, tmp_path):
        orch, db, seen, ev_q, sched = _setup(
            pathlib.Path(tmp_path) / "d")
        _seed_evidence(orch, CORPUS["fore"])
        task = _submit_and_wait(db, sched, orch.project.id, "foresight")
        assert task.status == "SUCCEEDED"
        arts = task.result["output"]["artifacts"]
        trends = arts.get("trends", [])
        assert len(trends) >= 2
        directions = {t["direction"] for t in trends}
        assert "enabling" in directions

    def test_startup_adapter_runs_service_mode(self, tmp_path):
        orch, db, seen, ev_q, sched = _setup(
            pathlib.Path(tmp_path) / "d")
        _seed_evidence(orch, [
            ("Owners complain bookkeeping is manual weekly.",
             "complain bookkeeping is manual"),
            ("Zoho Books charges 15 dollars per month.",
             "charges 15 dollars per month")])
        GraphSeed = None
        try:
            from research_engine.storage.graph_store import (
                GraphEntity, GraphStore)
            GraphStore(orch.db).upsert_entity(GraphEntity(
                project_id=orch.project.id, type="competitor",
                name="Zoho Books",
                attributes={"product": "accounting software"}))
        except Exception:
            pass
        task = _submit_and_wait(db, sched, orch.project.id, "startup")
        assert task.status == "SUCCEEDED", getattr(task, "error", "")
        out = task.result["output"]
        assert out["specialist_id"] == "startup"
        arts = out["artifacts"]
        # Honest adapter contract: either portfolio entries OR an explicit
        # strengthen-evidence recommendation — never silent emptiness.
        if arts.get("count", 0) == 0:
            assert any("strengthen" in r["text"]
                       for r in out["recommendations"]), out
        else:
            assert out["findings"]
        assert arts["stages"][0]["stage"].startswith("service:")

    def test_capability_query_by_mode(self):
        from research_engine.specialists.bootstrap import (
            ensure_builtin_specialists)
        from research_engine.specialists.runtime import get_registry
        ensure_builtin_specialists()
        feas = [d.specialist_id for d in get_registry().capability_query(
            modes=["FEASIBILITY"])]
        assert feas == ["technology"]
