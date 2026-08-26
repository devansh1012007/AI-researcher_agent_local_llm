# Post-Stabilization Architecture Review

> **STATUS UPDATE (Phase-5 Phase-0):** blockers **F-01** and **F-02a/b are
> REPAIRED**. The persist gate is restored (duplicated block removed;
> extractor gained a `persist` flag; unconditioned repos-writes now honor
> the read-only convention), and `requeue_task` is status-guarded with fence
> monotonicity preserved. Proofs flipped to hard regressions in
> `tests/invariants/test_gate_findings.py`; the startup-golden purity
> annotation was removed. Verdict below is the historical review record —
> the platform now meets its own §52 bar with respect to those two blockers.
> Open findings: F-03…F-07 (non-blocking, scheduled).

---

**Question:** can the platform safely support another substantial specialist
without weakening, bypassing, duplicating, or silently violating the
invariants established during stabilization?

**Method:** documented invariant → actual enforcement → all write paths →
all entry points → failure paths → future extension paths → adversarial test
→ golden workflow. Every load-bearing claim was verified against source
(file:line); every produced finding is captured as an executable proof in
`tests/invariants/test_gate_findings.py` (strict xfail — flips to a hard
regression the moment the defect is fixed).

**Phase discipline:** this review is REPORT-ONLY for production defects
(user-approved). Findings are documented; nothing was fixed.

---

## 1. Executive Summary

Stabilization did its job for the paths it touched: task fencing, natural-key
identity, claim-support grounding, honest convergence metrics, opportunity
schema versioning, and service-boundary scans are real, executable, and
adversarially tested (64 invariant tests + 6/6 mutations + 14/14 audit
reproductions).

But the gate exists to find what stabilization *missed*. It found seven
findings, two of which are **blockers** under §52:

- **F-01 (BLOCKER)** — report generation mutates primary state: the
  `persist=False` gate is dead code, masked by idempotent writes and a
  row-count-only purity oracle.
- **F-02a/b (BLOCKER)** — manual task requeue has no ownership guard and
  resets the fencing token (`attempts=0`), reintroducing the BUG-01
  double-writer shape through the retry door exposed to CLI and API.

Five further findings (F-03…F-07) are dangerous-drift or traceability gaps:
serious, scheduled work — not blockers by §52's letter.

## Verdict: NOT_READY

for the next major specialist until F-01 and F-02 are repaired. The repair
surface is small and precisely located, and every finding already ships an
executable proof that fails today and becomes its own regression test when
fixed. The extension capability itself (contract, INV-014 detectors, dual
goldens, regression rule) is built and verified — hence "one focused repair
phase away", not "far".

---

## 2. Current Architecture (as built)

Reconstructed from source via three independent component sweeps; citations
spot-checked against the tree.

### Composition root & execution

| Component | Owns | Mutates via | Notes |
|---|---|---|---|
| `services/context.py::ServiceContext` (:31–88) | AppConfig + PlatformDB + EventBus; lazy scheduler wiring 5 runners | constructs the only sanctioned PlatformDB outside storage internals | composition root for CLI/API/MCP |
| `platform/scheduler.py` | worker pool; lease-renewal thread inside `_execute`; event-driven `_advance_one` finalization | fenced PlatformDB calls | fenced execution path sound (§6) |
| `storage/platform_db.py` | jobs/tasks/watchers/events in `platform.sqlite` | atomic conditional UPDATEs; fence = monotonic `attempts` (:251); terminal-absorbing `save_job`; **exception: `requeue_task` :369–386 (F-02)** | single-writer seam |
| `core/orchestrator.py` | project state machine (21 `.sm.transition(` sites; only other domain caller is `hypothesis_engine.py:551`), budgets, `_startup_pipeline_result` cache | repos over per-project Database | workers propose; harness decides |
| `storage/database.py` | per-project SQLite/WAL, per-thread conns, `_init_lock`; `_STARTUP_UNIQUE_INDEXES` ×9 | `upsert/get/list/count/delete` | DB constraints backstop app checks |
| `specialists/startup/*` | startup domain models/repos/policies/analyzers/opportunities/kb/reports/service | repo seams: `save_natural` ×9 sites; enumerated justified `save()` sites | consumes orchestrator/services; KB is the one owned side-db |

### Interfaces

