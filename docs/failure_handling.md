# Failure Handling

## Principles

- One bad page never kills a project (isolation at every worker boundary).
- Partial results are always preserved (checkpoint after every phase).
- Retries are bounded and policy-specific; then the item is marked failed and the
  loop continues.

## Matrix

| Failure | Detection | Response |
|---|---|---|
| HTTP timeout / transport | `DocumentFetcher` | retry w/ backoff (`NETWORK`), then source FAILED |
| Rate limit 429/503 | status code | raised → retried with longer backoff |
| Other 4xx/5xx | status code | fail fast, source marked FAILED + reason |
| Oversized document | stream cap | truncate at `max_document_size_mb` |
| Bad HTML/PDF | parser exception | source FAILED; pipeline continues |
| Duplicate content | content hash under lock | source DUPLICATE, no re-processing |
| Corrupted cache entry | JSON decode | entry deleted, treated as miss |
| LLM invalid JSON / schema | `structured()` loop | repair prompt ×3 → graceful fallback |
| LLM unavailable | connection error | role degrades to deterministic path |
| Hallucinated quotes | `verify_quote` vs chunk | evidence REJECTED (stored for audit) |
| DB write failure | sqlite exceptions | surface as task failure; state checkpointed before |
| Worker crash | future exception | logged, isolated, loop continues |
| Run-loop anomaly | guard counter (>200) | forced stop with reason |

## Retry policies

```
NETWORK:     3 attempts, base backoff 1.5^attempt
RATE_LIMIT:  4 attempts, base 2.0
LLM:         2 attempts inside structured(), plus schema-repair prompts
validation:  no retry — deterministic checks either pass or reject
```

## Checkpointing

State is persisted to SQLite + `project.json` after every phase transition. A killed
process resumes with `research resume <project_id>` from the exact persisted state;
completed tasks are not repeated, failed sources are remembered.
