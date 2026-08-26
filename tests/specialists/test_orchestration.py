"""Phase 5 §6–§9, §42–§44: routing, composition, SPECIALIST_TASK
execution through the real scheduler, cycle guard, budgets, handoffs."""
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


def _project(tmp_path, question, mode="academic"):
    from research_engine.core.orchestrator import Orchestrator
    orch = Orchestrator.create_project(_cfg(tmp_path), question, mode=mode)
    orch.repos.projects.save(orch.project)
    return orch


# ---------------------------------------------------------------- routing

class TestHybridRouting:
    def test_rules_select_with_reasons(self):
        from research_engine.specialists.routing import route
        sels = route(
            "Which research gaps in soft robotics could become a startup? "
            "Assess technical feasibility and market demand.")
        ids = [s.specialist_id for s in sels]
        assert "literature" in ids and "technology" in ids \
            and "startup" in ids
        lit = next(s for s in sels if s.specialist_id == "literature")
        assert "matched domain signals" in lit.reason and lit.reason

    def test_no_signals_selects_nothing(self):
        from research_engine.specialists.routing import route
        assert route("Hello there.") == []

    def test_llm_veto_applied(self):
        from research_engine.specialists.routing import (
            RouteAnnotation, RouteVeto, route)

        class FakeLLM:
            def structured(self, system, user, model):
                return RouteAnnotation(
                    veto=[RouteVeto(id="startup", reason="not relevant")])

        sels = route("market opportunity for grippers",
                     llm=FakeLLM(), max_specialists=5)
        assert "startup" not in [s.specialist_id for s in sels]

    def test_llm_failure_fails_open_to_rules(self):
        from research_engine.specialists.routing import route

        class DeadLLM:
            def structured(self, *a, **k):
                raise RuntimeError("ollama down")

        sels = route("technical feasibility of the gripper design",
                     llm=DeadLLM())
        assert "technology" in [s.specialist_id for s in sels]

    def test_max_specialists_limit(self):
        from research_engine.specialists.routing import route
        q = ("paper feasibility market competitor trend customer pricing "
             "benchmark constraint trend regulation")
        assert len(route(q)) <= 5


# ------------------------------------------------------------ plan/guard

class TestPlannerAndGainGuard:
    def test_template_orders_flagship(self):
        from research_engine.specialists.planner import build_plan
        from research_engine.specialists.routing import Selection
        sels = [Selection("startup", "r"), Selection("technology", "r"),
                Selection("literature", "r")]
        stages = build_plan(sels, "find a startup opportunity from a "
                                   "research gap")
        assert [s.specialist_id for s in stages] == \
            ["literature", "technology", "startup"]

    def test_gain_guard_blocks_zero_gain_reinvocation(self):
        from research_engine.specialists.planner import gain_guard
        prior = [{"specialist_id": "technology",
                  "evidence_count": 10, "created_at": "t1"}]
        assert gain_guard("technology", 10, prior) != ""
        assert gain_guard("technology", 12, prior) == ""
        assert gain_guard("startup", 10, prior) == ""  # never ran

    def test_max_specialists_cap_enforced(self):
        from research_engine.specialists.planner import (
            MAX_SPECIALISTS_PER_PROJECT, build_plan)
        from research_engine.specialists.routing import Selection
        many = [Selection(f"s{i}", "r") for i in range(9)]
        stages = build_plan(many, "generic question here")
        assert len(stages) <= MAX_SPECIALISTS_PER_PROJECT


# ------------------------------------------------------- end-to-end run

class _FakeSpecialist:
    """Domain logic via the API seam ONLY (spec §35/§86)."""

    def __init__(self, calls: dict):
        self.calls = calls

    def __call__(self, rc):
        from research_engine.specialists.runtime import SpecialistOutput
        self.calls["question"] = rc.context_pack.get("question", "")
        if self.calls.get("create", True):
            res = rc.api.create_evidence(
                claim_text="Soft grippers handle delicate produce reliably",
                quote="Soft grippers handle delicate produce reliably.",
                chunk_text="Field trials show soft grippers handle delicate "
                           "produce reliably without bruising.",
                source_id="src_probe", source_tier=4)
            self.calls["evidence_status"] = res["status"]
        if self.calls.get("submit_followup") and rc.api._task_submitter:
            rc.api.submit_research_task({
                "specialist_id": "probe_b", "mode": "ANALYZE"})
        return SpecialistOutput(
            specialist_id=rc.descriptor.specialist_id,
            version=rc.descriptor.version,
            findings=[{"text": "gripper gap confirmed"}],
            confidence={"feasibility": 0.6},
            next_research=[{"what": "produce-supplier pain"}])


