# Convergence Semantics (INV-006)

Stop-reason decision order:
1. BUDGET_EXHAUSTED / MAX_ITERATIONS (honest resource stops)
2. PROVIDER_DEGRADED — `retrieval_failures > 0` with zero new evidence, OR
   verification rejection-rate above threshold (extraction pathology).
   `retrieval_failures` counts search failures (a provider that raised) plus
   fetch failures (a source marked FAILED) since the previous iteration.
   Routes to synthesis but state/human-log say "NOT converged".
3. CONVERGED via new-evidence-rate floor OR TRUE duplicate pressure
4. NO_HIGH_VALUE_GAPS (+ no new claims)
5. LLM advisory (cannot override budgets; ignored when high gaps remain)

Metric honesty: `duplicate_rate` = accepted rows whose quote-hash repeats;
`rejection_rate` = verification failures. They are different numbers about
different phenomena and are never conflated.

A failure is not saturation: retrieval that was ATTEMPTED and FAILED yields
PROVIDER_DEGRADED, never CONVERGED. "Nothing new" because the corpus is
exhausted still converges. A failed search is recorded on the query row
(`failed`, `failure_reason`) — a search that succeeded and found nothing is
not a failure.
