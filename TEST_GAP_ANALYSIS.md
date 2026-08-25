# TEST GAP ANALYSIS

Suite size: 231 tests, all offline, ~80s. Suite quality is uneven: strong on
platform lifecycle/sandbox/security mechanics; weak on research-correctness
semantics and service-layer wiring.

## Mutation experiment (performed)

**M-1**: `quality_gate` priority rule `missing<=2 → missing<=9` (everything high).
- Result: tests/specialists (21 tests) **PASS** — undetected.
- p5_startup_discovery_india_smb eval: **PASS** — undetected.
- Only the overhyped-failure task could catch it, and only when demand_ok also
  passes — i.e. one axis of a conjunctive guard is unobserved by 252 checks.
**Conclusion**: opportunity priority semantics are effectively untested.

## Weak / missing tests matrix (top items)

| Component | Critical behavior | Existing coverage | Gap | Failure mode if regressed | Priority |
|---|---|---|---|---|---|
| services/research_service.ask | GroundedQA wiring | none (CLI-only path tested) | API-level ask test | dead endpoint shipped silently (BUG-03 proves it) | P0 |
| scheduler lease/heartbeat | long-task single execution | crash-restart tests only (sleeps < lease) | slow-task + expired-lease + 2 workers | double orchestration (BUG-01) | P0 |
| StartupRepos idempotency | re-run leaves row counts stable | none | invariant test | unbounded duplication (BUG-02) | P0 |
| market.py sizing | year/funding rejection | conflict detection only | adversarial sentence corpus | fabricated market sizes (BUG-05) | P1 |
| claim faithfulness | claim ⊆ quote semantics | quote∈chunk only | truncation-inversion fixture | meaning-flipped evidence everywhere (BUG-09) | P1 |
| legacy extractor guards | $10M not a price | specialist regex only (old regex untested) | direct unit test on intelligence/startup._extract_prices | $1 prices in reports (BUG-04) | P1 |
| EventBus backpressure | audit lane durability | none | overflow test | silent audit loss (BUG-11) | P1 |
| hypothesis scoring | tier dominance | score formula unit tests exist? partial | 10×tier5 vs 1×tier1 property test | inverted confidence (RQ §hypothesis) | P1 |
| convergence semantics | silence≠convergence | threshold unit tests only | provider-outage scenario | false CONVERGED states | P1 |
| FTS lifecycle | no dup rows | search happy path | re-save test | recall pollution (BUG-07) | P2 |
| MCP tools end-to-end | every tool callable | list/perm tests; two tools never invoked | invoke-all-tools conformance test | TypeError tools shipped (BUG-06) | P2 |
| project.json vs DB | list≡get universe | none | orphan fixture | ghost listings (BUG-12) | P2 |
| report regeneration purity | no primary-state writes | none | write-audit via sqlite trace | derived view mutates truth (A-03) | P2 |
| startup gate priority formula | demand gating | indirect via eval | property tests on rubric/gate | hype inflation (mutation M-1 proof) | P1 |
| readiness scoping | per-opportunity isolation | none | cross-opp experiment fixture | inflated VALIDATION_READY (BUG-16) | P3 |

## Structural gaps
1. No service-layer contract suite: CLI paths bypass what API tests cover and vice-versa; BUG-03 class survives precisely because there is no "every endpoint/tool invoked once with offline fakes" conformance harness. Recommended: parametrized smoke that calls every API route and every MCP tool against platform_ctx; any TypeError/500 = fail.
2. No property/invariant layer: candidate invariants worth pinning —
   - evidence.status=REJECTED ⇒ excluded from all aggregators;
   - claims.supported_by ids exist; hypotheses.origin_refs exist;
   - opportunity without evidence_ids ⇒ notes contains SPECULATIVE;
   - build_market_context is row-count idempotent;
   - terminal jobs never transition;
   - fts_rows == evidence_rows for fresh DBs after N saves.
3. Mutation testing absent from workflow; M-1 shows why it's needed at least for scorers/gates/convergence.

## What existing tests DO catch (credit where due)
Terminal-absorbing save_job, lease reclaim basics, sandbox escapes, path
traversal, permission direction, backup tampering, prompt-injection report
boundaries, redaction, watcher change detection, KB roundtrip, staged gates,
interview critic, pricing normalization math.