- **CLI** (`cli/main.py`, ~40 commands): canonical service paths for
  pause/jobs/watchers/startup surface; legacy read handles `_load2/_load3`
  allowlisted. Violations found: direct `Database(` construction :1049;
  direct repo writes :338/:386; duplicate authoritative experiment paths
  :539/:569 vs `ExperimentService` (knowledge_service.py:288).
- **API** (`api/app.py`): zero storage construction ✓. Seven endpoints touch
  `ctx.platform_db` / `ctx.scheduler` directly, incl. mutating
  `requeue_task` :247.
- **MCP** (`mcp_server/server.py`): zero storage construction ✓; single
  permission choke point :341 (downward-only verified at permissions.py);
  one direct platform read :380; dead `_load_orch` :580.

### Grounding pipeline

`EvidenceWorker._extract_chunk` → `verify_quote` (pipeline/evidence.py:64)
→ fail-closed claim-support ladder (pipeline/claim_support.py:110–224;
CONTRADICTS/UNRELATED ⇒ REJECTED, audit row kept) → persistence. Startup
analyzers ground transitively through extracted evidence. Exception found:
experiment ingestion persists tier-1/SUPPORTED evidence without either gate
(F-03, result_ingestion.py:63–78).

### Reports

`ReportGenerator.write_startup_research` consumes precomputed
`_startup_pipeline_result` or `_startup_view_from_store`;
`build_market_context(persist=False)` is intended read-only but its gate is
dead (F-01). A further report-time mutation path exists in reasoning reports
(reports/reasoning_reports.py:23 → hypothesis_engine.py:487–512).

### Failure semantics layers

Fetch layer: exemplary typed errors + classified retries. Search/academic:
typed exceptions exist but seven except-blocks end in bare `return []`
(F-05). LLM layer: typed `LLMError`, zero internal catch sites; convergence
tiebreaker call unguarded (F-04, convergence.py:90).

---

## 3. Intended vs Actual — drift classification

| # | Observation | Class |
|---|---|---|
| D-1 | INV-004 enforced by dead gate; three write leaks (service.py:99–101 clobber; graph INSERTs via extract_all; report-time hypothesis-score save) | **BROKEN_ARCHITECTURAL_CONTRACT** |
| D-2 | `requeue_task`: no status guard + fence reset, contradicting docstring; reachable from CLI :950 / API :247 | **BROKEN_ARCHITECTURAL_CONTRACT** |
| D-3 | CLI constructs `Database(` (:1049); boundary scan lacks `Database\(` pattern | DANGEROUS_DRIFT |
| D-4 | CLI direct repo writes (:338, :386) without service ops | DANGEROUS_DRIFT |
| D-5 | Duplicate experiment authority: CLI vs `ExperimentService` | DANGEROUS_DRIFT |
| D-6 | Provider conflation ×7 + global-cache poisoning of outages across projects | DANGEROUS_DRIFT |
| D-7 | Convergence tiebreaker unguarded ⇒ degradation becomes FAILED | DANGEROUS_DRIFT |
| D-8 | Experiment evidence bypasses grounding without documented carve-out | DANGEROUS_DRIFT |
| D-9 | `OpportunityRepo` has no `natural_key()`; uniqueness = in-memory problem-string match only | TECHNICAL_DEBT (elevated) |
| D-10 | Unfenced scheduler-loop heartbeat (:276) beside the fenced renewal thread | MINOR_DRIFT |
| D-11 | `_promote_blocked` on `random_chance(0.05)` — probabilistic housekeeping | MINOR_DRIFT |
| D-12 | Job/event visibility reads ctx handles directly in all three interfaces (no JobControlService) | VALID_EVOLUTION |
| D-13 | Dead code: MCP `_load_orch`; duplicated NotFound/Conflict error defs; CLI ask/methodology re-implementations | TECHNICAL_DEBT |
| D-14 | `docs/architecture.md` frozen at Phase-2 (no platform/services/specialists) | TECHNICAL_DEBT |
| D-15 | `ProjectService._has_db_row` opens raw ro sqlite3 connection (research_service.py:90–105) | MINOR_DRIFT |
| D-16 | `PersistentScheduler.submit_job` annotation references unimported `ResearchJob` (latent under `from __future__ import annotations`) | TECHNICAL_DEBT |

---

