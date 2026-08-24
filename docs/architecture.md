# Architecture

## Principle

A **central harness** (orchestrator) owns execution. LLMs propose decisions; the harness
controls state, budgets, retries, persistence, and termination. The evidence store
preserves truth and provenance. Nothing trusts an LLM's memory.

```
USER ──► ORCHESTRATOR ──► workers ──► SQLite + JSONL + reports
              │
   state machine · budgets · retries · checkpointing · audit log
                   │
        PHASE 2: research graph · adaptive planner · evidence quality
                   · literature/startup intelligence · hybrid memory
```

## Components

| Component | Responsibility | Key rule |
|---|---|---|
| `core/orchestrator.py` | drives the loop through explicit states | only caller of `StateMachine.transition` |
| `core/state_machine.py` | validates every transition, logs it | illegal transitions raise |
| `core/budget.py` | live counters + hard stops | budgets are not advisory |
| `providers/llm/*` | Ollama / OpenAI-compatible / llama.cpp / mock | `structured()` never raises on bad output |
| `providers/llm/router.py` | role→model mapping (extractor/reasoning/synthesis) | roles may share one model |
| `providers/embeddings/*` | ollama / openai-compat / hashing fallback | embeddings optional by design |
| `providers/search`, `providers/academic` | normalized search behind interfaces | providers are swappable, cached |
| `pipeline/planning.py` | branches, query families, info-gain scoring | semantic query dedup |
| `pipeline/retrieval.py` | executes routed queries in a bounded thread pool | URL dedup at discovery |
| `pipeline/documents.py` | fetch → parse → chunk → persist | one bad source never kills the run |
| `pipeline/evidence.py` | extraction + quote verification + claim consolidation | unverifiable quotes are REJECTED |
| `pipeline/graph_builder.py` | derives the research graph after each cycle | deterministic edges only |
| `reasoning/adaptive_planner.py` | strategy selection + "what next?" engine | deterministic priority first, LLM advisory |
| `reasoning/priority.py` | transparent priority formula + branch coverage | every score explains itself |
| `reasoning/gap_detector.py` | LLM gaps **plus** rule-based + structural gaps | rules guarantee coverage with weak models |
| `reasoning/adversarial.py` | claim challenge protocol + counter-evidence queries | prevents confirmation-machine behavior |
| `reasoning/evidence_quality.py` | independence detection + aggregate strength | two blogs never beat one primary study |
| `reasoning/convergence.py` | stop decisions with explicit explanations | deterministic signals first; LLM is tiebreaker only |
| `intelligence/literature.py` | clustering, foundational/recent, benchmarks, comparisons | metrics never compared across settings |
| `intelligence/startup.py` | pains, competitors, pricing, signals, opportunities | opportunities require clustered evidence |
| `memory/retrieval.py` | hybrid keyword+semantic retrieval with reranking | text relevance mandatory; tier modulates |
| `memory/qa.py` | grounded Q&A + claim tracing | refuses when archive insufficient |
| `memory/snapshots.py` | snapshots, iteration diffs, source update detection | history never overwritten |
| `reports/generator.py` | DB → markdown (Phase 1 reports) | info.md is a derived view, never primary |
| `reports/intelligence_reports.py` | maps/comparisons/timelines (Phase 2 reports) | every item cites IDs |

## Deliberate deviations from the original spec

1. **Threads instead of asyncio.** SQLite is synchronous; LLM work is serialized by
   design (`max_parallel_llm_tasks: 1`). A bounded `ThreadPoolExecutor` for fetches gives
   the same throughput with far less complexity and full determinism.
2. **Keyless-first providers** (OpenAlex/Crossref/arXiv/DDG) so the system works with zero
   API keys; paid/keyed providers slot into the same interfaces.
3. **Gap detection is triple-layered**: deterministic rules + structural detectors +
   LLM analysis — guarantees coverage even when the local model is weak.
4. **Rejected evidence is stored, not discarded** — the audit trail must show what was
   thrown away and why (`status=REJECTED`, reason in `validation_notes`).
5. **Hashing embeddings default** — semantic retrieval works offline/deterministically;
   swap to a real embed model via config without code changes.
6. **Graph in SQLite** — no Neo4j until workload demands it (spec #69 honored).

## Concurrency model

- IO-bound search/fetch: `ThreadPoolExecutor(max_parallel_fetches)` — parallel.
- CPU-bound parsing: inside the same pool, bounded by document size caps.
- LLM-bound extraction/analysis: strictly sequential.
- SQLite: WAL mode, per-thread connections, init-lock around first-connection pragmas,
  dedup lock in document processing.

## Extension points (Phase 3)

- Hypothesis engine → Claim/Evidence/Gap graph is already the input format (spec #67)
- Methodology designer → benchmark/method comparison rows feed directly (spec #68)
- MCP/REST → tool interfaces map 1:1 (`ask`, `map`, `trace-claim`, `verify`, ...)
- Watched sources/queries → `source_versions` table is the alerting seed (spec #100)
