"""Flagship cross-specialist workflows (Phase 5 §25/§60/§79).

Chains SPECIALIST_TASK invocations through the normal scheduler; every
stage boundary is a structured Handoff carrying the previous stage's
created artifact ids — never transcripts.
"""
from __future__ import annotations

from research_engine.specialists.runtime import Handoff


def submit_stage(db, pid: str, specialist_id: str, stage_index: int,
                 mode: str = "ANALYZE", handoff: Handoff | None = None,
                 routing_reason: str = "") -> str:
    from research_engine.models.job import JobTask, ResearchJob
    job = ResearchJob(project_id=pid, type="SPECIALIST_TASK")
    db.save_job(job)
    payload = {"project_id": pid, "type": "SPECIALIST_TASK",
               "specialist_id": specialist_id,
               "mode": mode,
               "stage_index": stage_index,
               "routing_reason": routing_reason or f"workflow stage {stage_index}"}
    if handoff is not None:
        payload["handoff"] = handoff.model_dump()
    db.add_task(JobTask(job_id=job.id, type="SPECIALIST_TASK",
                        resource_profile="CPU_LIGHT", priority=10 + stage_index,
                        payload=payload))
    return job.id


def handoff_from_result(prev_specialist: str, next_specialist: str,
                        objective: str, result: dict) -> Handoff:
    created = (result or {}).get("created", {}) or {}
    out = (result or {}).get("output", {}) or {}
    open_q = [str(n.get("what", n) if isinstance(n, dict) else n)
              for n in (out.get("next_research") or [])][:5]
    return Handoff(
        source_specialist=prev_specialist,
        target_specialist=next_specialist,
        objective=objective[:300],
        evidence_ids=list(created.get("evidence_ids", []))[:20],
        claim_ids=list(created.get("claim_ids", []))[:20],
        constraints=[f.get("text", "")[:160]
                     for f in out.get("findings", [])
                     if isinstance(f, dict) and f.get("category")][:6],
        open_questions=open_q,
        required_output="feasibility+market assessment for synthesis",
    )


def run_flagship(ctx, pid: str, question: str,
                 wait_fn=None) -> list[dict]:
    """§60/§79 RESEARCH_GAP_TO_STARTUP: literature → technology → startup.

    `wait_fn(job_id) -> JobTask` polls the platform; stages run through the
    real scheduler so leases/fencing/budgets all apply."""
    stages = [("literature", "LITERATURE_REVIEW"),
              ("technology", "FEASIBILITY"),
              ("startup", "OPPORTUNITY_DISCOVERY")]
    results: list[dict] = []
    prev_handoff: Handoff | None = None
    for i, (sid, mode) in enumerate(stages):
        job_id = submit_stage(ctx.platform_db, pid, sid, i, mode=mode,
                              handoff=prev_handoff,
                              routing_reason=
                              "flagship RESEARCH_GAP_TO_STARTUP")
        task = (wait_fn or _default_wait(ctx))(job_id)
        results.append({"specialist": sid, "task": task})
        if task.status != "SUCCEEDED":
            break
        prev_handoff = handoff_from_result(
            sid, stages[i + 1][0] if i + 1 < len(stages) else "synthesis",
            question, task.result)
    return results


def _default_wait(ctx, timeout_s: float = 120.0):
    import time

    def wait(job_id: str):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            ts = ctx.platform_db.tasks_for_job(job_id)
            if ts and ts[0].status in ("SUCCEEDED", "FAILED",
                                       "DEAD_LETTER"):
                return ts[0]
            time.sleep(0.05)
        raise TimeoutError(f"workflow stage timed out: {job_id}")
    return wait
