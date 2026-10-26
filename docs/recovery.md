# Crash Recovery & Reliability

## What survives a crash

Everything. Authoritative state lives in SQLite (`platform.sqlite` for jobs,
`<project>/db.sqlite` for knowledge). In-memory scheduler state is disposable
(#118).

## Startup reconciliation (`PersistentScheduler.reconcile()`)

1. scan jobs not in a terminal state
2. tasks CLAIMED/RUNNING with expired leases → requeued (worker died)
3. fresh leases (another live worker) → left alone
4. jobs with only dead-lettered tasks left → FAILED (distinct reason)
5. interrupted-but-recoverable jobs → QUEUED again

Verified by `tests/recovery/test_recovery.py`: hard-stop mid-run, restart on
the same DB, every task completes exactly once, no duplicated evidence
(idempotency keys + content-hash dedup underneath).

## Failure isolation matrix (spec #143)

| Failure during... | Effect | Recovery |
|---|---|---|
| network fetch | source marked FAILED | next iteration retries via query re-execution |
| LLM extraction | evidence rejected, audit row kept | iteration continues with remaining chunks |
| worker crash mid-task | lease expires | another worker claims; idempotency key prevents dupes |
| process kill | WAL replays on reopen | reconcile() requeues |
| provider outage | circuit breaker opens | fallback chain serves; probe after cooldown |
| DB locked | classified DATABASE | fast retries under `_init_lock` |

## Idempotency rules (#9)

- stable task `idempotency_key` (e.g., fetch:<source_id>)
- document ingestion dedups by content hash before saving
- task completion is a single transactional upsert

## Incidents

Significant failures append to `<data_dir>/_global/incidents.md` and the
`incidents` table (spec #124).
