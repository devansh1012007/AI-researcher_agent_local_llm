# Contradiction Engine

## Detection (Phase 1, retained)
LLM proposes claim-pair contradictions; harness validates entity existence and
deduplicates. Stored WITHOUT resolution.

## Analysis (`reasoning/contradiction_analyzer.py`, Phase 2)

For each contradiction the analyzer compares supporting-evidence contexts:

| dimension | comparison |
|---|---|
| temporal | publication years of each side's evidence |
| geographic | geography terms in claims/titles |
| source tier | best tier on each side |

Deterministic verdicts:

- `TEMPORAL_DIFFERENCE` — different periods; both may be true in their own window
- `SCOPE_DIFFERENCE` — different geographies/scopes
- `MEASUREMENT_DIFFERENCE` — different metrics/populations implied
- `REAL_CONTRADICTION` — genuine disagreement; notes which side has stronger sources,
  resolution still requires human judgment
- `UNRESOLVED` — insufficient context to classify

The verdict is prefixed into the stored contradiction explanation and rendered in
`contradiction_report.md`. **The system never auto-resolves** (spec #75/#125).

## Adversarial integration

High-confidence claims lacking independent support or resting on dated evidence
generate their own gaps (`INDEPENDENT_REPLICATION_GAP`, `TIME_GAP`) with counter-evidence
queries attached — the loop actively hunts its own weak points.
