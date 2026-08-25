# STABILIZATION REPORT

Post-audit repair phase. Baseline: 231 tests / ~84s. Final: **283 tests
passed** (1 skip), **17/17 offline eval gates**, **6/6 mutations detected**,
**14/14 original adversarial reproductions now pass** (`scripts/reaudit.py`).

---

## 1. Bugs Fixed

| Audit ID | Defect | Fix summary |
|---|---|---|
| BUG-01/P0-01 | Scheduler double-executed tasks when runtime > lease (repro'd: 2 executions, LLM_LARGE cap=1) | Fenced leases: `attempts` = monotonic fencing token; renewal thread runs INSIDE `_execute` at `min(heartbeat, lease/3)`; `finish_task/release_task/heartbeat` ownership+fence enforced; violations raise `StaleTaskOwner`, metric `scheduler_stale_writes_rejected`, log `STALE_WRITER_REJECTED` |
| BUG-02/P0-02 | Startup entities duplicated on every context build (markets 1→4, competitors →11…) | Natural-key identity per entity + `save_natural()` resolve→merge→keep-ID; 9 DB UNIQUE expression indexes as backstop (legacy-safe skip+record); analyzers routed through it; KB seeding idempotent |
| P0-03/BUG-09 | Quote existence treated as claim support | `pipeline/claim_support.py`: deterministic fail-closed support verdicts (CONTRADICTS…ENTAILS) wired into extraction; CONTRADICTS/UNRELATED ⇒ REJECTED (audited); fields on Evidence; aggregation multiplies tier×support |
| P0-04 | `duplicate_rate` was rejection ratio; silence ⇒ CONVERGED | Honest metrics split (`duplicate_rate` true quote-dup via hash scan; new `rejection_rate`); convergence reordered — fetch-failure or rejection-storm ⇒ `StopReason.PROVIDER_DEGRADED` (never CONVERGED), cached-silence ≠ degradation |
| P0-05a/BUG-03 | `ResearchService.ask` TypeError 100% | Correct `GroundedQA(repos, retriever, provider)` construction; API/MCP contract tests added |
| P0-05b/BUG-06 | MCP `design_methodology` wrong arity → always crashed | Canonical service path `KnowledgeService.design_methodology`; tool delegates |
| P0-06/BUG-04 | Legacy `$10M→$1` regex live in production | Legacy price extractor RETIRED; delegates to canonical magnitude-guarded parser |
| P0-07/BUG-05 | Market sizing grabbed first number (years/%/funding misattributed) | `classify_numeric_statement()` gate before parse; only genuine market-size statements yield estimates; year/%/CAGR/funding/valuation classified distinctly; geography-wildcard bucketing so unattributed figures still cross-validate |
| P0-08/BUG-10 | Conflicts with `claim_id=""` un-analyzable | Contradiction model gains `conflict_type/evidence_a_ids/evidence_b_ids`; market conflicts stored NUMERICAL w/ evidence links; analyzer consumes evidence-side links; legacy unlinkables marked `LEGACY_UNLINKED` by repair (never fabricated) |
| P0-09 | Ten tier-5 posts outvoted one tier-1 study | `score_hypothesis` + `aggregate_claim_strength`: best-single dominates; independence-aware capped boost; SUPPORT_FACTOR multiplies weights (verified: swarm 0.458 < single 0.9) |
| P0-10 | Report generation ran pipelines and mutated state (2× pipeline/completion) | Orchestrator computes once → passes result; regeneration renders from persisted store; `build_market_context(persist=False)` read-only analyzer mode; intelligence-report writers made read-only; PURITY VERIFIED (2 regenerations ⇒ zero primary deltas) |
| P0-11 | ~20 interface sites bypassed services (incl. CLI state-machine mutation) | cmd_pause→ProjectService; startup assumptions/next/map/opportunities/generate-hypotheses→specialist service; MCP assumptions→service; dead `_rrepos_of` removed; EXECUTABLE boundary scan test (API/MCP zero-tolerance, CLI loaders allowlisted as shrinking debt) |
| P0-12 | Two opportunity engines, one table, incompatible schemas | Legacy discover/score retired from ALL production callers (CLI, report writers, orchestrator fallback deleted); canonical rubric stamps `schema_version=2`; v1 rows render labeled, never reinterpreted |
| P0-13 | Gate-priority mutation survived entire suite | Priority formula pinned by constructed-input tests; mutation harness `scripts/mutation_check.py` (M1–M6) all DETECTED |
| BUG-07 | FTS row duplicated per evidence re-save | `fts_index` replaces per entity (verified 3 saves → 1 row) |
| BUG-11 | EventBus dropped audit events silently | `dropped_events` counter + warning log per drop |
| BUG-12 | Ghost project.json appeared in list but 404'd on get | Listing validates authoritative DB row (read-only sqlite probe) |
| BUG-13 | Dead/duplicate code cluster | Duplicate NotFoundError/ConflictError defs remain flagged (see §14); `_rrepos_of` removed; `StartupIntelligence._PRICE_RE` retired |

## 2. Root Causes

1. **Liveness modeled outside execution** (BUG-01): heartbeat placement assumed short tasks.
2. **Append-only write habits applied to derived snapshots** (BUG-02): no natural identity.
3. **Existence conflated with semantics** (P0-03): quote check inherited the whole grounding burden.
4. **Metrics named for intent, implemented as counts** (P0-04, P0-09): duplication/rejection/support all collapsed into sums.
5. **Convenience coupling**: generator had cfg ⇒ rebuilt world (P0-10); legacy engine left wired "temporarily" (P0-06/12).
6. **Unverified idempotency & boundary assumptions** — nothing failed loudly when violated.

## 3. Architectural Invariants Restored

See `docs/invariants.md` INV-001…INV-013. Each names enforcing code + tests.

## 4. Data Repaired

`repair_project(db)` (+ new CLI `research repair-startup [<pid>|--all]`):
natural-key dedupe (oldest canonical, provenance unioned), LEGACY_UNLINKED
conflict marking, unique-index completion. Auditable summary printed.
Existing polluted workspaces (incl. `research_data/proj_find-promising-*`)
should run it once post-upgrade.

## 5. Tests Added

tests/invariants/: single-writer (8), entity identity (4), claim faithfulness
(15+1), convergence (7), system invariants (7), interface contracts (8),
bugfix regressions (3). Total suite 231 → **283**.

## 6. Mutation Tests Added

`scripts/mutation_check.py` M-1…M-6 (gate threshold, degraded branch,
support status mapping, upsert resolve, fence check, weighting formula).
Result: **6/6 DETECTED**. Harness is extensible; add a mutation whenever you
touch a scorer/gate/state machine.

## 7–8. Original Reproductions vs After

| Finding | Original state | Fix | Regression test | Re-run after fix | Status |
|---|---|---|---|---|---|
| BUG-01 double exec | 2 executions (cap=1, lease=2s, task 4s) | fenced leases + in-execute heartbeat | `test_single_writer.py::TestOriginalReproduction` | 1 execution, attempts=1 | FIXED |
| BUG-02 duplication | markets 1→4, comps→11 across runs | natural-key upserts | `test_entity_identity.py::TestBug02Idempotency` | run₂≡run₃ | FIXED |
| BUG-03 ask TypeError | always | ctor fixed | `test_interface_contracts.py::test_ask_endpoint_alive` | 200 + answer | FIXED |
| BUG-04 $10M→$1 | parsed $1 | legacy parser retired | reaudit BUG-04 | REJECTED | FIXED |
| BUG-05 size misattribution | year/funding/%→values | classify-gated parser | reaudit BUG-05 (7 spec cases) | all PASS | FIXED |
| BUG-06 MCP methodology | TypeError | service route | contracts conformance | clean error/ok | FIXED |
| BUG-08 default create_app | NoneType crash | get_ctx closure fix | reaudit BUG-08 | no crash | FIXED |
| BUG-09 truncation inversion | passed gates | claim_support | faithfulness suite | CONTRADICTS | FIXED |
| P0-04 false convergence | rejection=dup, silence=converged | honest metrics+ordering | convergence semantics suite | PROVIDER_DEGRADED | FIXED |
| P0-08 unlinked conflicts | UNRESOLVED forever | evidence-linked model | reaudit BUG-10 | linked+typed | FIXED |
| P0-09 weighting | sum beats quality | best-single+capped boost | weighting property tests | 0.458<0.9 | FIXED |
| P0-10 impure reports | 2 pipelines/run | read-only generation | purity invariant test | zero deltas ×2 | FIXED |
| P0-11 boundary bypass | ~20 sites | services routed + scan | boundary scan test | clean | FIXED |
| P0-12 dual engines | both wrote table | one canonical engine | schema-version test | v2 only | FIXED |
| P0-13 mutation M-1 survived | survived 21 tests+eval | pinned formula + harness | mutation_check M-1..6 | 6/6 DETECTED | FIXED |

## 9–10. Performance / Resource Impact

- Net win: startup completion previously ran build_market_context ≈8× and the
  full pipeline 2×; now 1 pipeline + cheap store reads for reports.
- Added costs (measured negligible): fence JSON field on tasks; renewal thread
  per running task (daemon, event-stopped); duplicate_ratio O(n) hash pass per
  metrics tick; claim-support regex checks per extracted item (~µs each).
- Suite runtime 84s → ~92s (+invariants), acceptable.

## 11. Backward Compatibility

- Schema: additive only (new JSON fields/indexes); `_migrate` untouched paths
  keep working; legacy score_breakdowns labeled v1.
- Behavior changes are deliberate corrections (documented in docs/*): startup
  reports regenerate from stores instead of researching; opportunity_map shows
  stored candidates; validation_candidates no longer designs tests at render
  time (run `startup validate` instead); pause routes through scheduler jobs.
- One obsolete test updated deliberately (phase2 adaptive: fake corpus is
  ~100% duplicated under HONEST dup metrics; saturation-stop is correct).

## 12–14. Remaining Risks / Suspected Issues / Debt

- Known debt kept deliberately: CLI `_load2/_load3` storage handles (read
  paths, allowlisted, must shrink); duplicate error-class definitions in
  research_service.py; modes/base.py dead module; unused Opportunity fields
  (market_signal_evidence_ids etc.) — cleanup candidates, not correctness.
- Suspected (unfixed, low): ranking tie-bias toward insertion order;
  readiness cross-opportunity scoping; search-cache key ignoring freshness
  config. Tracked in BUG_AUDIT §Suspected.
- Highest-risk remaining area: **LLM-backed extraction quality in live runs**
  — grounding gates now fail closed, so weak local models will simply yield
  less accepted evidence (honest degradation, by design).

## Final Answers (spec §88)

1. **Architecturally-caused bugs:** BUG-01 (liveness outside execution),
   BUG-02 (no identity layer), P0-10 (reports coupled to research), P0-11
   (seam never enforced), P0-12 (two engines by accretion). The rest were
   localized logic errors enabled by missing invariants.
2. **Invariants now enforced by CODE:** INV-001..010 fully (DB fences, UNIQUE
   indexes, support gating, convergence ordering, purity-by-construction);
   INV-008 enforced by executable scan; INV-009 by writer+repair tool.
3. **Previously-trusted boundaries now validated:** scheduler ownership,
   report purity, service seam (API/MCP strict), evidence grounding, market
   sizing semantics, opportunity schema, project listing truth.
4. **Corrupted data & repair:** duplicated startup rows + polluted KB +
   unlinked conflict rows. Repair = `repair-startup` (dedupe by natural key,
   union provenance, mark LEGACY_UNLINKED, complete indexes) with auditable
   summary; idempotent, safe to rerun.
5. **Tradeoffs introduced:** fencing can reject a *finished* stale worker's
   result (work lost, state safe — logged for retry); upserts merge same-key
   entities (conservative normalization avoids dangerous merges);
   claim-support may downgrade nuanced-but-valid claims to PARTIAL (they
   still persist and count at reduced weight); read-only reports mean users
   must explicitly run discovery/validation (no hidden auto-research);
   PROVIDER_DEGRADED stops surface as flagged incompleteness rather than a
   confident CONVERGED.
6. **Uncertain:** real-world rate of false PARTIALLY/CONTRADICTS verdicts on
   nuanced legitimate claims under live-model extractions; syndication depth
   in target corpora (drives severity-inflation magnitude).
7. **Highest-risk remaining area:** live LLM extraction feeding the now-
   stricter gates — behavior is safe (fail-closed) but coverage quality is
   model-bound; watch rejection_rate dashboards after enabling a real model.
8. **Do NOT build yet:** new specialists/modes, multi-node scheduling,
   alternative persistence engines, richer scoring dimensions — until the
   suspected issues above are resolved and the debt list shrinks.

Reproduce everything:
    pytest tests/                       # 283 passed
    python scripts/mutation_check.py    # 6/6 DETECTED
    python scripts/reaudit.py           # 14/14 FIXED
    evals/runners/run_eval.py --offline # 17/17 PASS
