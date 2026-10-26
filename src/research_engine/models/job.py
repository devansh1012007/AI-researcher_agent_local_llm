"""Research job + task models (spec #6/#8/#14/#111).

Jobs are long-running units (deep research, experiments, watchers, reports).
Tasks are schedulable steps within/across jobs with leases, heartbeats,
attempts, and dead-letter semantics. All persisted in the platform DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class JobStatus:
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    RESUMING = "RESUMING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    FAILED_PARTIAL = "FAILED_PARTIAL"      # spec #105
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"                     # dependencies unmet
    WAITING_FOR_USER = "WAITING_FOR_USER"
    WAITING_FOR_RESOURCE = "WAITING_FOR_RESOURCE"
    WAITING_FOR_EXTERNAL_RESULT = "WAITING_FOR_EXTERNAL_RESULT"


ACTIVE_STATUSES = {JobStatus.QUEUED, JobStatus.STARTING, JobStatus.RUNNING,
                   JobStatus.PAUSING, JobStatus.RESUMING, JobStatus.COMPLETING}
WAITING_STATUSES = {JobStatus.PAUSED, JobStatus.BLOCKED, JobStatus.WAITING_FOR_USER,
                    JobStatus.WAITING_FOR_RESOURCE,
                    JobStatus.WAITING_FOR_EXTERNAL_RESULT}
TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.FAILED_PARTIAL,
                     JobStatus.CANCELLED}


class JobPriority:  # spec #14 — lower number = scheduled first
    CRITICAL = 10
    HIGH = 30
    NORMAL = 50
    LOW = 70
    BACKGROUND = 90


class CompletionReason:  # spec #111 — distinct finish causes
    CONVERGED = "CONVERGED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    USER_STOPPED = "USER_STOPPED"
    FAILED = "FAILED"
    NO_MORE_USEFUL_RESEARCH = "NO_MORE_USEFUL_RESEARCH"
    WAITING_FOR_EXTERNAL_RESULT = "WAITING_FOR_EXTERNAL_RESULT"


class ResourceProfile(str):
    """Coarse concurrency buckets (spec #12) — the scheduler caps each."""
    NETWORK_LIGHT = "NETWORK_LIGHT"
    NETWORK_HEAVY = "NETWORK_HEAVY"
    CPU_LIGHT = "CPU_LIGHT"
    CPU_HEAVY = "CPU_HEAVY"
    LLM_SMALL = "LLM_SMALL"
    LLM_LARGE = "LLM_LARGE"
    MEMORY_HEAVY = "MEMORY_HEAVY"
    EXPERIMENT_HEAVY = "EXPERIMENT_HEAVY"


class TaskStatus:
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


class ResearchJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    project_id: str = ""
    type: str = "deep_research"       # deep_research|experiment|report|watcher_tick|maintenance|incremental_update
    status: str = JobStatus.QUEUED
    priority: int = JobPriority.NORMAL
    completion_reason: str | None = None
    current_task: str = ""
    progress: dict = Field(default_factory=dict)     # spec #110 meaningful measures
    budget: dict = Field(default_factory=dict)
    usage: dict = Field(default_factory=dict)
    checkpoint_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)   # job ids (spec #15)
    created_by: str = "local_user"        # spec #77 audit
    config_snapshot: dict = Field(default_factory=dict)
    error: str = ""
    trace_id: str = ""
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    next_run_at: datetime | None = None   # recurring/watcher jobs (spec #17)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class JobTask(BaseModel):
    """A unit of work with lease-based ownership (spec #8/#119/#120)."""
    id: str = Field(default_factory=lambda: new_id("tk"))
    job_id: str = ""
    project_id: str = ""
    type: str = ""                        # e.g. FETCH_DOCUMENT, EXTRACT_EVIDENCE
    idempotency_key: str = ""             # stable key => re-execution safe (#9)
    status: str = TaskStatus.CREATED
    priority: int = JobPriority.NORMAL
    resource_profile: str = ResourceProfile.CPU_LIGHT
    payload: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    error: str = ""
    error_category: str = ""
    attempts: int = 0
    max_attempts: int = 3
    worker_id: str = ""
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def lease_expired(self, now: datetime | None = None) -> bool:
        now = now or _now()
        return (self.status in (TaskStatus.CLAIMED, TaskStatus.RUNNING)
                and self.lease_expires_at is not None
                and self.lease_expires_at <= now)


class Watcher(BaseModel):
    """Source monitor (spec #18): query + frequency + change policy + action."""
    id: str = Field(default_factory=lambda: new_id("wch"))
    project_id: str
    name: str = ""
    query: str = ""
    source_scope: list[str] = Field(default_factory=list)  # provider names or domains
    frequency_hours: float = 24.0
    change_policy: str = "content_hash"    # content_hash|new_urls_only
    action: str = "incremental_update"     # incremental_update|notify_only
    enabled: bool = True
    last_run_at: datetime | None = None
    last_change_at: datetime | None = None
    consecutive_empty_runs: int = 0
    created_at: datetime = Field(default_factory=_now)
