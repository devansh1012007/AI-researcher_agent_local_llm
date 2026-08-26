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
| INV-014 | Specialists persist only through identity-declaring repo seams, never open storage themselves; ungrounded synthesis-evidence and opaque scores are caught by auditors. | static scan + `specialists/extension_audit.py` (detector seam; see `docs/extension_invariants.md`) | `tests/invariants/test_extension_contract.py` |
| INV-015 | Cross-domain connections are evidence-linked with COMPUTED confidence (canonical aggregator); domain standards gate VALIDATED status fail-closed; specialists cannot assert or inflate it. | `specialists/cross_domain.py` (propose/validate); UNIQUE index on connection triple | `tests/cross_domain/test_cross_domain.py` |
| INV-016 | Adaptive policies are versioned, bounded, and human-activated: no autonomous deployment path exists; learned adjustments are hard-clamped; cold-start behavior is bit-identical to shipped rules; golden baselines are unreachable from any learning path. | `adaptive/policies.PolicyRegistry` (bounds check at activation); clamps in `routing_v2`; baseline seeding in ServiceContext | `tests/policy/`, `tests/routing/` |

## Adding a new invariant

1. State it in one sentence here.
2. Name the enforcing module/function.
3. Add unit + adversarial test under `tests/invariants/`.
4. If it guards a formula, add a mutation to `scripts/mutation_check.py`.

# Phase 7 invariants (§41 / §48)

INV-017: No production policy may become active without explicit human authorization.
Enforcement: policy_activations table stores activated_by + authorization_reference; SafetyGate.can_activate requires non-empty authorization_ref; no code path activates without it.

INV-018: Every learned candidate must have complete lineage to its source observations.
Enforcement: candidate_policies requires dataset_snapshot_id -> dataset_snapshots.fingerprint -> production_observations.fingerprint; LearningDB.get_candidate_policy + get_dataset_snapshot enforce traceability.

INV-019: Synthetic or simulated observations cannot increase production learning confidence.
Enforcement: EligibilityFilter excludes provenance_type in (synthetic, benchmark, replayed) unless allow_synthetic=True; dataset eligibility records excluded counts.

INV-020: No candidate may be promoted without independent evaluation evidence.
Enforcement: evaluation.py requires separate train/eval splits; candidate must have evaluation_metrics_json and regression_metrics_json before approval.

INV-021: A learning failure cannot change the active policy.
Enforcement: freeze_states blocks promotion; SafetyGate.is_frozen prevents activation; learning failure preserves current active policy via rollback_target_policy_id.

INV-022: A frozen learner cannot promote or activate a candidate.
Enforcement: SafetyGate.is_frozen checks freeze_states; can_promote returns False when frozen.

INV-023: The active baseline cannot be mutated by the learning subsystem.
Enforcement: existing policies table protected by registry lifecycle; candidate policies never overwrite active policy except via explicit activation with rollback_target_policy_id.

INV-024: Learning cannot modify protected safety constraints.
Enforcement: bounded surfaces (§10) restrict to routing/utility/gain/specialist-ranking/budget; security/auth/deployment/safety tables never written by learning module.

INV-025: Missing evaluation evidence is never interpreted as positive evidence.
Enforcement: SafetyGate.can_promote requires evaluation metrics; evaluation.py reports missing evidence as failure, not success; freeze_states trigger on telemetry failure.
