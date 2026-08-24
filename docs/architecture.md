# Architecture

## Principle

A **central harness** (orchestrator) owns execution. LLMs propose decisions; the harness
controls state, budgets, retries, persistence, and termination. The evidence store
preserves truth and provenance. Nothing trusts an LLM's memory.

```
USER ──► ORCHESTRATOR ──► workers ──► SQLite + JSONL + reports
              │
   state machine · budgets · retries · checkpointing · audit log
```

## Components

| Component | Responsibility | Key rule |
|---|---|---|
| `core/orchestrator.py` | drives the loop through explicit states | only caller of `StateMachine.transition` |
| `core/state_machine.py` | validates every transition, logs it | illegal transitions raise |
| `core/budget.py` | live counters + hard stops | budgets are not advisory |
| `providers/llm/*` | Ollama / OpenAI-compatible / llama.cpp / mock | `structured()` never raises on bad output |
| `providers/llm/router.py` | role→model mapping (extractor/reasoning/synthesis) | roles may share one model |
| `providers/search`, `providers/academic` | normalized search behind interfaces | providers are swappable, cached |
| `pipeline/planning.py` | branches, query families, info-gain scoring | semantic query dedup |
| `pipeline/retrieval.py` | executes routed queries in a bounded thread pool | URL dedup at discovery |
| `pipeline/documents.py` | fetch → parse → chunk → persist | one bad source never kills the run |
| `pipeline/evidence.py` | extraction + quote verification + claim consolidation | unverifiable quotes are REJECTED |
| `reasoning/gap_detector.py` | LLM gaps **plus deterministic rule-based gaps** | rules guarantee coverage with weak models |
| `reasoning/convergence.py` | stop decisions | deterministic signals first; LLM is tiebreaker only |
| `reports/generator.py` | DB → markdown | info.md is a derived view, never primary |

## Deliberate deviations from the original spec

1. **Threads instead of asyncio.** SQLite is synchronous; LLM work is serialized by
   design (`max_parallel_llm_tasks: 1`). A bounded `ThreadPoolExecutor` for fetches gives
   the same throughput with far less complexity and full determinism.
2. **Keyless-first providers** (OpenAlex/Crossref/arXiv/DDG) so the system works with zero
   API keys; paid/keyed providers slot into the same interfaces.
3. **Gap detection is hybrid**: deterministic rules guarantee certain gap classes
   (unverified numerics, weak-evidence claims, uncovered branches, empty evidence) even
   when the local model is weak — the LLM adds semantic gaps on top.
4. **Rejected evidence is stored, not discarded** — the audit trail must show what was
   thrown away and why (`status=REJECTED`, reason in `validation_notes`).

## Concurrency model

- IO-bound search/fetch: `ThreadPoolExecutor(max_parallel_fetches)` — parallel.
- CPU-bound parsing: inside the same pool, bounded by document size caps.
- LLM-bound extraction/analysis: strictly sequential.
- SQLite: WAL mode, per-thread connections, short transactions.

## Extension points (Phase 2+)

- New provider → implement `SearchProvider` / `AcademicProvider` / `LLMProvider`,
  register in `build_default_registry` or config.
- New mode → subclass `ResearchMode` (branch categories, schema hint, report set).
- MCP/REST → the tool interfaces (`search_web`, `fetch_document`, `query_evidence`,
  `get_project_state`) map 1:1 onto future tool servers.
- Vector search → `chunks` table already stores text + provenance; add an embedding
  column/index without touching the loop.