## 4. Findings (F-01 … F-07)

Each finding: problem → evidence → executable proof → classification.

### F-01 — Report generation mutates primary state  ⛔ BLOCKER
- **Evidence:** `specialists/startup/service.py` — `:98` sets
  `srepos = live_srepos if persist else None`; a duplicated block at `:99–101`
  immediately re-calls `_repos_for(orch)` and clobbers it. All analyzer writes
  fire during reports, including KB seeding (`:106–109`) and market creation
  (`:128–129`) on projects without one. Two further leaks:
  graph INSERTs via `StartupIntelligence.extract_all` (:111–112 →
  intelligence/startup.py:167–168 → graph_store.py:108–125) and report-time
  hypothesis mutation (reports/reasoning_reports.py:23 → :487).
- **Why tests missed it:** `TestReportPurity` oracle is table ROW COUNTS on a
  pre-populated project; every leaked write is idempotent-by-natural-key.
- **Proof:** `test_gate_findings.py::TestF01ReportPurityLeak` (strict xfail,
  WAL-safe logical fingerprint incl. cross-project KB).
- **Class:** BROKEN_ARCHITECTURAL_CONTRACT (INV-004).

### F-02 — Manual requeue breaks single-writer ownership  ⛔ BLOCKER
- **Evidence:** `platform_db.py::requeue_task` (:369–386): no status filter
  (docstring says "dead-lettered/failed"; code accepts ANY status incl. a task
  under a live lease) and sets `attempts = 0` — resetting the fencing token.
  After requeue+claim the re-issued fence equals a previously issued one; a
  still-running stale execution becomes indistinguishable from the new owner —
  the exact BUG-01 shape via the manual-retry door. Exposed at CLI :950 and
  API :247.
- **Proofs:** `TestF02RequeueFenceHazards` (two strict-xfail tests).
- **Class:** BROKEN_ARCHITECTURAL_CONTRACT (INV-001/002).

### F-03 — Experiment evidence bypasses grounding, undocumented
- **Evidence:** result_ingestion.py:63–78 persists Evidence tier-1 /
  SUPPORTED / confidence=0.85 / legacy support-factor with empty
  `support_verdict`; neither gate runs; carve-out absent from invariants doc.
- **Proof:** `TestF03ExperimentGroundingBypass`. INV-014 auditor currently
  allowlists `experiment_result` explicitly so the exception is *visible*.
- **Class:** DANGEROUS_DRIFT (INV-005). Requires a policy decision
  (document the provenance carve-out or route through gates), then promotion
  of INV-014 to hard enforcement.

### F-04 — Convergence LLM tiebreaker escalates outage to FAILED
- **Evidence:** convergence.py:90 calls `provider.structured()` unguarded;
  `LLMError` escapes `evaluate()` → orchestrator marks project FAILED —
  defeating honest-degradation intent exactly where degradation matters.
- **Proof:** `TestF04ConvergenceTiebreakerOutage`.
- **Class:** DANGEROUS_DRIFT (INV-006).

### F-05 — Provider failure conflated with empty results (×7)
- **Evidence:** arxiv.py:39, crossref.py:56, semantic_scholar.py:31/:52,
  openalex.py:59 (+2 siblings): `except … log.warning(…); return []`.
  Downstream retrieval caches empties GLOBALLY for `cache_ttl_hours`, so one
  transient outage poisons identical queries across projects.
- **Proof:** `TestF05FailureConflationCensus` (AST-precise census).
- **Class:** DANGEROUS_DRIFT (INV-012).

### F-06 — Antonym/direction inversion undetected by claim-support
- **Evidence (new, from §14 matrix extension):** "Churn decreased" vs quote
  "Churn increased" → STRONGLY_SUPPORTS (vocabulary overlap; lexicon has
  explicit negation tokens only). Time-scope, exception-stripping and
  "at least"-tightening cells all correctly refuse SUPPORTS (added as passing
  tests).
- **Proof:** `TestF06AntonymInversionUndetected`.
- **Class:** DANGEROUS_DRIFT (INV-005 quality).

### F-07 — Opportunities never link pricing/signal evidence
- **Evidence (new, from startup golden baseline):** pricing_plans rows carry
  `evidence_id`; materialized opportunities carry core pain `evidence_ids`
  but `pricing_evidence_ids`/`market_signal_evidence_ids` are empty on ALL
  rows even when matching artifacts exist in-store → §23/§42 traceability is
  partial. Related: D-9 (no natural key on OpportunityRepo).