def _register_probe(sid="probe_a", max_llm=5, calls=None):
    from research_engine.specialists.runtime import (
        SpecialistBudget, SpecialistDescriptor, get_registry)
    d = SpecialistDescriptor(
        specialist_id=sid, name=f"P{sid}", version="1.0",
        supported_modes=["ANALYZE"], skills=[],
        entity_types=[], budgets=SpecialistBudget(max_llm_calls=max_llm),
        permissions={"READ_PROJECT", "READ_EVIDENCE", "CREATE_EVIDENCE",
                     "CREATE_RESEARCH_TASK"})
    reg = get_registry().register(d, _FakeSpecialist(calls if calls is not None else {}))
    return reg.descriptor


def _mk_scheduler(tmp_path, cfg):
    from research_engine.platform.events import EventBus
    from research_engine.platform.job_runners import make_specialist_runner
    from research_engine.platform.scheduler import (
        PersistentScheduler, SchedulerConfig)
    from research_engine.storage.platform_db import PlatformDB
    db = PlatformDB(pathlib.Path(cfg.storage.data_dir))
    bus = EventBus()
    import queue as _q
    seen: list = []
    sub_id, ev_q = bus.subscribe()          # all events
    sched = PersistentScheduler(db, SchedulerConfig(
        worker_threads=1, poll_interval=0.02, lease_seconds=30,
        heartbeat_seconds=999))

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.cfg = cfg
    ctx.bus = bus
    ctx.platform_db = db
    runner = make_specialist_runner(ctx, cfg)
    sched.register_runner("SPECIALIST_TASK", lambda t: runner(t))

    def _drain():
        while True:
            try:
                seen.append(ev_q.get_nowait())
            except _q.Empty:
                return

    orig_stop = sched.stop

    def stop_and_drain():
        orig_stop()
        time.sleep(0.05)
        _drain()

    sched.stop = stop_and_drain
    return db, bus, seen, sched


def _submit(db, pid, sid, **payload_extra):
    from research_engine.models.job import JobTask, ResearchJob
    job = ResearchJob(project_id=pid, type="SPECIALIST_TASK")
    payload = {"project_id": pid, "type": "SPECIALIST_TASK",
               "specialist_id": sid, "mode": "ANALYZE"}
    payload.update(payload_extra)
    db.save_job(job)
    db.add_task(JobTask(job_id=job.id, type="SPECIALIST_TASK",
                        resource_profile="CPU_LIGHT", payload=payload))
    return job.id


