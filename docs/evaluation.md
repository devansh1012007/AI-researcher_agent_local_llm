# Evaluation

## Framework

```
evals/
    datasets/golden_tasks.json   # 5 deterministic benchmark tasks
    metrics/eval_metrics.py      # scoring from persisted state
    runners/run_eval.py          # --offline (fakes) | live
tests/evaluation/                # gate assertions inside the test suite
```

## Golden tasks

| id | mode | tests |
|---|---|---|
| golden_llm_manipulation | academic | multi-source literature research, primary-source ratio |
| golden_ai_infra_india | startup | market/customer/competitor dimensions |
| golden_contradiction_probe | academic | contradictory-evidence handling |
| golden_numeric_claims | startup | numeric provenance |
| golden_missing_info | academic | correct "insufficient evidence" behavior |

## Metrics

- **Retrieval**: primary-source ratio, domain diversity, accepted/rejected counts
- **Evidence**: quote correctness (re-verified against chunks at eval time),
  rejected ratio, citation coverage of claims
- **Research**: subquestion coverage, gaps discovered/resolved, contradictions
- **System**: LLM calls, queries executed, errors, wall clock

Quality gates per task (e.g., `min_quote_correctness: 0.95`) fail the run when
unmet — architecture changes that degrade grounding are caught mechanically.

```bash
python evals/runners/run_eval.py --offline     # deterministic CI-safe run
python evals/runners/run_eval.py --task golden_llm_manipulation   # live
```

Results: `evals/last_eval_results.json`.

Interpretation offline: retrieval/evidence/system metrics are meaningful;
subquestion coverage is content-driven and only becomes discriminative with a real model.
