"""INVARIANT-001/002: single-writer task ownership.

Regression tests for audit finding BUG-01 (scheduler double execution).
The ORIGINAL adversarial reproduction must show exactly-once execution.
"""
from __future__ import annotations

import tempfile
import pathlib
import threading
import time

import pytest

from research_engine.models.job import ResearchJob, JobTask, TaskStatus
from research_engine.platform.scheduler import PersistentScheduler, SchedulerConfig
from research_engine.storage.platform_db import PlatformDB, StaleTaskOwner


def _mk_db(tmp_path=None):
    return PlatformDB(pathlib.Path(tempfile.mkdtemp()) / "data")


def _one_task_job(db, ttype="WORK", profile="GENERIC", max_attempts=1):
    job = ResearchJob(project_id="p", type="maintenance")
    db.save_job(job)
    db.add_task(JobTask(job_id=job.id, type=ttype,
                        resource_profile=profile, max_attempts=max_attempts))
    return job


class TestOriginalReproduction:
    def test_bug01_slow_task_not_double_executed(self):
        """ORIGINAL AUDIT REPRO: 2 workers, runtime(4s) >> lease(2s),
        LLM_LARGE cap=1. Before the fix this executed TWICE."""
        db = _mk_db()
        _one_task_job(db, ttype="DEEP_RESEARCH", profile="LLM_LARGE")
        runs = []

        def slow(t):
            runs.append(threading.get_ident())
            time.sleep(4.0)
            return {"ok": True}

        cfg = SchedulerConfig(worker_threads=2, poll_interval=0.05,
                              lease_seconds=2.0, heartbeat_seconds=9999.0)
        s = PersistentScheduler(db, cfg)
        s.register_runner("DEEP_RESEARCH", slow)
        s.start()
        time.sleep(7)
        s.stop()
        assert len(runs) == 1, f"task executed {len(runs)} times"
        ts = db.tasks_for_job(db.list_jobs()[0].id)
        assert ts[0].status == "SUCCEEDED"
        assert ts[0].attempts == 1


class TestFencing:
    def test_stale_fence_cannot_finish(self):
        db = _mk_db()
        job = _one_task_job(db)
        t1 = db.claim_next_task("w1", {"GENERIC": 5}, lease_seconds=60)
        assert t1 is not None and t1.attempts == 1
        # owner w1 loses the lease (simulated crash); w2 reclaims
        t1.lease_expires_at = None
        db.update_task(db.get_task(t1.id))
        row = db._conn().execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (t1.id,))
        t2 = db.claim_next_task("w2", {"GENERIC": 5}, lease_seconds=60)
        assert t2 is not None and t2.attempts == 2
        # stale worker w1 (fence 1) attempts terminal write -> rejected loudly
        with pytest.raises(StaleTaskOwner) as exc:
            db.finish_task(t1.id, "w1", ok=True, result={}, fence=1)
        assert exc.value.expected_fence == 2 and exc.value.received_fence == 1
        # current owner finishes fine with its fence
        out = db.finish_task(t2.id, "w2", ok=True, result={}, fence=2)
        assert out.status == "SUCCEEDED"

    def test_stale_worker_id_cannot_finish(self):
        db = _mk_db()
        _one_task_job(db)
        t = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        with pytest.raises(StaleTaskOwner):
            db.finish_task(t.id, "w2", ok=True, result={})
        # unfenced-but-wrong-owner is still rejected (ownership check)

    def test_terminal_task_cannot_be_finished_again(self):
        db = _mk_db()
        _one_task_job(db)
        t = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        db.finish_task(t.id, "w1", ok=True, result={}, fence=t.attempts)
        with pytest.raises(StaleTaskOwner):
            db.finish_task(t.id, "w1", ok=True, result={}, fence=t.attempts)

    def test_same_worker_old_fence_cannot_finish(self):
        """Fence check is independent of worker identity: the SAME worker
        reclaiming its own task gets a NEW fence; writes carrying the old
        fence must be rejected (kills mutation M-5)."""
        db = _mk_db()
        _one_task_job(db)
        t1 = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        old_fence = t1.attempts
        # expire + reclaim by the SAME worker -> attempts bumps to 2
        db._conn().execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (t1.id,))
        t2 = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        assert t2.attempts == old_fence + 1
        with pytest.raises(StaleTaskOwner) as exc:
            db.finish_task(t2.id, "w1", ok=True, result={}, fence=old_fence)
        assert exc.value.expected_fence == t2.attempts
        # current fence succeeds
        out = db.finish_task(t2.id, "w1", ok=True, result={}, fence=t2.attempts)
        assert out.status == "SUCCEEDED"

    def test_stale_heartbeat_rejected_by_fence(self):
        db = _mk_db()
        _one_task_job(db)
        t = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        assert db.heartbeat(t.id, "w1", 60, fence=t.attempts) is True
        # steal via expiry; old fence now stale
        db._conn().execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (t.id,))
        t2 = db.claim_next_task("w2", {"GENERIC": 5}, 60)
        assert db.heartbeat(t.id, "w1", 60, fence=t.attempts) is False
        assert db.heartbeat(t.id, "w2", 60, fence=t2.attempts) is True

    def test_release_is_owner_checked(self):
        db = _mk_db()
        _one_task_job(db)
        t = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        with pytest.raises(StaleTaskOwner):
            db.release_task(t.id, "w2", fence=t.attempts)
        assert db.release_task(t.id, "w1", fence=t.attempts) is True
        assert db.get_task(t.id).status == "QUEUED"


class TestSchedulerInvariants:
    def test_dead_owner_lease_recovered_exactly_once(self):
        """Worker 'dies' (no renewal). Reclaim happens. Late write from the
        corpse is rejected. Net: exactly one successful execution."""
        db = _mk_db()
        _one_task_job(db)
        t1 = db.claim_next_task("dead", {"GENERIC": 5}, 60)
        # simulate death: expire the lease without any renewal
        db._conn().execute(
            "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (t1.id,))
        t2 = db.claim_next_task("live", {"GENERIC": 5}, 60)
        assert t2.attempts > t1.attempts
        try:
            db.finish_task(t1.id, "dead", ok=True, result={"late": True},
                           fence=t1.attempts)
            raised = False
        except StaleTaskOwner:
            raised = True
        assert raised
        out = db.finish_task(t2.id, "live", ok=True, result={}, fence=t2.attempts)
        assert out.status == "SUCCEEDED"
        # exactly one SUCCEEDED record exists
        rows = [x for x in db.tasks_for_job(out.job_id) if x.status == "SUCCEEDED"]
        assert len(rows) == 1

    def test_cancelled_job_claim_dropped_and_fenced(self):
        from research_engine.models.job import JobStatus
        db = _mk_db()
        job = _one_task_job(db)
        sched = PersistentScheduler(db, SchedulerConfig(worker_threads=1))
        job.status = JobStatus.CANCELLED
        db.save_job(job)
        t = db.claim_next_task("w1", {"GENERIC": 5}, 60)
        assert t is not None
        # worker discovers cancellation and drops claim (fenced finish)
        db.finish_task(t.id, "w1", ok=False, error="cancelled",
                       error_category="USER", fence=t.attempts)
        assert db.get_task(t.id).status == "DEAD_LETTER"
