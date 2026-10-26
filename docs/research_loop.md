# Research Loop

The loop is the most important artifact of the system. One cycle:

```
PLANNED
  └─ _begin_iteration()                    iteration counter++, event logged
SEARCHING
  └─ pending queries?  ──no──► _generate_followups() from gaps+contradictions
  └─ select top-N by expected_information_gain (budget-capped)
  └─ RetrievalWorker: route → search (parallel, cached) → normalize → Sources
FETCHING
  └─ DocumentProcessor: fetch (retry/backoff/size-cap/cache) → parse (trafilatura/pypdf)
     → content-hash dedup → deterministic chunking
EXTRACTING
  └─ EvidenceWorker per chunk: LLM proposes evidence w/ verbatim quotes
VERIFYING
  └─ quote verified against chunk text; failures REJECTED and stored anyway
  └─ claims consolidated; claim confidence derived from tier×confidence×corroboration
ANALYZING_GAPS
  └─ GapDetector (rules + LLM), ContradictionDetector
  └─ metrics snapshot per iteration
  └─ ConvergenceAnalyzer decides:
       BUDGET_EXHAUSTED | MAX_ITERATIONS | CONVERGED | NO_HIGH_VALUE_GAPS | continue
GENERATING_FOLLOWUPS
  └─ targeted queries from unresolved gaps + contradiction follow-ups
  └─ back to SEARCHING
CONVERGED ─► SYNTHESIZING ─► COMPLETED
```

## Stopping

`stop_reason` is always recorded. `CONVERGED` (diminishing new evidence / duplicate
saturation / no high-value gaps) is different from `BUDGET_EXHAUSTED` or
`MAX_ITERATIONS` — reports flag budget-limited conclusions.

## Information gain heuristic

```
gain = branch.importance × relevance(kind) × source_quality × uncertainty × novelty
relevance(kind): primary 1.0 · technical .95 · contradiction .85 · synonym .7 ...
novelty decays with the number of prior queries
```

Deterministic, cheap, and sufficient to stop local compute from repeating low-value
searches. Query families include adversarial probes (`limitations`, `failure cases`)
by construction.

## Resume & continuation

Every mutation is persisted immediately; the orchestrator can be killed at any point.
`research resume <id>` reloads state and continues from the current state machine
position. Completed projects can be continued (e.g., "investigate that contradiction")
— `COMPLETED → SEARCHING` is an allowed transition and creates a new iteration on top
of preserved knowledge.
