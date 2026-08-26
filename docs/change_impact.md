# Change Impact & Continuous Watchers

## Dependency traversal (§81/§82)

New evidence (research run, watcher tick, experiment ingestion) is traversed
through PERSISTED links only:

```
new evidence → claims (supported_by / contradicted_by)
            → hypotheses (supporting_evidence / contradicting_evidence)
            → opportunities (evidence_ids / market_signal_evidence_ids)
```

`adaptive/impact.analyze_new_evidence` returns the downstream map;
`raise_impact_alerts` persists ranked alerts. No inference, no fabrication.

## Alerts (§83/§84)

Few kinds, ranked by `impact × confidence × recency × decision_relevance`:

- `CLAIM_CONTRADICTION` — new evidence contradicts existing claims
- `HYPOTHESIS_FALSIFIED` — new evidence lands in contradicting sets
- `OPPORTUNITY_WEAKENED` — linked opportunity lacks market-signal support
  or carries sub-0.4 severity
- `HIGH_IMPACT_NEW_EVIDENCE` — bulk arrival worth a look

Surfaces: `research alerts <pid>` (+`--ack`), `GET /projects/{id}/alerts`,
MCP `list_alerts`. Noise control: bounded kinds, composite score ordering,
acknowledge workflow.

## Continuous watchers (§80)

Watchers are now SELF-DRIVING: the scheduler enqueues due WATCHER_TICK jobs
at start and after every finished task (event-driven, ≤3 per sweep; the
tick's own empty-streak backoff prevents storms). A tick with new connected
evidence runs impact analysis and raises alerts automatically.

Chain example: new paper → watcher extracts evidence → impact traversal
finds affected technical claims → alert raised → targeted specialist task
can be submitted through the normal fenced path.

Note: `due_watchers()` had never been callable in production (bare SQL
param bug) — Phase 6 wiring exposed and fixed it.

## Outcome attribution caution (§40)

External outcomes (experiment verdicts, user-reported results) feed
EVALUATION aggregates, never automatic policy writes. Success of a
recommendation does not retroactively certify the research process that
produced it.
