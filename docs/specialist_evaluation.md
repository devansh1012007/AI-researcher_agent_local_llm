# Specialist Evaluation

How we measure whether specialists IMPROVE research rather than merely
adding compute (§81/§85).

## Layers

1. **Contract harness** (`tests/specialists/test_contract_harness.py`) —
   every registered specialist automatically passes identity, grounding,
   permissions, ownership, purity, schema and limits checks on every suite
   run.
2. **Golden chains** — deterministic offline specialist workflows with exact
   baselines: `evals/golden/{literature_only, technology_only,
   cross_domain_research, research_gap_to_startup}` (+ existing scientific /
   startup).
3. **Threshold evals** — `evals/specialists/*.json` and
   `evals/cross_domain/*.json` run through the same runner with
   threshold gates (e.g. `gaps ≥ 3`, `claims ≥ 1`, `evidence_after ≥ 4`)
   instead of exact counts where corpus growth is expected.

Run everything:

```bash
python evals/runners/run_golden.py          # includes evals/specialists + evals/cross_domain
```

## Per-specialist quality dimensions (§45)

- literature: gap detection rate, claim traceability, stage coverage
- technology: constraint category coverage, unknown-risk surfacing
- competitive: shared-entity reuse (no duplicate competitor records),
  pricing-change detection
- foresight: trend signal capture, direction classification
- startup: unchanged Phase-5 gates (opportunity pipeline, hypotheses,
  report sections) via the adapter

## Routing measurement (§47) and performance registry (§48)

Every invocation appends to `platform.sqlite::specialist_perf` keyed
`(specialist, version, task_type)`: runs, failures, llm_calls, queries,
documents, EMA latency. CLI: `research specialists` shows OK/RUNS.
Routing correctness is pinned by `TestHybridRouting` and protected by
mutation M-7 (selection rule is load-bearing). No learned routing until this
data accumulates (spec §18).

## Efficiency (§81/§85)

Golden metrics record `seed_evidence → evidence_after`, claims, gaps per
chain; cycle-guard SKIPPED results are counted as efficiency WINS (avoided
duplicate work), visible in stage statuses.
