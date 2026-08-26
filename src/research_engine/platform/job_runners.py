"""Job runners: connect scheduler tasks to research-engine work.

A runner receives a claimed JobTask and does the actual work:
  - deep_research: full orchestrator run (long-running, cooperative pause/cancel)
  - incremental_update / watcher_tick: watcher-driven incremental research
  - experiment: sandboxed local experiment execution
  - report: asynchronous report regeneration

Runners are registered on a PersistentScheduler; they never touch SQLite
directly — all persistence goes through the orchestrator/repos/services.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from research_engine.models.job import (
    CompletionReason, JobStatus, JobTask,
)
from research_engine.platform.events import DomainEvent, EventBus
from research_engine.platform.metrics import GlobalMetrics
from research_engine.platform.obs_logging import platform_logger


def make_deep_research_runner(cfg, bus: EventBus | None = None,
                              platform_db=None):
    """Factory returning a runner fn(task) -> dict for deep_research jobs.

    The task payload carries project_id. Cooperative control flags are read
    from the scheduler via closure (`control_fn(job_id) -> PAUSE|CANCEL|None`).
    When `platform_db` is supplied, a Phase 6 research-outcome record is
    written at run end (§6) — measurement only; it never affects the run.
    """
    from research_engine.core.config import AppConfig
    cfg = cfg or AppConfig.load()
    bus = bus or EventBus()

    def runner(task: JobTask, control_fn=None) -> dict:
        from research_engine.core.orchestrator import Orchestrator
        log = platform_logger()
        metrics = GlobalMetrics.get().registry
        pid = task.payload.get("project_id") or task.project_id
        orch = Orchestrator.load(cfg, pid)
        job_id = task.job_id
        orch.trace_id = f"job_{job_id}"
        t0 = time.time()
        started_iso = datetime.now(timezone.utc).isoformat()
        bus.publish(DomainEvent("ResearchStarted", project_id=pid, job_id=job_id,
                                payload={"question": orch.project.question_raw}))
        stop_reason = None
        while True:
            flag = control_fn(job_id) if control_fn else None
            if flag == "CANCEL":
                orch.request_stop()
                stop_reason = CompletionReason.USER_STOPPED
                break
            if flag == "PAUSE":
                orch.request_pause()
            p = orch.run()
            if p.state.name == "PAUSED":
                return {"status": "PAUSED", "iteration": p.current_iteration}
            break
        dur = time.time() - t0
        metrics.observe("research_duration_s", dur)
        metrics.incr("research_runs", mode=orch.project.mode)
        final = {
            "status": "COMPLETED" if not stop_reason else "STOPPED",
            "state": orch.project.state.value,
            "stop_reason": (stop_reason or (orch.project.stop_reason.value
                            if orch.project.stop_reason else "")),
            "iteration": orch.project.current_iteration,
            "duration_s": round(dur, 1),
            "evidence": orch.repos.evidence.count(pid, "status!='REJECTED'"),
            "claims": orch.repos.claims.count(pid),
            "gaps_open": orch.repos.gaps.count(pid, "resolved=0"),
        }
        ev_type = "ResearchCompleted"
        payload = {**final}
        if orch.project.state.value == "FAILED":
            ev_type = "ResearchFailed"
        elif stop_reason == CompletionReason.USER_STOPPED:
            payload["status"] = "USER_STOPPED"
        bus.publish(DomainEvent(ev_type, project_id=pid, job_id=job_id,
                                payload=payload))
        # ---- Phase 6 §6: record the structured outcome (measurement only)
        if platform_db is not None:
            try:
                _record_outcome(platform_db, orch, pid, job_id, dur,
                                started_iso)
            except Exception:
                log.warning("outcome recording failed", project_id=pid,
                            metadata={}, exc_info=True)
        log.info("deep_research_done", project_id=pid, job_id=job_id,
                 duration_ms=dur * 1000, metadata={k: final[k] for k in
                                                   ("state", "stop_reason", "evidence")})
        return final

    return runner


def _record_outcome(platform_db, orch, pid: str, job_id: str,
                    duration_s: float, started_iso: str) -> None:
    """Build + persist the §6 outcome row and per-family/source aggregates."""
    from research_engine.adaptive.outcomes import (
        build_outcome, record_query_analytics, record_source_analytics)
    from research_engine.adaptive.policies import (
        POLICY_QUERY, POLICY_ROUTING, ensure_baseline_policies)
    from research_engine.adaptive.stopping import recommend_next_action
    ensure_baseline_policies(platform_db)
    policy_versions = {}
    for kind in (POLICY_ROUTING, POLICY_QUERY):
        pol = platform_db.active_policy(kind)
        if pol:
            policy_versions[kind] = pol["version"]
    specialists_used = sorted({
        p.get("specialist_id") for p in
        platform_db.list_specialist_invocations(pid)
        if p.get("specialist_id")})
    mode = getattr(orch.project, "mode", "") or "generic"
    bucket = ""
    outcome, feats = build_outcome(
        orch, pid, job_id, mode, duration_s,
        policy_versions=policy_versions, started_at_iso=started_iso)
    outcome["specialists_used"] = specialists_used
    try:
        from research_engine.adaptive.features import domain_bucket as _bucket
        bucket = _bucket(outcome["question"])
        decision = recommend_next_action(orch, pid)
        outcome["final_decision"] = {
            "next_action": decision["action"],
            "rationale": decision["rationale"],
        }
    except Exception:
        pass
    platform_db.save_outcome(
        outcome["outcome_id"], pid, job_id, outcome["research_type"],
        outcome["fingerprint"], outcome)
    task_type = f"{mode}:{bucket}" if bucket else mode
    if task_type == "generic":
        task_type = mode or "generic"
    record_query_analytics(platform_db, orch, pid, mode or "generic")
    record_source_analytics(platform_db, orch, pid, bucket)


def make_experiment_runner(cfg, control_fn=None):
    """Runner for experiment jobs — delegates to the sandboxed local runner."""
    def runner(task: JobTask, control_fn=None) -> dict:
        from research_engine.experiments.runner import LocalExperimentRunner
        r = LocalExperimentRunner(cfg)
        return r.execute_registered(
            task.payload["project_id"],
            task.payload["experiment_id"])
    return runner


def make_report_runner(cfg):
    """Asynchronous report regeneration (spec #84)."""
    def runner(task: JobTask, control_fn=None) -> dict:
        from research_engine.core.config import AppConfig
        c = cfg or AppConfig.load()
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.reports.generator import ReportGenerator
        pid = task.payload.get("project_id") or task.project_id
        orch = Orchestrator.load(c, pid)
        gen = ReportGenerator(c, orch.router.synthesis, orch.repos, orch.ws)
        generated = gen.generate_all(orch.project)
        return {"reports": generated}
    return runner


def make_specialist_runner(ctx, cfg=None):
    """Phase 5 §42–§44: execute ONE specialist invocation as a normal
    platform task (fenced, budgeted, audited). The specialist receives a
    RunContext whose `api` is the only seam to project state."""
    from research_engine.core.config import AppConfig
    c = cfg or AppConfig.load()
    bus = ctx.bus

    def runner(task: JobTask, control_fn=None) -> dict:
        import time as _t
        from research_engine.core.orchestrator import Orchestrator
        from research_engine.specialists.api import SpecialistApi
        from research_engine.specialists.context_pack import (
            assemble_context_pack)
        from research_engine.specialists.planner import gain_guard
        from research_engine.specialists.runtime import (
            BudgetExceeded, Handoff, InvocationBudget, LifecycleState,
            RunContext, SpecialistOutput, get_registry)

        payload = task.payload or {}
        pid = payload.get("project_id") or task.project_id
        sid = payload["specialist_id"]
        version = payload.get("version")
        mode = payload.get("mode", "ANALYZE")
        params = payload.get("params", {}) or {}
        handoff = Handoff(**payload["handoff"]) if payload.get("handoff") \
            else None
        routing_reason = payload.get("routing_reason", "")

        registry = get_registry()
        try:
            # idempotent: builtin specialists self-register on first use
            from research_engine.specialists.bootstrap import (
                ensure_builtin_specialists)
            ensure_builtin_specialists(registry)
        except Exception:
            pass
        reg = registry.lookup(sid, version)
        if reg is None or reg.health.state.value == "RETIRED":
            raise ValueError(f"specialist not available: {sid}@{version}")
        desc = reg.descriptor

        orch = Orchestrator.load(c, pid)
        platform_db = ctx.platform_db

        # §67 cycle-gain guard BEFORE any work. Gain is measured against the
        # PREVIOUS run's post-invocation count (`evidence_after`), i.e., how
        # much genuinely new knowledge exists since that specialist last ran.
        ev_now = len(orch.repos.evidence.all(pid))
        prior = [p for p in platform_db.list_specialist_invocations(pid)
                 if p.get("status") in ("SUCCEEDED", "SKIPPED")]
        last_ev = max((int(p.get("evidence_after")
                           if p.get("evidence_after") is not None
                           else p.get("evidence_count") or 0)
                       for p in prior), default=None)
        if prior and last_ev is not None:
            skip = gain_guard(sid, ev_now,
                              [{"specialist_id": sid,
                                "evidence_count": last_ev,
                                "created_at": "z"}])
            if skip:
                reg.transition(LifecycleState.BLOCKED, skip)
                bus.publish(DomainEvent(
                    "SpecialistSkipped", project_id=pid,
                    payload={"specialist": sid, "reason": skip}))
                return {"status": "SKIPPED", "reason": skip}

        budget = InvocationBudget(desc.budgets)

        def _submit(spec_request: dict):
            from research_engine.models.job import JobTask, ResearchJob
            job = ResearchJob(project_id=pid, type="SPECIALIST_TASK")
            sub = JobTask(job_id=job.id, type="SPECIALIST_TASK",
                          resource_profile="CPU_LIGHT",
                          payload={
                              "project_id": pid,
                              "type": "SPECIALIST_TASK",
                              "specialist_id": spec_request.get(
                                  "specialist_id", ""),
                              "mode": spec_request.get("mode", "ANALYZE"),
                              "params": spec_request.get("params", {}),
                              "handoff": spec_request.get("handoff"),
                              "routing_reason":
                                  "follow-up via CREATE_RESEARCH_TASK",
                              "evidence_count_before": ev_now,
                          })
            platform_db.save_job(job)
            platform_db.add_task(sub)
            return sub

        api = SpecialistApi(orch, set(desc.permissions), budget,
                            specialist_id=sid, version=desc.version,
                            task_id=task.id, task_submitter=_submit)
        pack = assemble_context_pack(orch, handoff,
                                     max_documents=desc.budgets.max_documents)
        rc = RunContext(orch=orch, api=api, descriptor=desc, mode=mode,
                        params=params, handoff=handoff, context_pack=pack,
                        budget=budget, selection_reason=routing_reason)

        reg.transition(LifecycleState.RUNNING,
                       routing_reason or "selected by router")
        bus.publish(DomainEvent(
            "SpecialistStarted", project_id=pid,
            payload={"specialist": sid, "version": desc.version,
                     "mode": mode, "reason": routing_reason,
                     "task_id": task.id}))
        t0 = _t.time()
        try:
            out = reg.invoke(rc)
            if not isinstance(out, SpecialistOutput):
                out = SpecialistOutput.model_validate(out)
        except BudgetExceeded as exc:
            dur = _t.time() - t0
            platform_db.record_specialist_perf(
                sid, desc.version, mode, ok=False, latency_s=dur,
                llm_calls=budget.llm_calls_used,
                queries=budget.queries_used,
                documents=budget.documents_used)
            reg.transition(LifecycleState.BLOCKED, f"budget: {exc}")
            bus.publish(DomainEvent(
                "SpecialistBudgetExhausted", project_id=pid,
                payload={"specialist": sid, "detail": str(exc)}))
            raise
        except Exception as exc:
            dur = _t.time() - t0
            platform_db.record_specialist_perf(
                sid, desc.version, mode, ok=False, latency_s=dur)
            reg.transition(LifecycleState.FAILED, str(exc)[:200])
            bus.publish(DomainEvent(
                "SpecialistFailed", project_id=pid,
                payload={"specialist": sid, "error": str(exc)[:300]}))
            raise
        dur = _t.time() - t0
        platform_db.record_specialist_perf(
            sid, desc.version, mode, ok=True, latency_s=dur,
            llm_calls=budget.llm_calls_used, queries=budget.queries_used,
            documents=budget.documents_used)
        reg.transition(LifecycleState.COMPLETED)
        ev_after = len(orch.repos.evidence.all(pid))
        # persist post-run evidence count so the NEXT run's gain guard
        # measures genuine research gain (§67)
        try:
            task.payload = dict(task.payload or {})
            task.payload["evidence_after"] = ev_after
            platform_db.update_task(task)
        except Exception:
            pass
        bus.publish(DomainEvent(
            "SpecialistCompleted", project_id=pid,
            payload={"specialist": sid, "duration_s": round(dur, 2),
                     "new_evidence": ev_after - ev_now,
                     "task_id": task.id}))
        return {"status": "SUCCEEDED", "specialist": sid,
                "output": out.model_dump(),
                "budget": budget.snapshot(),
                "created": dict(api.created),
                "evidence_count_after": ev_after}

    return runner
