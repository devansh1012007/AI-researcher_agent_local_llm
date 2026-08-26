# Golden Research Runs

Permanent regression capability born from the Post-Stabilization Architecture
Gate (§38–48): canonical end-to-end research tasks whose offline execution is
**fully deterministic**, recorded as versioned baselines, and checked against
hard invariants on every run.

## Layout

```
evals/golden/scientific/manifest.json   # question + expectations + thresholds
evals/golden/scientific/baseline.json   # recorded metrics + versions + reason
evals/golden/startup/manifest.json
evals/golden/startup/baseline.json
evals/runners/run_golden.py             # runner (offline default, --live flag)
```

## Determinism contract

Offline runs use `ScriptedLLM` + fake providers inside a fresh temp workspace;
project ids derive from the question, so a rerun replays byte-identical logic.
`baseline.json.metrics` must reproduce EXACTLY (`--suite all` exits non-zero on
any drift). Durations are excluded. Baselines record git sha, python version,
config fingerprint, and an `updated_reason` (§46): never bump a baseline to
make it pass — every bump needs a documented why.

## What every golden run verifies (hard checks)

- `all_claims_traceable` — every claim cites at least one existing evidence id
- `no_ungrounded_synthesis_evidence` — INV-014 auditor over real output
- `opportunity_scores_schema_v2` — INV-014 score validator (startup)
- `report_generation_read_only` — WAL-safe store fingerprint before/after
  report generation (INV-004)
- startup: markets/personas/competitors/pricing/opportunity counts from
  thresholds; opportunity core-evidence traceability (§42)

## Known violations are first-class

A check annotated in the manifest under `known_violations` may fail while its
gate finding is open — printed as `KNOWN_VIOLATION (<id>)` every run, never
silent. When the finding is fixed, delete the annotation and the check becomes
a hard gate again. Current annotations:

| Check | Finding |
|---|---|
| `report_generation_read_only` (startup) | F-01 — persist=False gate clobbered |
| `pricing_or_signal_linkage` (startup) | F-07 — opportunities don't link pricing/signal evidence |

## Dual mode (§38 decision: both)

- **Offline synthetic (default)** — regression gate; exact baselines; runs in
  ~3s/suite; hermetic.
- **Live (`--live`)** — periodic realism check against real providers using
  the same questions; threshold/tolerance based, never wired to baselines,
  never blocks CI. Results are informational because real web variance makes
  exact comparison meaningless (§43 constraint).

## Regression rule (§45)

After every major change, in order:

```bash
pytest                                   # unit + integration
pytest tests/invariants -q               # executable invariants
python scripts/mutation_check.py         # critical mutations still detected
python evals/runners/run_golden.py       # scientific + startup vs baselines
```

Allow improvement; reject unexplained regression; explain intentional drift
via `--update-baseline --reason "..."`.
