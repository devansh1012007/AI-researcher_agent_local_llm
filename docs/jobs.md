# Jobs & Scheduler (Phase 4)

## The job model

Every long-running operation is a **ResearchJob** (`models/job.py`) persisted in
the platform DB (`<data_dir>/platform.sqlite`):

```
QUEUED → STARTING → RUNNING → COMPLETING → COMPLETED
                    ↕            ↘ FAILED / FAILED_PARTIAL
                 PAUSED  ← PAUSING
BLOCKED · WAITING_FOR_USER · WAITING_FOR_RESOURCE · CANCELLED
```

Completion reasons stay distinct (spec #111): `CONVERGED`, `BUDGET_EXHAUSTED`,
`USER_STOPPED`, `FAILED`, `NO_MORE_USEFUL_RESEARCH`. A job that fails at 80%
becomes `FAILED_PARTIAL`; completed tasks are retained and resumable (#105).

Job types: `deep_research`, `experiment`, `report`, `watcher_tick`,
`incremental_update`, `maintenance`.

## Tasks, leases, heartbeats

Work units are JobTasks with lease-based ownership:

- claiming is a single atomic conditional UPDATE — two workers can never hold
  one task;
- every running task carries `worker_id`, `lease_expires_at`, `heartbeat_at`
  (#119/#120); workers renew heartbeats every `scheduler.heartbeat_seconds`;
- an expired lease is reclaimable by any worker — a crashed worker cannot lock
  a task forever (#8);
- failed tasks retry per error category; after `max_attempts` they enter
  `DEAD_LETTER` with the full error context (#121) and can be requeued via
  `research job-control retry <task_id>` (#122).

## Priorities & dependencies

Priorities: CRITICAL(10) HIGH(30) NORMAL(50) LOW(70) BACKGROUND(90). Interactive
research outranks maintenance. A submitted job whose `depends_on` jobs have not
all COMPLETED is BLOCKED until they finish (#15).

## Resource profiles & adaptive concurrency

Each task declares a profile (NETWORK_LIGHT/HEAVY, CPU_LIGHT/HEAVY,
LLM_SMALL/LARGE, MEMORY_HEAVY, EXPERIMENT_HEAVY). The scheduler caps each
profile independently — defaults in `platform.scheduler.profile_caps`, tuned by
resource *profiles* (`minimal|balanced|high_memory|cpu_only|offline`, #152).
Never hard-code "10 agents"; caps express laptop reality.

## Recovery on startup

`PersistentScheduler.reconcile()` (#106/#11): scan incomplete jobs → reclaim
stale leases → requeue interrupted work → mark hopeless jobs FAILED → resume.
See `docs/recovery.md`.

## Human-gated pauses

Pause is a first-class state, never a failure (#16): `research pause <pid>` /
API `/projects/{id}/pause` sets a cooperative flag; the orchestrator checks it
at phase boundaries, checkpoints, and transitions to PAUSED. Resume continues
from the checkpoint.