- **Proofs:** golden KNOWN_VIOLATION telemetry + `TestF07…Linkage` xfail.
- **Class:** TECHNICAL_DEBT (elevated; flagship-artifact integrity).

---

## 5. Invariant matrix (verified coverage)

| Invariant | Protects | Enforcement | Callers covered? | Gate verdict |
|---|---|---|---|---|
| INV-001/002 | one writer; stale fences rejected | claim/finish/release/heartbeat(fence); renewal thread | scheduler path YES; **manual-retry path NO (F-02)** | NOT READY |
| INV-003 | idempotent domain identity | save_natural + 9 UNIQUE indexes | 9/11 entity tables; **OpportunityRepo missing (D-9)**; race backstop now proven threaded | READY W/ CONDITIONS |
| INV-004 | read-only reports | precomputed/store-view writers + persist=False | **gate dead (F-01)**; purity oracle strengthened to logical fingerprints | NOT READY |
| INV-005 | grounding two-gate | claim_support wired into extraction | extraction YES; **experiment path bypass (F-03); antonym gap (F-06)** | READY W/ CONDITIONS |
| INV-006 | honest convergence | ordered deterministic checks + separated rates | ordering verified vs cases A–H; **tiebreaker leak (F-04)** | READY W/ CONDITIONS |
| INV-007 | quality × independence weighting | aggregate_claim_strength caps; SUPPORT_FACTOR | best-single dominance + ≤0.35 cap verified (tier-1 v swarm test) | READY |
| INV-008 | service boundary | scan test (repo-bundle patterns) | API/MCP clean; **CLI blind spots (D-3/D-4/D-5)** | READY W/ CONDITIONS |
| INV-009 | conflict both-sides | Contradiction fields + repair marking | reaudit BUG-10 green; golden contradictions counted | READY |
| INV-010 | canonical score schema | score_rubric v2 + render labeling | validator now matches canonical factors/reasons shape | READY |
| INV-011 | money parsing | policies.parse_money + post-filter | reaudit BUG-04/05 green | READY |
| INV-012 | failure ≠ empty | typed provider errors | fetch layer yes; **search/academic conflation (F-05)** | READY W/ CONDITIONS |
| INV-013 | project isolation | per-project DB + scoped queries | repos+FTS verified; global caches hold public web content only; KB opt-in shared | READY |
| INV-014 (new) | specialist extension contract | static scan + auditors (detector seam) | specialists scanned; promotion pending F-03 | READY W/ CONDITIONS |

---

## 6. Single-writer verification (§6–8)

Scheduler execution path verified sound: atomic conditional claim, lease
renewal inside `_execute` at `min(heartbeat, lease/3)` WITH fence,
`finish/release/heartbeat` reject mismatched owner/fence (`StaleTaskOwner`),
dead-owner recovery exactly-once, cancelled jobs fenced, terminal states
absorbing (existing suite + adversarial additions). Write-path census found
**one unprotected mutator**: `requeue_task` (F-02) — everything else either
enforces ownership or is an offline maintenance tool operating on explicit
handles (data_repair, KB seed) whose ownership story is "operator-invoked".

## 7. Entity identity verification (§9–11)

Sequential idempotency (×3 pipeline runs converge), natural-key resolution
keeping original IDs, legacy-pollution repair, KB seeding idempotency: all
covered and green. NEW: threaded concurrent `save_natural` (8 writers, same
key) converges to exactly one row — UNIQUE backstop proven under races.

## 8. Grounding verification (§12–15)

LLM→persistence census: extraction path fully gated; startup analyzers ground
transitively; hypothesis/experiment/memory paths identified with experiment
ingestion as the sole ungated producer (F-03). Faithfulness matrix extended:
time-scope, exception-stripping, quantifier-tightening cells added (all pass);
direction-inversion exposed F-06. No specialist ships its own validator —
single canonical ladder confirmed.

## 9. Convergence verification (§16–17)

