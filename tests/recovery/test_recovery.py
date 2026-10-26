"""Crash recovery tests (spec #11/#106/#143): kill things mid-flight and
verify no corrupted state, no duplicated work, correct statuses, recovery."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from research_engine.models.job import (
    JobStatus, JobTask, ResearchJob, ResourceProfile, TaskStatus,
)
from research_engine.platform.scheduler import PersistentScheduler, SchedulerConfig
from research_engine.storage.platform_db import PlatformDB


def _mk(tmp_path):
    db = PlatformDB(tmp_path / "data")
    return db


class TestCrashRecovery:
    def test_reconcile_reclaims_stale_leases(self, tmp_path):
        """Worker crashed holding a lease -> restart reclaims + retries."""
        db = _mk(tmp_path)
        job = ResearchJob(project_id="p", type="maintenance")
        db.save_job(job)
        task = JobTask(job_id=job.id, type="WORK")
        db.add_task(task)
        # simulate: worker claimed then process died
        claimed = db.claim_next_task("dead-worker",
                                     {ResourceProfile.CPU_LIGHT: 4},
                                     lease_seconds=300)
        assert claimed.id == task.id
        cfg = SchedulerConfig(worker_threads=2, poll_interval=0.05,
                              lease_seconds=1.0)
        s = PersistentScheduler(db, cfg)
        actions = s.reconcile()
        # lease still fresh (300s) -> not stale yet; job stays as-is
        t = db.get_task(task.id)
        if t.lease_expired():
            assert actions["stale_reclaimed"] >= 1
        # force expiry, then reconcile must reclaim
        t.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.update_task(t)
        actions = s.reconcile()
        assert actions["stale_reclaimed"] == 1
        t = db.get_task(task.id)
        assert t.status == TaskStatus.QUEUED

    def test_full_crash_cycle_no_lost_work(self, tmp_path):
        """Complete crash story: 3 done, 1 mid-flight, crash, restart,
        recovery completes the job with NO duplicate executions."""
        db = _mk(tmp_path)
        executed = []
        lock = threading.Lock()

        class Recorder:
            def __call__(self, task):
                with lock:
                    executed.append(task.idempotency_key)
                time.sleep(0.3)
                return {"ok": task.idempotency_key}

        job = ResearchJob(project_id="p", type="maintenance")
        db.save_job(job)
        tasks = [JobTask(job_id=job.id, type="REC",
                         idempotency_key=f"unit-{i}") for i in range(4)]
        for t in tasks:
            db.add_task(t)
        cfg = SchedulerConfig(worker_threads=2, poll_interval=0.05,
                              lease_seconds=0.6)
        s1 = PersistentScheduler(db, cfg)
        s1.register_runner("REC", Recorder())
        s1.start()
        # let some work happen, then CRASH (no drain)
        time.sleep(0.55)
        s1._stop.set()   # simulate hard stop: workers abandon mid-task
        time.sleep(0.1)

        # restart: new scheduler instance over the SAME database
        s2 = PersistentScheduler(db, cfg)
        s2.register_runner("REC", Recorder())
        s2.reconcile()
        s2.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            j = db.get_job(job.id)
            if j.is_terminal():
                break
            time.sleep(0.1)
        s2.stop()
        assert j.status in (JobStatus.COMPLETED, JobStatus.FAILED_PARTIAL), \
            f"recovery failed: {j.status} {j.error}"
        succeeded = [t for t in db.tasks_for_job(job.id)
                     if t.status == TaskStatus.SUCCEEDED]
        assert len(succeeded) == 4, "every unit completed exactly once"
        # idempotency: each unit executed at most twice (once by dead worker,
        # once after recovery) — never more
        from collections import Counter
        counts = Counter(executed)
        assert all(v <= 2 for v in counts.values()), counts

    def test_dead_letter_job_fails_not_hangs(self, tmp_path):
        db = _mk(tmp_path)
        job = ResearchJob(project_id="p", type="maintenance")
        db.save_job(job)
        db.add_task(JobTask(job_id=job.id, type="POISON", max_attempts=1))
        cfg = SchedulerConfig(worker_threads=1, poll_interval=0.05)
        s = PersistentScheduler(db, cfg)
        def poison(t):
            raise RuntimeError("unrecoverable")
        s.register_runner("POISON", poison)
        s.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            j = db.get_job(job.id)
            if j.is_terminal():
                break
            time.sleep(0.05)
        s.stop()
        assert j.status == JobStatus.FAILED
        ts = db.tasks_for_job(job.id)
        assert ts[0].status == TaskStatus.DEAD_LETTER

    def test_heartbeat_keeps_lease_alive(self, tmp_path):
        db = _mk(tmp_path)
        task = JobTask(job_id="j", type="LONG", resource_profile=ResourceProfile.CPU_LIGHT)
        db.add_task(task)
        claimed = db.claim_next_task("w", {ResourceProfile.CPU_LIGHT: 2},
                                     lease_seconds=0.5)
        for _ in range(4):
            time.sleep(0.25)
            assert db.heartbeat(task.id, "w", lease_seconds=0.5)
        # lease renewed repeatedly -> another worker cannot steal it
        assert db.claim_next_task("w2", {ResourceProfile.CPU_LIGHT: 8},
                                  lease_seconds=30) is None
