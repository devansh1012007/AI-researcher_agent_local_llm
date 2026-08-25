# Convergence Semantics (INV-006)

Stop-reason decision order:
1. BUDGET_EXHAUSTED / MAX_ITERATIONS (honest resource stops)
2. PROVIDER_DEGRADED — fetch failures>0 with zero new evidence, OR
   verification rejection-rate above threshold (extraction pathology).
   Routes to synthesis but state/human-log say "NOT converged".
3. CONVERGED via new-evidence-rate floor OR TRUE duplicate pressure
4. NO_HIGH_VALUE_GAPS (+ no new claims)
5. LLM advisory (cannot override budgets; ignored when high gaps remain)

Metric honesty: `duplicate_rate` = accepted rows whose quote-hash repeats;
`rejection_rate` = verification failures. They are different numbers about
different phenomena and are never conflated.
