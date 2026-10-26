# Scheduler (stabilized)

## Ownership model (INV-001/002)

```
claim_next_task(worker, profiles, lease_s)
  -> status=RUNNING, attempts+=1   # attempts IS the fencing token
  -> lease_expires_at = now+lease

during execution:
  renewal thread heartbeats every min(heartbeat_seconds, lease/3)
  -> heartbeat(task, worker, fence) renews lease or flags lost ownership

terminal write:
  finish_task(..., fence) requires (worker_id, fence, status∈{CLAIMED,RUNNING})
  mismatch -> StaleTaskOwner raised + scheduler_stale_writes_rejected metric

pause:
  release_task(worker, fence) -> QUEUED (ownership-checked)
```

A live worker can never have its task stolen: renewal runs INSIDE execution.
A dead worker's lease expires and is reclaimed; its late writes are rejected
loudly with expected vs received fence in the log record
(`STALE_WRITER_REJECTED`).

## Job finalization
Event-driven `_advance_one(job)` after every task completion; idle poll is an
optimization only. Terminal job statuses are absorbing at the SQL layer.

## Failure drills covered
kill -9 mid-task → reclaim exactly once; pause during run → fenced release;
cancel while queued → fenced drop; double-finish → second raises.
