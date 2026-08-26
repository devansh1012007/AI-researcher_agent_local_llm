# Research Learning (What Is Measured, What Adapts)

## Outcome records (§6)

Every completed deep-research run writes a `research_outcomes` row:
question/mode/features, run fingerprint (§7), specialists used,
quality metrics, resource metrics, gain v2, user feedback join key, and the
stopping policy's next-action recommendation. Built by
`job_runners._record_outcome` from PERSISTED state only — honest zeros are
valid outcomes.

## Task features (§8) and domain buckets (§10)

`adaptive/features.py` derives deterministic keyword/structure features:
domain bucket, complexity, technicality, market orientation, current-info
need, primary-source need, cross-domain flag, time sensitivity, geographic
specificity. These enable comparison of similar tasks without an LLM.

## Gain v2 — importance-weighted, gaming-resistant (§33-§35)

```
gain = 1.0·Σ(1/tier over new evidence)
     + 3.0·(important gaps resolved WITH query lineage)
     + 4.0·(contradictions resolved)
```

- Evidence importance = 1/source_tier: primary literature counts ~5× forums.
- A gap counts as resolved only with `resolved_by_query_ids` lineage —
  renamed or re-summarized gaps earn nothing (§35).
- Efficiency variants divide by queries/LLM calls/duration at analysis time.

## Query strategy learning (§18-§21)

Per-family utility accumulates in `query_family_perf`
(`primary→primary_source_search`, `contradiction→counterevidence`, …).
Utility deliberately EXCLUDES raw result counts. Application is bounded:
historical utility may ONLY break the parity tie in the low-stakes
"coverage adequate" branch of `select_strategy`; contradiction search and
primary-source mandates stay deterministic. Requires ≥20 samples; inert on
fresh stores (goldens unaffected).

## Source utility ≠ source policy (§22/§23)

`source_perf` records OBSERVED utility per (source_type, domain bucket).
Evidence-quality POLICY (`TIER_BY_SOURCE_TYPE`) stays authoritative for
grounding decisions. A forum can be a great discovery lead while remaining
a weak-evidence tier — the system never conflates the two.

## Model routing (§24-§27)

`providers/llm/telemetry.py` instruments the router choke point: every
production call records provider/model/role/ok/latency/schema-failures into
`llm_perf`. `adaptive/model_policy.py` computes quality-per-second,
schema reliability, and conservative degradation verdicts (≥50% failure or
schema-failure rate over ≥10 calls). Verdicts are ADVISORY — no silent
model swaps; benchmark before changing roles (§27).

## User feedback (§37/§38/§85)

Explicit verdicts (`useful|incorrect|bad_source|…`) via CLI/API/MCP land in
`user_feedback`, kept SEPARATE from objective quality. One feedback item
never moves policy; it feeds evaluation aggregates.

## Experiment outcomes feed evaluation (§41)

`ResultIngestor` already links experiment results → hypothesis confidence.
These rows are first-class inputs when comparing strategies: prediction
accuracy per reasoning pattern is computed at analysis time, not asserted.

## Drift & diversity monitors (§71-§78)

`adaptive/drift.py`: usage concentration flags (diagnostic, never quotas),
policy behavior drift between decision halves, per-specialist degradation
trend, all surfaced on `research quality`.
