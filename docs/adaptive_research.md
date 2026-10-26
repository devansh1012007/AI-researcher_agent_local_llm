# Adaptive Research

Phase 2's central upgrade: the planner no longer follows a static sequence — it
analyzes the current structured state and decides **what deserves investigation next**.

## Priority model (`reasoning/priority.py`)

```
priority = importance x uncertainty x expected_information_gain
           x evidence_deficit x downstream_dependency
```

Every open branch, gap, and contradiction becomes a `PriorityItem`; the queue is sorted
and each item can explain itself (`item.explain()`). No opaque numbers.

## Coverage model

Per branch (formula documented in code):

```
coverage = 0.4*answer_ratio + 0.3*strength + 0.2*diversity + 0.1*freshness
```

- answered >= 0.7 · weakly_answered 0.25–0.7 · unanswered < 0.25
- strength counts tier<=2 evidence; diversity counts distinct domains
- branches carry `coverage_score`, `evidence_count`, `gap_count`, `status`

## Strategy selection (`reasoning/adaptive_planner.py`)

Deterministic rules pick one strategy per iteration:

| State | Strategy |
|---|---|
| unresolved contradictions exist | CONTRADICTION_SEARCH |
| claims rest only on tier>=4 sources | PRIMARY_SOURCE_SEARCH |
| important branches unanswered | BROAD_SWEEP |
| important branches weakly covered | FOCUSED_DEEP_DIVE |
| otherwise alternate | FAILURE_CASE_SEARCH / RECENT_WORK_SEARCH |

The LLM proposes additional queries inside the chosen strategy; deterministic priority
queries are always generated first, so a weak model cannot stall adaptation.

## Query evolution & memory

Queries record `results_count`, `useful_results`, `reason`, `strategy`. Near-duplicate
queries are dropped semantically before execution. The "what next" output is persisted
as an `adaptive_plan` event for auditability.

## Stopping policy

Stopping now explains itself:

```
"Research stopped because no high-importance gaps remain open and recent iterations
 produced minimal new evidence."
```
vs
```
"Research stopped due to budget exhaustion while N high-priority gaps remain unresolved."
```

These are recorded as `stop_policy_applied` events and shown in reports.
