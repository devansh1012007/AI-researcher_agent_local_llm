# Observability

## Structured logs (spec #47)

Every platform event is one JSON line in `<data_dir>/_global/logs/platform.jsonl`:

```json
{"ts":"...","level":"info","event":"job_finished","component":"platform",
 "project_id":"","job_id":"job_x","task_id":"","trace_id":"",
 "duration_ms":0,"status":"ok","error":"","metadata":{...}}
```

Correlate a research request end-to-end via `trace_id` (#50): job → planner →
queries → fetches → evidence → gaps. Per-project human logs remain in
`reports/research_log.md` + `events.jsonl`.

Secret redaction (#66): keys/tokens/passwords are replaced with `<redacted>`
in messages AND metadata before anything hits disk.

## Metrics (spec #48)

In-process registry (`platform/metrics.py`) with periodic snapshots to
`_global/metrics.jsonl` (30s) incl. resource samples:

- research: runs, duration histogram, mode counters
- llm: calls by provider/role (router), failures, retries
- retrieval: queries, accepted sources, cache behavior
- scheduler: tasks started/succeeded/failed by type + error category,
  per-task latency histograms, queue depth gauges
- hardware: load averages, mem used_pct, cpu busy %, disk free (/proc; degrades
  to {} elsewhere)

## Research telemetry (spec #49)

Per-iteration records already persisted as `ResearchMetrics` rows (sources,
evidence, claims, gaps resolved/open, duplicates, diversity, llm_calls) plus
research gain — the basis for efficiency work (#82).

## Incidents (spec #124)

Significant failures append to `_global/incidents.md` + `incidents` table:
time, job, component, symptom, cause, resolution.

## Health checks (#51)

`GET /health` / `GET /ready` classify database, storage, LLM provider,
scheduler as healthy/degraded/unavailable — degradation is expected and
visible, not hidden.