class TestEndToEndInvocation:
    def setup_method(self):
        from research_engine.specialists.runtime import reset_registry
        reset_registry()

    def _run_one(self, tmp_path, question, calls, extra=None, sid="probe_a"):
        cfg = _cfg(pathlib.Path(tempfile.mkdtemp()))
        cfg.storage.data_dir = str(tmp_path)
        orch = _project(pathlib.Path(cfg.storage.data_dir), question)
        _register_probe(calls=calls)
        db, bus, seen, sched = _mk_scheduler(
            pathlib.Path(cfg.storage.data_dir), cfg)
        jid = _submit(db, orch.project.id, sid, **(extra or {}))
        sched.start()
        try:
            deadline = time.time() + 10
            while time.time() < deadline:
                ts = db.tasks_for_job(jid)
                if ts and ts[0].status in ("SUCCEEDED", "FAILED",
                                           "DEAD_LETTER"):
                    break
                time.sleep(0.05)
        finally:
            sched.stop()
        return db, seen, orch, ts[0]

    def test_full_invocation_lifecycle_and_artifacts(self, tmp_path):
        calls = {}
        db, seen, orch, task = self._run_one(
            tmp_path, "Soft robotics research gaps for produce handling",
            calls, extra={"handoff": {
                "source_specialist": "literature",
                "target_specialist": "probe_a",
                "objective": "assess gripper feasibility",
                "evidence_ids": []}})
        assert task.status == "SUCCEEDED", getattr(task, "error", "")
        assert calls["question"].startswith("Soft robotics")
        # grounded artifact persisted with verdict
        rows = orch.repos.evidence.all(orch.project.id)
        assert any(r.support_verdict for r in rows)
        kinds = {e.type for e in seen}
        assert {"SpecialistStarted", "SpecialistCompleted"} <= kinds
        perf = db.list_specialist_perf("probe_a")
        assert perf and perf[0]["runs"] == 1 and perf[0]["failures"] == 0

    def test_cycle_guard_skips_second_zero_gain_run(self, tmp_path):
        calls = {}
        cfgd = pathlib.Path(tempfile.mkdtemp())
        cfg = _cfg(cfgd)
        cfg.storage.data_dir = str(cfgd)
        orch = _project(cfgd, "Soft robotics gaps question")
        _register_probe(calls=calls)
        db, bus, seen, sched = _mk_scheduler(cfgd, cfg)

        def run_once(create: bool):
            calls["create"] = create
            jid = _submit(db, orch.project.id, "probe_a")
            sched.start()
            deadline = time.time() + 10
            while time.time() < deadline:
                ts = db.tasks_for_job(jid)
                if ts and ts[0].status in ("SUCCEEDED", "FAILED",
                                           "DEAD_LETTER"):
                    break
                time.sleep(0.05)
            sched.stop()
            return ts[0]

        first = run_once(True)
        assert first.status == "SUCCEEDED"
        second = run_once(False)   # zero research gain → guard must trip
        result = second.result or {}
        assert second.status == "SUCCEEDED" and \
            result.get("status") == "SKIPPED" and \
            "cycle-guard" in str(result.get("reason", "")), result

    def test_budget_exhaustion_fails_task_loudly(self, tmp_path):
        from research_engine.specialists.runtime import (
            InvocationBudget, SpecialistBudget)

        calls = {}

        def greedy(rc):
            llm = rc.api.reasoning_llm()
            llm.structured("s", "u", dict)
            llm.structured("s", "u", dict)   # cap is 1 → must raise
            raise AssertionError("budget not enforced")

        from research_engine.specialists.runtime import (
            SpecialistDescriptor, get_registry)
        get_registry().register(SpecialistDescriptor(
            specialist_id="greedy", name="G", version="1.0",
            supported_modes=["ANALYZE"],
            budgets=SpecialistBudget(max_llm_calls=1),
            permissions={"READ_PROJECT"}), greedy)
        db, seen, orch, task = self._run_one(
            tmp_path, "some neutral question text", calls, sid="greedy")
        assert task.status in ("DEAD_LETTER", "FAILED"), (
            f"budget violation not enforced: {task.status} "
            f"{getattr(task, 'error', '')}")
        perf = db.list_specialist_perf("greedy")
        assert perf and perf[0]["runs"] >= 1
        assert perf[0]["failures"] == perf[0]["runs"], (
            "every budget-exhausted invocation must count as a failure")

    def test_followup_task_created_via_permissioned_api(self, tmp_path):
        calls = {"submit_followup": True}
        cfgd = pathlib.Path(tempfile.mkdtemp())
        cfg = _cfg(cfgd)
        cfg.storage.data_dir = str(cfgd)
        orch = _project(cfgd, "followup probe question")
        _register_probe(calls=calls)
        _register_probe("probe_b")
        db, seen, _, sched = _mk_scheduler(cfgd, cfg)
        jid = _submit(db, orch.project.id, "probe_a")
        sched.start()
        try:
            deadline = time.time() + 10
            while time.time() < deadline:
                jobs = db.incomplete_jobs() if hasattr(
                    db, "incomplete_jobs") else []
                ts = db.tasks_for_job(jid)
                if ts and ts[0].status in ("SUCCEEDED", "FAILED",
                                           "DEAD_LETTER"):
                    break
                time.sleep(0.05)
        finally:
            sched.stop()
        assert ts[0].status == "SUCCEEDED"
        hist = db.list_specialist_invocations(orch.project.id)
        assert any(h.get("specialist_id") == "probe_b"
                   for h in hist), "follow-up specialist task missing"


def _last_job_of(db, pid):
    jobs = db.list_jobs(limit=50)
    mine = [j for j in jobs if j.project_id == pid]
    return mine[-1].id
