# System Invariants

Canonical list. Every invariant here is **executable** — the enforcing code
and the regression tests are named. If a PR breaks one, CI must fail.

**Numbering.** IDs are never reused or renumbered, so a row can be cited
across branches. `INV-015`..`INV-025` are RESERVED: they are taken by the
unmerged `origin/agent/phase-7-production-learning` branch (which also
renames `INV-014`), so this branch's own rows start at `INV-026`. Merging
phase-7 is an explicit non-goal of the current plan; the reservation keeps
that merge possible without an id collision. New rows on this branch take
`INV-026`+.

| ID | Invariant | Enforced by | Tests |
|----|-----------|-------------|-------|
| INV-001 | A task has at most one valid writer at any instant. | `PlatformDB.claim_next_task` (fence = `attempts`, monotonic), `finish_task`/`release_task` ownership checks, execution-time lease renewal (`scheduler._execute`) | `tests/invariants/test_single_writer.py` |
| INV-002 | A stale fencing token cannot mutate task state; rejection is LOUD (`StaleTaskOwner`, metric `scheduler_stale_writes_rejected`). | `platform_db.finish_task/release_task/heartbeat(fence=)` | `test_single_writer.py::TestFencing` |
| INV-003 | Repeated domain analysis is idempotent: natural-key upserts keep original identity; DB unique indexes backstop. | `StartupRepos.*.natural_key` + `_GenericRepo.save_natural`; `_STARTUP_UNIQUE_INDEXES` | `tests/invariants/test_entity_identity.py` |
| INV-004 | Report generation is READ-ONLY over primary state. | `ReportGenerator.write_startup_research` (precomputed result or store view); `service.build_market_context(persist=False)`; read-only intelligence-report writers | `tests/invariants/test_system_invariants.py::TestReportPurity` |
| INV-005 | Grounding = quote EXISTS **and** claim is SUPPORTED by that quote. CONTRADICTS/UNRELATED ⇒ REJECTED (audit row kept). | `pipeline/claim_support.py` + wiring in `EvidenceWorker._extract_chunk` | `tests/invariants/test_claim_faithfulness.py` |
| INV-006 | Convergence reflects useful progress. Provider failure or extraction-pathology yields `PROVIDER_DEGRADED`, never CONVERGED. | `reasoning/convergence.py` ordering: `new_evidence == 0 AND retrieval_failures > 0` ⇒ `PROVIDER_DEGRADED`; honest metrics (`duplicate_rate`=true dup; `rejection_rate` separate) | `tests/invariants/test_convergence_semantics.py`; `tests/invariants/test_search_failure_semantics.py` (end-to-end) |
| INV-007 | Evidence aggregation respects source quality AND independence: best-single dominates, corroboration boost capped (≤0.35); support factor multiplies tier weight. | `evidence_quality.aggregate_claim_strength`; `hypothesis_engine.score_hypothesis` | `test_claim_faithfulness.py::TestIntegration/TestHypothesisWeighting` |
| INV-008 | Public interfaces use application services. API/MCP: zero direct storage construction. CLI: legacy loaders `_load2/_load3` only (documented debt, shrinking). | executable scan `test_system_invariants.py::TestServiceBoundaries` | same |
| INV-009 | Every conflict identifies both sides (claim links OR evidence links). Unlinkable historical rows are marked `LEGACY_UNLINKED`, never fabricated. | `models/analysis.Contradiction` fields; `market.cross_validate_sizes`; `data_repair.repair_project` | `scripts/reaudit.py` BUG-10 check |
| INV-010 | One canonical opportunity schema: `score_breakdown.schema_version=2` with named rubric dimensions + gate. Legacy rows stay labeled v1 and are never silently reinterpreted. | `opportunities.score_rubric`; report writers render by version | `test_system_invariants.py::TestOpportunitySchema` |
| INV-011 | `$10M`-style magnitudes never parse as prices/market sizes without classification. One canonical money parser (`policies.parse_money` + `classify_numeric_statement`). | `specialists/startup/policies.py`; legacy extractor delegates | `scripts/reaudit.py` BUG-04/05 checks |
| INV-012 | Failed operations are distinguishable from empty results at every external boundary (search/fetch/extraction/LLM). | search/academic provider wrappers RAISE (`SearchProviderError`); `pipeline/retrieval.py` records the failure on the `SearchQuery` row (`failed`, `failure_reason`) and a per-leg outcome (`leg_outcomes`, status `failed` vs `unconfigured` vs `optional_unconfigured`); convergence consumes the failure delta; `platform/watchers.py` keeps unconfigured providers and provider failures in SEPARATE lists and reports `status: DEGRADED` when a provider failed; `reasoning/novelty.py` returns `unconfigured_providers`/`provider_failures` on EVERY path. | `tests/invariants/test_search_failure_semantics.py`; `tests/invariants/test_search_outcome_honesty.py`; `test_bugfix_regressions.py`; unit-level pins in `tests/unit/test_stage1_dead_legs.py` |
| INV-013 | Project data is isolated: repos/FTS queries are project-scoped. | per-project SQLite; scoped FTS WHERE | `test_system_invariants.py::TestProjectIsolation` |
| INV-014 | The API requires a token exactly when the server is bound to a non-loopback address; the address the server binds and the address the app authorises on are the same value. | `cli/main.py cmd_serve` writes the effective bind address into `cfg.platform.api.host` before creating the app; `api/app.py make_auth_dependency` authorises on it via the shared fail-closed `core/config.is_loopback_host` | `tests/invariants/test_api_auth_boundary.py` |
| INV-023 | Review decisions are an append-only overlay: they never rewrite machine-owned state, and a decision whose `content_hash` no longer matches its target is stale — surfaced, never auto-applied; latest non-stale decision wins. | `services/review_service.py` (`record_decision`/`list_decisions`), `storage/review_repos.py`; read-only consumption in `reports/generator.py` | `tests/unit/test_stage4_review.py` |
| INV-027 | The effective bind address and the address the app authorises on are the same value; under LOCAL_ONLY (`mode: offline` or `privacy_mode: true`) no network provider is constructed and no non-loopback egress is permitted. | `core/config.effective_environment`; `core/http_policy.build_egress_policy`; `core/orchestrator.build_default_registry` (returns empty registry under LOCAL_ONLY); `cli/main.py cmd_serve` propagates the bound host | `tests/invariants/test_api_auth_boundary.py`; `tests/invariants/test_system_invariants.py::TestServiceBoundaries` |
| INV-028 | Entity ids are collision-free monotonic ULIDs: no two processes mint the same id, and ids are strictly increasing within a process; creation order is read from the row payload `created_at`, never from id text. | `core/ids.next_id`; `storage/database.parse_payload_timestamp`; `storage/graph_store._entity_order_key`; `specialists/startup/data_repair._oldest_first_key` | `tests/invariants/test_entity_identity.py`; `tests/unit/test_stage1_dead_legs.py::TestUlidIds`; `tests/unit/test_stage2_id_ordering.py` |
| INV-026 | A result count is never rendered without the MEANING it carries. `SearchQuery.results_count` is versioned (`results_count_schema_version`: 1 = legacy raw hits, 2 = distinct canonical **http(s)** URLs) and the report states the basis beside the number; the per-leg outcomes are rendered too. | `models/research.py` (`RESULTS_COUNT_*`); `pipeline/retrieval.py` (the distinct-URL count); `reports/generator.py` `_count_basis` / `_leg_summary` | `tests/invariants/test_search_outcome_honesty.py::TestReportStatesTheHonestNumbers`; `tests/unit/test_stage1_dead_legs.py::TestLegOutcomes::test_the_persisted_query_row_carries_the_count_and_the_outcomes` |

