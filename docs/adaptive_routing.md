# Adaptive Routing (Routing v2)

Phase 5 routing (deterministic domain-signal rules + schema-validated LLM
veto) remains THE FLOOR. Routing v2 layers bounded, explainable learning on
top (`adaptive/routing_v2.py`).

## Selection pipeline

```
rule scores (floor)
  → per-specialist history lookup (context-conditioned, §10)
  → trust adjustment clamped to ±0.15          (never overrides rule gaps)
  → reliability floor check (≥0.5 else NO boost)
  → controlled exploration: promote (never inject) a low-ranked
    rule-matched specialist with probability ε                 (§13/§14)
  → decision record persisted                  (§56/§57)
```

## Constraints that cannot be violated

| Constraint | Value | Enforced at |
|---|---|---|
| max score adjustment | ±0.15 | registry activation check + clamp |
| min samples before learning | 5 runs | `specialist_stats` gate |
| reliability floor | 0.5 | boost refusal |
| exploration ε | ≤0.15; HIGH_RIGOR ⇒ 0 | registry + criticality arg |
| candidate set | rule matches only | exploration promotes, never injects |

Exploration is deterministic given question+history (seeded hash), so
replays are reproducible (§59).

## Context conditioning (§10)

Specialist perf rows are recorded under `task_type = "<mode>:<domain_bucket>"`
going forward (buckets from `adaptive/features.domain_bucket`: b2b_saas,
consumer, regulated_industry, technical_science, broad_exploratory).
Lookups aggregate matching rows and require the sample minimum — a
specialist will NOT be learned as "great for B2B SaaS" from two runs.

## Counterfactual honesty (§16)

No fabricated counterfactuals. "Would another specialist have done better?"
is answerable only via recorded comparable runs, A/B benchmark tasks, and
golden chains (`evals/runners/run_adaptive_benchmark.py`). Expected-vs-
actual gain is stored per decision so calibration is measurable over time.

## Interfaces

- CLI: `research quality`, `research decisions <pid>`
- Every selection stores chosen/alternatives/reason/policy_version/
  expected_gain in `adaptive_decisions`.
