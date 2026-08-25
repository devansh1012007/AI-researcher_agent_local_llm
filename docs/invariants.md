# System Invariants

Canonical list. Every invariant here is **executable** — the enforcing code
and the regression tests are named. If a PR breaks one, CI must fail.

| ID | Invariant | Enforced by | Tests |
|----|-----------|-------------|-------|
| INV-001 | A task has at most one valid writer at any instant. | `PlatformDB.claim_next_task` (fence = `attempts`, monotonic), `finish_task`/`release_task` ownership checks, execution-time lease renewal (`scheduler._execute`) | `tests/invariants/test_single_writer.py` |
| INV-002 | A stale fencing token cannot mutate task state; rejection is LOUD (`StaleTaskOwner`, metric `scheduler_stale_writes_rejected`). | `platform_db.finish_task/release_task/heartbeat(fence=)` | `test_single_writer.py::TestFencing` |
| INV-003 | Repeated domain analysis is idempotent: natural-key upserts keep original identity; DB unique indexes backstop. | `StartupRepos.*.natural_key` + `_GenericRepo.save_natural`; `_STARTUP_UNIQUE_INDEXES` | `tests/invariants/test_entity_identity.py` |
| INV-004 | Report generation is READ-ONLY over primary state. | `ReportGenerator.write_startup_research` (precomputed result or store view); `service.build_market_context(persist=False)`; read-only intelligence-report writers | `tests/invariants/test_system_invariants.py::TestReportPurity` |
| INV-005 | Grounding = quote EXISTS **and** claim is SUPPORTED by that quote. CONTRADICTS/UNRELATED ⇒ REJECTED (audit row kept). | `pipeline/claim_support.py` + wiring in `EvidenceWorker._extract_chunk` | `tests/invariants/test_claim_faithfulness.py` |
| INV-006 | Convergence reflects useful progress. Provider failure or extraction-pathology yields `PROVIDER_DEGRADED`, never CONVERGED. | `reasoning/convergence.py` ordering + honest metrics (`duplicate_rate`=true dup; `rejection_rate` separate) | `tests/invariants/test_convergence_semantics.py` |
| INV-007 | Evidence aggregation respects source quality AND independence: best-single dominates, corroboration boost capped (≤0.35); support factor multiplies tier weight. | `evidence_quality.aggregate_claim_strength`; `hypothesis_engine.score_hypothesis` | `test_claim_faithfulness.py::TestIntegration/TestHypothesisWeighting` |
| INV-008 | Public interfaces use application services. API/MCP: zero direct storage construction. CLI: legacy loaders `_load2/_load3` only (documented debt, shrinking). | executable scan `test_system_invariants.py::TestServiceBoundaries` | same |
| INV-009 | Every conflict identifies both sides (claim links OR evidence links). Unlinkable historical rows are marked `LEGACY_UNLINKED`, never fabricated. | `models/analysis.Contradiction` fields; `market.cross_validate_sizes`; `data_repair.repair_project` | `scripts/reaudit.py` BUG-10 check |
| INV-010 | One canonical opportunity schema: `score_breakdown.schema_version=2` with named rubric dimensions + gate. Legacy rows stay labeled v1 and are never silently reinterpreted. | `opportunities.score_rubric`; report writers render by version | `test_system_invariants.py::TestOpportunitySchema` |
| INV-011 | `$10M`-style magnitudes never parse as prices/market sizes without classification. One canonical money parser (`policies.parse_money` + `classify_numeric_statement`). | `specialists/startup/policies.py`; legacy extractor delegates | `scripts/reaudit.py` BUG-04/05 checks |
| INV-012 | Failed operations are distinguishable from empty results at every external boundary (search/fetch/extraction/LLM). | provider wrappers raise; convergence consumes failure deltas; `EventBus.dropped_events` counter | convergence tests; `test_bugfix_regressions.py` |
| INV-013 | Project data is isolated: repos/FTS queries are project-scoped. | per-project SQLite; scoped FTS WHERE | `test_system_invariants.py::TestProjectIsolation` |

## Adding a new invariant

1. State it in one sentence here.
2. Name the enforcing module/function.
3. Add unit + adversarial test under `tests/invariants/`.
4. If it guards a formula, add a mutation to `scripts/mutation_check.py`.
