"""Persistent scheduler (spec #7/#12/#13/#14/#15/#106/#119/#120).

Runs in-process with worker threads; ALL state lives in PlatformDB so the
scheduler survives restarts. The scheduler itself never calls an LLM.

Responsibilities:
  - reconcile on startup: reclaim stale leases, resume interrupted jobs
  - claim tasks atomically under per-resource-profile concurrency caps
  - adaptive caps: NETWORK/LLM/CPU limits derived from config + live resources
  - priority + dependency ordering; BLOCKED jobs wake when deps finish
  - dead-letter after max attempts, incident recording
  - job lifecycle: pause/cancel flags checked cooperatively by runners
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from research_engine.models.job import (
    ACTIVE_STATUSES, TERMINAL_STATUSES, WAITING_STATUSES, CompletionReason,
    JobPriority, JobStatus, JobTask, ResourceProfile, TaskStatus,
)
from research_engine.platform.errors import classify
from research_engine.platform.events import DomainEvent, EventBus
from research_engine.platform.metrics import GlobalMetrics, sample_resources
from research_engine.platform.obs_logging import IncidentLog, platform_logger
from research_engine.storage.platform_db import PlatformDB, StaleTaskOwner

DEFAULT_PROFILES = {
    ResourceProfile.NETWORK_LIGHT: 5,
    ResourceProfile.NETWORK_HEAVY: 2,
    ResourceProfile.CPU_LIGHT: 3,
    ResourceProfile.CPU_HEAVY: 1,
    ResourceProfile.LLM_SMALL: 2,
    ResourceProfile.LLM_LARGE: 1,
    ResourceProfile.MEMORY_HEAVY: 1,
    ResourceProfile.EXPERIMENT_HEAVY: 1,
}


class SchedulerConfig:
    def __init__(self, max_jobs: int = 1, worker_threads: int = 4,
                  lease_seconds: float = 120.0, heartbeat_seconds: float = 15.0,
                  poll_interval: float = 0.5,
                  profile_caps: dict[str, int] | None = None):
        self.max_jobs = max_jobs            # concurrent deep-research-style jobs
        self.worker_threads = worker_threads
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_interval = poll_interval
        self.profile_caps: dict[str, int] = {**DEFAULT_PROFILES, **(profile_caps or {})}

    @classmethod
    def from_app_config(cls, cfg) -> "SchedulerConfig":
        plat = getattr(cfg, "platform", None)
        sched = getattr(plat, "scheduler", None) if plat else None
        if sched is None:
            return cls()
        return cls(max_jobs=sched.max_jobs,
                   worker_threads=sched.worker_threads,
                   profile_caps=dict(sched.profile_caps))


class PersistentScheduler:
    def __init__(self, db: PlatformDB, cfg: SchedulerConfig | None = None,
                 bus: EventBus | None = None):
        self.db = db
        self.cfg = cfg or SchedulerConfig()
        self.bus = bus or EventBus()
        self.log = platform_logger()
        self.incidents = IncidentLog(self.db.path.parent)
        self.metrics = GlobalMetrics.get().registry
        self._worker_id = f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._runners: dict[str, Callable[[JobTask], dict]] = {}
        self._control: dict[str, str] = {}   # job_id -> PAUSE|CANCEL (runtime hint)
        self._lock = threading.Lock()

    # ------------------------------------------------------- runner registry
    def register_runner(self, task_type: str,
                        fn: Callable[[JobTask], dict]) -> None:
        """fn receives the claimed JobTask and returns a result dict.
        Raise to fail the attempt. Check scheduler.control_flag(job_id) inside
        long fn loops for cooperative pause/cancel."""
        self._runners[task_type] = fn

    def control_flag(self, job_id: str) -> str | None:
        with self._lock:
            return self._control.get(job_id)

    def _set_control(self, job_id: str, flag: str | None) -> None:
        with self._lock:
            if flag is None:
                self._control.pop(job_id, None)
            else:
                self._control[job_id] = flag

    # ------------------------------------------------------------- job API
    def submit_job(self, job, tasks: list[JobTask]) -> ResearchJob:
        """Persist a queued job (+tasks); BLOCKED immediately when its
        dependencies are not all COMPLETED (spec #15)."""
        deps_met = True
        for dep in job.depends_on:
            d = self.db.get_job(dep)
            if d is None or d.status != JobStatus.COMPLETED:
                deps_met = False
                break
        job.status = JobStatus.BLOCKED if not deps_met else JobStatus.QUEUED
        self.db.save_job(job)
        for t in tasks:
            t.job_id = job.id
            t.project_id = t.project_id or job.project_id
            t.priority = min(t.priority, job.priority)
            self.db.add_task(t)
        self.bus.publish(DomainEvent("JobQueued", project_id=job.project_id,
                                     job_id=job.id, payload={"type": job.type}))
        self.log.info("job_submitted", job_id=job.id,
                      metadata={"type": job.type, "tasks": len(tasks)})
        return job

    def pause_job(self, job_id: str) -> bool:
        job = self.db.get_job(job_id)
        if job is None or job.is_terminal():
            return False
        self._set_control(job_id, "PAUSE")
        if job.status in (JobStatus.QUEUED, JobStatus.BLOCKED,
                          JobStatus.WAITING_FOR_USER):
            job.status = JobStatus.PAUSED
            self.db.save_job(job)
        else:
            job.status = JobStatus.PAUSING
            self.db.save_job(job)
        return True

    def resume_job(self, job_id: str) -> ResearchJob | None:
        job = self.db.get_job(job_id)
        if job is None:
            return None
        self._set_control(job_id, None)
        if job.status == JobStatus.PAUSED:
            job.status = JobStatus.RESUMING
            self.db.save_job(job)
            for t in self.db.tasks_for_job(job_id):
                if t.status in (TaskStatus.RETRYING, TaskStatus.CREATED):
                    t.status = TaskStatus.QUEUED
                    self.db.update_task(t)
        return job

    def cancel_job(self, job_id: str) -> bool:
        job = self.db.get_job(job_id)
        if job is None or job.is_terminal():
            return False
        self._set_control(job_id, "CANCEL")
        job.status = JobStatus.CANCELLED
        job.completion_reason = CompletionReason.USER_STOPPED
        job.completed_at = datetime.now(timezone.utc)
        self.db.save_job(job)
        for t in self.db.tasks_for_job(job_id):
            if t.status not in (TaskStatus.SUCCEEDED, TaskStatus.DEAD_LETTER):
                t.status = TaskStatus.CANCELLED
                self.db.update_task(t)
        self.bus.publish(DomainEvent("JobFinished", project_id=job.project_id,
                                     job_id=job.id,
                                     payload={"status": "CANCELLED"}))
        return True

    # ---------------------------------------------------------- reconciliation
    def reconcile(self) -> dict:
        """Startup recovery (spec #106): scan incomplete jobs/tasks, reclaim
        stale leases, requeue interrupted work, mark impossible work failed."""
        actions = {"stale_reclaimed": 0, "jobs_resumed": 0, "dead_lettered": 0}
        now = datetime.now(timezone.utc)
        for job in self.db.incomplete_jobs():
            tasks = self.db.tasks_for_job(job.id)
            running = [t for t in tasks
                       if t.status in (TaskStatus.CLAIMED, TaskStatus.RUNNING)]
            stale = [t for t in running if t.lease_expired(now)]
            for t in stale:
                # previous process died mid-task; safe to retry (idempotency keys)
                t.status = TaskStatus.QUEUED
                t.worker_id = ""
                t.lease_expires_at = None
                self.db.update_task(t)
                actions["stale_reclaimed"] += 1
            fresh_running = [t for t in running if not t.lease_expired(now)]
            if job.status in ACTIVE_STATUSES and not fresh_running:
                if any(t.status == TaskStatus.DEAD_LETTER for t in tasks) and \
                   not any(t.status in (TaskStatus.QUEUED, TaskStatus.RETRYING,
                                        TaskStatus.RUNNING, TaskStatus.CLAIMED)
                           for t in tasks):
                    job.status = JobStatus.FAILED
                    job.completion_reason = CompletionReason.FAILED
                    job.completed_at = now
                    self.db.save_job(job)
                    actions["dead_lettered"] += 1
                elif job.status != JobStatus.PAUSED:
                    job.status = JobStatus.QUEUED
                    self.db.save_job(job)
                    actions["jobs_resumed"] += 1
            elif job.status in WAITING_STATUSES and job.status != JobStatus.PAUSED:
                pass  # waiting states persist across restarts deliberately
        self.log.info("reconcile_complete", metadata=actions)
        return actions

    # ---------------------------------------------------------------- loop
    def start(self) -> None:
        self.reconcile()
        self._stop.clear()
        for i in range(self.cfg.worker_threads):
            th = threading.Thread(target=self._worker_loop, name=f"sched-w{i}",
                                  daemon=True)
            th.start()
            self._threads.append(th)
        # Phase 6 §80: watchers become continuous — due ticks are enqueued
        # at start and after every finished task (event-driven, bounded),
        # replacing the previously unwired schedule_due path.
        try:
            self._schedule_due_watchers()
        except Exception as exc:
            self.log.error("watcher_seed_error", error=str(exc))

    def _schedule_due_watchers(self, max_enqueue: int = 3) -> int:
        """Enqueue WATCHER_TICK jobs for due watchers. Bounded per sweep;
        the tick's own backoff (consecutive_empty_runs) prevents storms."""
        from research_engine.models.job import JobTask, ResearchJob
        n = 0
        for w in self.db.due_watchers()[:max_enqueue]:
            job = ResearchJob(project_id=w.project_id, type="watcher_tick",
                              priority=90)
            task = JobTask(job_id=job.id, project_id=w.project_id,
                           type="WATCHER_TICK",
                           resource_profile="NETWORK_LIGHT", priority=90,
                           payload={"watcher_id": w.id,
                                    "project_id": w.project_id})
            self.submit_job(job, [task])
            n += 1
        return n

    def stop(self, drain_s: float = 5.0) -> None:
        self._stop.set()
        deadline = time.time() + drain_s
        for th in self._threads:
            th.join(timeout=max(0.0, deadline - time.time()))

    def run_forever(self) -> None:  # pragma: no cover - CLI entry
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    # ------------------------------------------------------------ internals
    def _active_deep_jobs(self) -> int:
        n = 0
        for j in self.db.list_jobs():
            if j.type in ("deep_research", "incremental_update", "experiment") \
               and j.status in (JobStatus.RUNNING, JobStatus.STARTING,
                                JobStatus.RESUMING, JobStatus.COMPLETING):
                n += 1
        return n

    def _promote_blocked(self) -> None:
        for j in self.db.list_jobs(status=JobStatus.BLOCKED):
            deps_done = all(
                (d := self.db.get_job(dep)) is not None and d.is_terminal()
                and d.status == JobStatus.COMPLETED
                for dep in j.depends_on)
            if deps_done:
                j.status = JobStatus.QUEUED
                self.db.save_job(j)

    def _maybe_start_queued_job(self, job) -> bool:
        if job.type in ("deep_research", "incremental_update") and \
           self._active_deep_jobs() >= self.cfg.max_jobs:
            return False
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.trace_id = job.trace_id or uuid.uuid4().hex[:12]
        self.db.save_job(job)
        self.bus.publish(DomainEvent("JobStarted", project_id=job.project_id,
                                     job_id=job.id))
        return True

    def _worker_loop(self) -> None:
        profiles = {p: c for p, c in self.cfg.profile_caps.items()}
        lease = self.cfg.lease_seconds
        last_hb = 0.0
        current_task: JobTask | None = None
        while not self._stop.is_set():
            try:
                # periodic heartbeat for a long-running local task
                if current_task and time.time() - last_hb > self.cfg.heartbeat_seconds:
                    renewed = self.db.heartbeat(current_task.id, self._worker_id, lease)
                    if not renewed:
                        current_task = None  # lost lease; abandon quietly
                    last_hb = time.time()
                # housekeeping every few polls
                if random_chance(0.05):
                    self._promote_blocked()
                task = self.db.claim_next_task(self._worker_id, profiles, lease)
                if task is None:
                    self._advance_jobs()
                    self._stop.wait(self.cfg.poll_interval)
                    continue
                if task.job_id:
                    job = self.db.get_task_job(task.job_id)
                    if job is None:
                        self.db.finish_task(task.id, self._worker_id, ok=False,
                                            error="job missing",
                                            error_category="USER",
                                            fence=task.attempts)
                        current_task = None
                        continue
                    if job.status in (JobStatus.PAUSING, JobStatus.PAUSED):
                        # release cleanly back to queue (fenced)
                        try:
                            self.db.release_task(task.id, self._worker_id,
                                                 fence=task.attempts)
                        except Exception as exc:
                            self.log.warn("release_rejected", task_id=task.id,
                                          error=str(exc)[:120])
                        self._stop.wait(self.cfg.poll_interval)
                        continue
                    if job.is_terminal():
                        # cancelled while queued: drop the claim, never run
                        self.db.finish_task(task.id, self._worker_id, ok=False,
                                            error="job cancelled before start",
                                            error_category="USER",
                                            fence=task.attempts)
                        current_task = None
                        continue
                current_task = task
                self._execute(task)
                current_task = None
            except Exception as exc:  # never let the loop die
                self.log.error("scheduler_loop_error", error=str(exc))
                self._stop.wait(1.0)

    def _execute(self, task: JobTask) -> None:
        t0 = time.time()
        runner = self._runners.get(task.type)
        fence = task.attempts          # fencing token captured at claim
        self.metrics.incr("scheduler_tasks_started", type=task.type)
        # INVARIANT-001: renew the lease FROM INSIDE execution so a live
        # worker can never have its task stolen mid-run (BUG-01 fix). The
        # renewal interval is derived from the lease, not operator memory.
        hb_every = max(0.05, min(self.cfg.heartbeat_seconds,
                                 self.cfg.lease_seconds / 3.0))
        stop_renewal = threading.Event()
        lost_ownership = threading.Event()

        def _renew() -> None:
            while not stop_renewal.wait(hb_every):
                try:
                    ok = self.db.heartbeat(task.id, self._worker_id,
                                           self.cfg.lease_seconds, fence=fence)
                except Exception as exc:
                    self.log.warn("heartbeat_error", task_id=task.id,
                                  error=str(exc)[:120])
                    continue
                if not ok:
                    lost_ownership.set()
                    self.log.warn("STALE_WRITER_DETECTED", task_id=task.id,
                                  worker_id=self._worker_id, expected_fence=fence)
                    return

        renewal = threading.Thread(target=_renew, name=f"hb-{task.id[:12]}",
                                   daemon=True)
        if self.cfg.lease_seconds > 0:
            renewal.start()
        stale_rejected = False
        try:
            if runner is None:
                raise RuntimeError(f"no runner registered for task type {task.type}")
            result = runner(task)
            if lost_ownership.is_set():
                # work finished but ownership was stolen mid-flight: refuse
                # to write terminal state (INVARIANT-002)
                raise StaleTaskOwner(task.id, self._worker_id, -1, fence,
                                     reason="ownership lost during execution")
            try:
                self.db.finish_task(task.id, self._worker_id, ok=True,
                                    result=result, fence=fence)
            except StaleTaskOwner as exc:
                stale_rejected = True
                self.metrics.incr("scheduler_stale_writes_rejected",
                                  type=task.type)
                self.log.warn("STALE_WRITER_REJECTED", task_id=task.id,
                              worker_id=self._worker_id, expected_fence=exc.expected_fence,
                              received_fence=exc.received_fence, reason=exc.reason)
                return
            self.metrics.observe("task_latency_ms", (time.time() - t0) * 1000,
                                 type=task.type)
            self.metrics.incr("scheduler_tasks_succeeded", type=task.type)
        except Exception as exc:
            cat = classify(exc)
            try:
                self.db.finish_task(task.id, self._worker_id, ok=False,
                                    error=str(exc), error_category=cat.value,
                                    fence=fence)
            except StaleTaskOwner as sexc:
                stale_rejected = True
                self.metrics.incr("scheduler_stale_writes_rejected",
                                  type=task.type)
                self.log.warn("STALE_WRITER_REJECTED", task_id=task.id,
                              worker_id=self._worker_id,
                              expected_fence=sexc.expected_fence,
                              received_fence=sexc.received_fence, reason=sexc.reason)
            if not stale_rejected:
                self.metrics.incr("scheduler_tasks_failed", type=task.type,
                                  category=cat.value)
                attempts_left = task.max_attempts - task.attempts
                self.log.warn("task_failed", job_id=task.job_id, task_id=task.id,
                              status=cat.value, error=str(exc),
                              metadata={"attempts_left": max(0, attempts_left)})
                if cat.value in ("AUTH", "SECURITY"):
                    self.incidents.record(task.job_id, task.type, str(exc)[:200],
                                          f"{cat.value} failure")
        finally:
            stop_renewal.set()
            renewal.join(timeout=2.0)
            # drive THIS job forward immediately — finalization must not
            # depend on idle-poll timing (crash-test determinism, spec #11)
            if task.job_id:
                try:
                    self._advance_one(task.job_id)
                except Exception as exc:
                    self.log.error("advance_after_finish_error", error=str(exc))
                try:
                    self._schedule_due_watchers()
                except Exception:
                    pass

    def _advance_one(self, job_id: str) -> None:
        job = self.db.get_job(job_id)
        if job is not None and not job.is_terminal():
            self._advance_jobs(job_filter=job.id)

    def _advance_jobs(self, job_filter: str = "") -> None:
        """Move job state forward based on its tasks; called opportunistically."""
        for job in self.db.list_jobs():
            if job_filter and job.id != job_filter:
                continue
            if job.status not in (JobStatus.RUNNING, JobStatus.PAUSING,
                                  JobStatus.QUEUED, JobStatus.RESUMING,
                                  JobStatus.COMPLETING):
                continue
            tasks = self.db.tasks_for_job(job.id)
            if not tasks and job.type not in ("deep_research", "incremental_update",
                                              "watcher_tick"):
                continue
            queued = [t for t in tasks if t.status in
                      (TaskStatus.QUEUED, TaskStatus.RETRYING, TaskStatus.CLAIMED,
                       TaskStatus.RUNNING)]
            dead = [t for t in tasks if t.status == TaskStatus.DEAD_LETTER]
            done = [t for t in tasks if t.status == TaskStatus.SUCCEEDED]
            active = [t for t in tasks if t.status in
                      (TaskStatus.CLAIMED, TaskStatus.RUNNING)]
            if job.status == JobStatus.PAUSING and not active:
                job.status = JobStatus.PAUSED
                self.bus.publish(DomainEvent("ResearchPaused",
                                             project_id=job.project_id, job_id=job.id))
                self.db.save_job(job)
                continue
            if job.status in (JobStatus.QUEUED, JobStatus.RESUMING):
                # start even if tasks already finished (fast lanes)
                if job.type in ("deep_research", "incremental_update") and \
                        self._active_deep_jobs() >= self.cfg.max_jobs:
                    continue
                deps_ok = all(
                    (d := self.db.get_job(dep)) is not None
                    and d.status == JobStatus.COMPLETED
                    for dep in job.depends_on)
                if not deps_ok:
                    job.status = JobStatus.BLOCKED
                    self.db.save_job(job)
                    continue
                self._maybe_start_queued_job(job)
            if queued:
                job.progress = {"done": len(done), "queued": len(queued),
                                "dead_letter": len(dead)}
                self.db.save_job(job)
                continue
            # nothing queued left
            if job.status in (JobStatus.RUNNING, JobStatus.COMPLETING):
                if dead and not done:
                    job.status = JobStatus.FAILED
                    job.completion_reason = CompletionReason.FAILED
                elif dead:
                    job.status = JobStatus.FAILED_PARTIAL   # spec #105
                    job.completion_reason = CompletionReason.FAILED
                else:
                    job.status = JobStatus.COMPLETED
                    job.completion_reason = job.completion_reason or \
                        CompletionReason.CONVERGED
                job.completed_at = datetime.now(timezone.utc)
                self.db.save_job(job)
                self.bus.publish(DomainEvent(
                    "JobFinished" if job.type != "deep_research" else "ResearchCompleted",
                    project_id=job.project_id, job_id=job.id,
                    payload={"status": job.status,
                             "reason": job.completion_reason}))
                self.log.info("job_finished", job_id=job.id,
                              metadata={"status": job.status,
                                        "reason": job.completion_reason})


def random_chance(p: float) -> bool:
    import random
    return random.random() < p
