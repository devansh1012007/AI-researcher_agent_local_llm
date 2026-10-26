# Research Evaluation (Phase 2 additions)

## New concepts

### Research gain (per iteration)
```
gain = 2*new_claims + 2*gaps_resolved + 0.5*accepted_evidence_delta + domain_diversity_uplift
```
Recorded per iteration in metrics/events and surfaced by `research diff` and the eval
runner (`adaptive: gain_by_iter=[...] total=... gain/llm_call=...`). Diminishing returns
become visible — "iteration 4 added 60 pages but only 2 useful evidence objects" shows up
as low gain, lowering the incentive to continue.

### Search efficiency
```
efficiency = accepted_sources / retrieved_sources
```
Also `research_gain / LLM_calls` — maximize research value per unit of local compute.

## Phase 2 golden tasks (`evals/datasets/phase2_tasks.json`)

| id | tests |
|---|---|
| p2_literature_mapping | clustering inputs present; literature reports generated |
| p2_startup_opportunity | opportunity pipeline runs end-to-end offline |
| p2_adaptive_contradiction | adaptive follow-ups + contradiction handling |

Run everything:

```bash
python evals/runners/run_eval.py --offline   # Phase 1 + Phase 2 suites
```

## Acceptance coverage (`tests/evaluation/test_phase2_acceptance.py`)

- Adaptive: branches prioritized+covered; followups state-dependent; gain measured;
  stop explanation recorded.
- Literature: clustering works & totals preserved; foundational ranking not
  citation-only; method comparison REFUSES blind cross-setting metric comparison;
  reports written.
- Startup: pain→opportunity→assumptions→falsification roundtrip with transparent
  score breakdown (weights sum to 1.0); startup reports written.
- Memory: snapshot+diff roundtrip; claim tracing end-to-end.

## Gap-quality evaluation

Structural gap detectors are unit-tested for true positives AND true negatives
(`no gaps without evidence`, diversity/negative-evidence/replication fire only under
their exact conditions). Human labeling of gap quality remains a manual process on
real runs (spec #90); the CLI output is designed to make that review practical
(`gaps.md` lists category + importance + evidence_needed).
