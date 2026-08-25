# Scheduler Operations

The scheduler is the only component that decides *when* work runs. It never
calls an LLM and never touches project SQLite directly — runners do that.

## Running it

- Implicit: every service-layer job submission starts it on demand.
- Explicit long-lived process: `research serve` (API) keeps one alive.
- Workers: `platform.scheduler.worker_threads` (default 4).

## Configuration (gar.yaml)

```yaml
platform:
  profile: balanced        # minimal|balanced|high_memory|cpu_only|offline
  scheduler:
    max_jobs: 1            # concurrent research jobs
    worker_threads: 4
    lease_seconds: 120
    heartbeat_seconds: 15
    profile_caps:          # per-resource-profile concurrency
      NETWORK_LIGHT: 5
      LLM_LARGE: 1
      EXPERIMENT_HEAVY: 1
```

## Inspecting

```
research jobs                       # queue visibility (#107)
research jobs --status RUNNING
research job <job_id>               # detail incl. tasks/attempts/error class
research job-control pause|resume|cancel <job_id>
research job-control retry <task_id>
```

## Failure semantics

| Error class | Retry? | Notes |
|-------------|--------|-------|
| NETWORK     | yes, backoff+jitter | transient |
| RATE_LIMIT  | yes, long backoff   | respects provider cooldown |
| MODEL       | yes, short backoff  | empty/invalid output |
| DATABASE    | yes, fast retry     | lock contention |
| AUTH/PARSING/SCHEMA/SECURITY/USER | never | fail into dead-letter |