## Adding a new invariant

1. State it in one sentence here.
2. Name the enforcing module/function.
3. Add unit + adversarial test under `tests/invariants/`.
4. If it guards a formula, add a mutation to `scripts/mutation_check.py`.

## Changed invariants

An existing row may be STRENGTHENED, never weakened. Every change to a row is
recorded here with the old text, the new text and the reason, so a reader can
see what the invariant used to promise. A NEW row is not recorded here: it is
added to the table above, following the protocol above.

| ID | old | new | why |
|----|-----|-----|-----|
| INV-012 | `... records the failure on the `SearchQuery` row (`failed`, `failure_reason`); convergence consumes the failure delta. The watcher boundary is still open (P1-14).` | `... records the failure on the `SearchQuery` row (`failed`, `failure_reason`) and a per-leg outcome (`leg_outcomes`, status `failed` vs `unconfigured` vs `optional_unconfigured`); convergence consumes the failure delta; `platform/watchers.py` keeps unconfigured providers and provider failures in SEPARATE lists and reports `status: DEGRADED` when a provider failed; `reasoning/novelty.py` returns `unconfigured_providers`/`provider_failures` on EVERY path.` | The watcher boundary was CLOSED: the watcher now tells an unconfigured provider (a declared configuration state) apart from a provider failure (an outage) and reports `DEGRADED` on a failure, so the "boundary is still open (P1-14)" sentence was stale and removed. The novelty verifier now returns its provider report on every path, and the retrieval worker records a per-leg outcome. The change is a STRENGTHENING: it names more enforcing code and more tests and drops no promise. No migration: the row is documentation, not stored data. |