Cases A–H mapped: progress→continue, outage→PROVIDER_DEGRADED, cached
silence→saturation-shaped (not degraded), rejection-storm→DEGRADED, true
duplication→CONVERGED, budget/max-iter distinct reasons, metric semantics
(dup vs rejection rates separate). Gap-unresolved case documented as policy
note (rate-based convergence may stop with open gaps; gaps remain visible in
reports). Residual hole = F-04.

## 10. Service boundary verification (§20–21)

API/MCP: zero storage construction; permission choke point single; wiring
conformance net executes EVERY tool/endpoint offline. CLI: three violations
(D-3/D-4/D-5) beyond the documented allowlist. Interface-equivalence is
guaranteed where all three route through services; violations enumerated for
the repair backlog.

## 11. Report purity verification (§18–19)

Oracle upgraded from row-counts to WAL-safe logical store fingerprints
(shared `extension_audit.store_fingerprint`). Academic-path generation is
pure (golden scientific proves it end-to-end). Startup-path generation
mutates (F-01) — annotated KNOWN_VIOLATION in the startup golden so the
regression rule stays honest until fixed.

## 12. Evidence quality verification (§24)

Best-single dominates; corroboration boost capped ≤0.35; SUPPORT_FACTOR
multiplies tier weight; tier-5 swarm cannot outvote tier-1 (asserted).
Duplicate interim formula noted in consolidate_claims (different tier table,
no support factor) — flagged as anti-slop debt (R-6).

## 13. Conflict integrity verification (§25–26)

Contradiction model carries both sides + type; market-size cross-validation
raises NUMERICAL conflicts with evidence links; legacy unlinkables marked,
never fabricated (reaudit BUG-10). Golden runs count contradictions as first-
class metrics.

## 14. Project isolation verification (§27)

Per-project SQLite files, question-derived ids, project-scoped repos/FTS;
cross-project read test green. Shared surfaces reviewed: global search cache
holds PUBLIC web content keyed by URL/query (not private state); market KB is
opt-in shared memory by design; embeddings fall back deterministically.
Isolation holds across CLI/API/MCP/retrieval surfaces tested.

## 15. Long-running task verification (§30, §35)

Human approval gate for experiments verified (awaiting_approval refuses
execution). Scheduler inheritance (lease/fence/retry/cancel/checkpoint/
limits) is architectural for anything submitted through `submit_job`;
outside-execution ownership remains convention-only outside the fenced paths
— covered by extension-contract checklist requiring scheduler use.

---

## 16. New-specialist readiness (§31–37, §49–50)

Delivered this phase: `docs/specialist_extension_contract.md` (provide-vs-
own split, checklists for entities/scores/tasks/claims/reports),
`docs/extension_invariants.md` (INV-014), positive fixture proving the
canonical path enforces identity/grounding/ownership/purity/score-schema
automatically, five negative fixtures each proving a tripwire fires, plus a
static scan keeping specialists off raw storage. Verdict: the CONTRACT has
teeth at detector level today; runtime blocking follows the F-03 resolution.

## 17–18. Golden runs

Scientific: PASS — all hard checks + exact baseline reproduction (~3s).
Startup: PASS with two annotated KNOWN_VIOLATIONS (F-01 purity, F-07
linkage) — the regression rule therefore rejects drift while truthfully
representing open findings. Baselines record git sha/py version/config +
update reason. Live mode stubbed behind `--live` as a non-blocking realism
check (see docs/golden_research_runs.md).

## 19. Regression baseline (§45)

```bash
pytest && pytest tests/invariants -q && python scripts/mutation_check.py \
  && python evals/runners/run_golden.py
```

Current state at review time: 295 passed / 1 skipped / 8 xfailed ·
invariants 64+8xfail · mutations 6/6 detected · reaudit 14/14 FIXED ·
goldens 2/2 PASS (exact match @ f9e3d8d).

## 20. Remaining risks

R-1 F-03/F-04/F-05/F-06 degrade honesty guarantees under provider stress —
    precisely the conditions real deployments hit.
R-2 Detector-level INV-014 means a specialist ignoring the contract is caught
    by CI, not prevented at write time.
R-3 Global cache poisoning window (F-05 interaction) spans projects.
R-4 No JobControlService: job ops bypass formal service ops (D-12).
R-5 docs/architecture.md stale (D-14) — onboarding hazard.

## 21. Blockers (must fix before next specialist)

1. **F-01** — restore persist gate (delete duplicated block service.py:99–101);
   add content-level purity assertion; remove startup-golden annotation.
