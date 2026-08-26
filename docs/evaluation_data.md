# Evaluation Data Separation & Benchmark Protection

## Three-way split (§30)

```
evals/adaptive/train/*.json    optimization input for policy proposals
evals/adaptive/val/*.json      model/policy selection between candidates
evals/adaptive/test/*.json     FINAL comparison only — never optimized against
```

The adaptive benchmark runner (`evals/runners/run_adaptive_benchmark.py`)
takes an explicit `--split` flag. Policy proposals record WHICH splits they
were tuned on in their evaluation blob; comparing on test after tuning on
test is a review finding, enforced by convention here and by reviewers —
the runner prints the split used with every result so the history is
visible.

## Golden protection (§31)

Golden baselines (`evals/golden/*/baseline.json`, plus specialist suites)
are the regression bedrock. Hard rules:

1. No adaptive tooling writes to `evals/golden/`. Policy proposal/activation
   paths touch ONLY platform.sqlite — there is no code path from learning
   to golden files (verified by `tests/policy/test_golden_protection.py`).
2. Baseline updates require the explicit
   `--update-baseline --reason "..."` invocation and land as reviewed diffs.
3. Threshold gates in manifests cannot be lowered by automation; they change
   only via versioned manifest edits.

A full propose→evaluate→activate cycle leaves every baseline byte-identical;
that property is asserted by test.

## What each benchmark measures (§64-§69)

| benchmark | compares | gate |
|---|---|---|
| routing accuracy | known-optimal specialist tasks: v1 vs v2 | accuracy ≥ baseline, fewer unnecessary calls |
| query strategy | static vs utility tie-break | quality preserved, cost ≤ |
| model A/B | fixed vs measured selection under identical constraints | quality_per_second |
| budget | fixed vs dynamic allocation | gain per query, bounded spend |
| critic | injected known defects found? | recall of injected findings |

The central success criterion (spec §100): same task, baseline vs adaptive,
reproducible offline, showing **equal-or-better quality at comparable-or-
lower cost**. The runner emits exactly this table; claims beyond it are
forbidden until the data exists.
