"""Performance smoke benchmarks (spec #95/#147). Measure, don't guess.
These are regression tripwires, not micro-optimization targets."""
from __future__ import annotations

import time

import pytest

from research_engine.models.job import JobTask, ResourceProfile, ResearchJob
from research_engine.platform.scheduler import PersistentScheduler, SchedulerConfig
from research_engine.storage.platform_db import PlatformDB


def test_scheduler_throughput(platform_ctx):
    """Hundreds of tasks drain quickly with 4 workers on a laptop."""
    db = platform_ctx.platform_db
    n = 300
    job = ResearchJob(project_id="perf", type="maintenance")
    db.save_job(job)
    for i in range(n):
        db.add_task(JobTask(job_id=job.id, type="NOOP",
                            resource_profile=ResourceProfile.CPU_LIGHT))
    s = PersistentScheduler(db, SchedulerConfig(worker_threads=4,
                                                poll_interval=0.01))
    s.register_runner("NOOP", lambda t: {})
    t0 = time.time()
    s.start()
    deadline = time.time() + 60
    while time.time() < deadline:
        if db.get_job(job.id).is_terminal():
            break
        time.sleep(0.05)
    dur = time.time() - t0
    s.stop()
    assert db.get_job(job.id).status == "COMPLETED"
    rate = n / max(dur, 0.001)
    assert rate > 50, f"scheduler too slow: {rate:.0f} tasks/s"


def test_platform_db_claim_latency(platform_ctx):
    db = platform_ctx.platform_db
    for i in range(200):
        db.add_task(JobTask(job_id="jlat", type="X",
                            resource_profile=ResourceProfile.CPU_LIGHT))
    caps = {ResourceProfile.CPU_LIGHT: 500}
    t0 = time.time()
    claimed = 0
    while True:
        t = db.claim_next_task("w", caps, lease_seconds=60)
        if t is None:
            break
        claimed += 1
    per_op_ms = (time.time() - t0) * 1000 / max(1, claimed)
    assert claimed == 200
    assert per_op_ms < 25, f"claim latency {per_op_ms:.1f}ms/op too high"


def test_project_db_query_latency(platform_ctx, make_orchestrator):
    """Evidence listing stays fast with hundreds of rows (spec #147)."""
    orch = make_orchestrator("Performance baseline project for query latency")
    from research_engine.models.evidence import Evidence
    from research_engine.models.enums import SourceType
    for i in range(400):
        ev = Evidence(project_id=orch.project.id,
                          source_id=f"src_{i:04d}",
                          claim_text=f"claim number {i} about topic",
                          quote=f"verbatim quote text {i} from source",
                          chunk_id=f"chk_{i:04d}", source_tier=3)
        ev.ensure_id()
        orch.repos.evidence.save(ev)
    t0 = time.time()
    items = orch.repos.evidence.all(orch.project.id)
    list_latency = (time.time() - t0) * 1000
    assert len(items) >= 400
    assert list_latency < 500, f"evidence scan {list_latency:.0f}ms too slow"

    t0 = time.time()
    orch.repos.evidence.count(orch.project.id, "status!='REJECTED'")
    count_latency = (time.time() - t0) * 1000
    assert count_latency < 250


def test_memory_bounded_under_load(platform_ctx):
    """Long scheduler run must not leak tasks or balloon state (#96)."""
    import resource
    db = platform_ctx.platform_db
    job = ResearchJob(project_id="mem", type="maintenance")
    db.save_job(job)
    for i in range(150):
        db.add_task(JobTask(job_id=job.id, type="NOOP",
                            resource_profile=ResourceProfile.CPU_LIGHT))
    s = PersistentScheduler(db, SchedulerConfig(worker_threads=3,
                                                poll_interval=0.01))
    s.register_runner("NOOP", lambda t: {"x": "y" * 100})
    s.start()
    deadline = time.time() + 30
    while time.time() < deadline and not db.get_job(job.id).is_terminal():
        time.sleep(0.05)
    s.stop()
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    assert rss_mb < 800, f"RSS {rss_mb:.0f}MB suggests unbounded growth"