2. **F-02a/b** — guard requeue (only DEAD/FAILED/SKIPPED, never live lease)
   and preserve fence monotonicity (e.g. attempts = max(attempts)+1 on
   requeue); flip both xfails to hard regressions.

## 22. Recommendations (non-blocking, prioritized)

R-1 Settle F-03 carve-out in invariants doc; then promote INV-014 auditors to
    write-seam enforcement (+mutation entry).
R-2 Guard convergence tiebreaker with typed except → PROVIDER_DEGRADED.
R-3 Route provider failures through typed errors; scope or key global caches
    by availability; consider negative-result caching semantics.
R-4 Introduce JobControlService wrapping platform handles; extend boundary
    scan with `Database\(` pattern; fold CLI approve/add-result through
    ExperimentService.
R-5 Add antonym/direction pair table to claim_support lexicon.
R-6 Consolidate consolidate_claims onto aggregate_claim_strength; give
    OpportunityRepo a natural_key (+UNIQUE index) and wire pricing/signal
    linkage (F-07).
R-7 Rewrite docs/architecture.md against the actual map (this document's §2
    is the seed); delete dead code (D-13/D-16).

## 23. Final readiness decision

# Decision: NOT_READY (for the next major specialist phase)
# Reason: §52 blockers F-01 (reports mutate state) and F-02a/b (ownership
# bypass via manual retry) are active; both break written invariants that a
# second specialist would immediately rely on.
# Why not READY_WITH_CONDITIONS: conditions must be enforceable today;
# these two defects are enforced-against (tests fail loudly) rather than
# enforced. Proceeding would normalize writing specialists atop known-broken
# foundations.
# Path to READY: ship blocker repairs (small, located, proof-backed), flip
# the strict-xfails to hard assertions, re-run goldens with annotations
# removed, re-issue this gate. Estimated scope: one focused repair phase.

---

## Appendix A — Answers to the ten final questions (§57)

1. **Add specialist w/o bypassing invariants?** Yes — via the extension
   contract; detectors verify compliance in CI (runtime blocking pending R-1).
2. **New persisted entity w/o inventing identity?** Yes — natural_key + 
   UNIQUE protocol is codified (checklist in contract); exception to fix:
   OpportunityRepo itself (R-6).
3. **Persist LLM claim w/o canonical grounding?** Through the wired pipeline,
   no. Directly, storage accepts — caught by INV-014 auditor in CI, not at
   write time (honest answer: partially).
4. **Long-running task w/o fencing?** Not through the scheduler. Yes through
   `requeue_task`'s reset (F-02) — which is why the verdict is NOT_READY.
5. **New report mutate authoritative state?** Nothing stops a rogue writer at
   runtime today; the fingerprint guard catches it in CI, and F-01 shows even
   shipped reports can violate. Blocker listed.
6. **Competing scoring model?** Detectable (schema validator flags non-v2,
   reason-less scores) but not prevented — same detector/enforcement nuance.
7. **CLI/API/MCP bypass service layer?** API/MCP: no. CLI: three enumerated
   violations exist (D-3/4/5) — enforceable by extending the scan; tracked.
8. **Cross-project influence?** Private state: no (isolation holds). Public
   web cache sharing and opt-in KB are designed behaviors, documented.
9. **Tell improved vs degraded research quality?** Yes — goldens (exact
   baselines + invariant checks), eval thresholds, mutation harness.
10. **Provable by automated tests?** Yes — every finding here has an
    executable proof; every claim of readiness cites a named test/script.

## Appendix B — Deliverables produced by this gate

- `docs/post_stabilization_architecture_review.md` (this file)
- `docs/specialist_extension_contract.md`
- `docs/golden_research_runs.md`
- `docs/extension_invariants.md` (+ INV-014 row in docs/invariants.md)
- `evals/golden/{scientific,startup}/` manifests + recorded baselines
- `evals/runners/run_golden.py` (offline default, --live flag, §46 bump rule)
- `src/research_engine/specialists/extension_audit.py` (INV-014 auditors)
- Tests: `tests/invariants/test_gate_findings.py` (F-01…F-07 proofs),
  `test_extension_contract.py` (positive/negative fixtures + INV-014 scan),
  concurrent-identity race test, faithfulness matrix cells
