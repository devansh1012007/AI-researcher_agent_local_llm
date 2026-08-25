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


def make_deep_research_runner(cfg, bus: EventBus | None = None):
    """Factory returning a runner fn(task) -> dict for deep_research jobs.

    The task payload carries project_id. Cooperative control flags are read
    from the scheduler via closure (`control_fn(job_id) -> PAUSE|CANCEL|None`).
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
        log.info("deep_research_done", project_id=pid, job_id=job_id,
                 duration_ms=dur * 1000, metadata={k: final[k] for k in
                                                   ("state", "stop_reason", "evidence")})
        return final

    return runner


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
