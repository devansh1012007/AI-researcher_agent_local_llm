# SYSTEM REASSESSMENT — Master Report

Scope: full history reconstruction + adversarial code/research/security/test
audit of GAR phases 1–5 as of this working tree (231 tests green, 17/17 eval
gates). Companion files: DECISION_HISTORY.md, BAD_DECISIONS.md,
BUG_AUDIT.md, ARCHITECTURE_AUDIT.md, RESEARCH_QUALITY_AUDIT.md,
SECURITY_AUDIT.md, TEST_GAP_ANALYSIS.md.

---

## 1. Executive summary

The platform layer is genuinely solid: crash-safe job lifecycle with
absorbing terminal states, verified backups, real sandboxing, permission
direction, offline determinism. The research *content* layer is where the
system quietly betrays its own invariants: quote verification without claim
faithfulness, count-based metrics that reward syndication, a convergence
signal that reads extractor failure as success, and two competing startup
engines writing one table. Two P0 defects are active today: scheduler lease
steal double-executes long research runs on the same DB, and startup domain
rows duplicate on every analysis pass. Neither is caught by the suite — both
were found by breaking assumptions, not by running tests.

## 2–3. What we built; decisions taken
See DECISION_HISTORY.md (25 decisions, dependency chains, reversibility).

## 4. Decisions that were correct (keep, do not touch)
- SQLite-as-truth + per-project files; absorbing terminal job states;
- event-driven finalization; audit-hook experiment sandbox; PathSandbox
resolve-semantics; downward-only MCP permissions; verified archives;
offline-first fakes with honest quotes; versioned prompts.

## 5–6. Weak / bad decisions
BAD_DECISIONS.md BD-01…BD-06: dual engines, stateful report regeneration,
lease liveness split, count-based aggregation, unverified idempotency,
misleading metric names.

## 7–8. Current architecture & drift
ARCHITECTURE_AUDIT.md: intended-vs-actual diagrams, 10-item drift register.
Headline: the service seam exists but ~20 call sites bypass it; reports
mutate primary state; graph vs srepos dual representations disagree.

## 9–10. Critical & silent bugs
BUG_AUDIT.md (16 findings): P0 = BUG-01 double-execution, BUG-02 duplication.
Silent class: BUG-03 dead ask endpoint, BUG-04 $1 prices, BUG-09 meaning-
flipping truncations, BUG-10 un-analyzable conflicts, BUG-11 dropped audit
events, always-zero dup telemetry.

## 11. Security problems
SECURITY_AUDIT.md: localhost-open API default (S-01), injection payoff via
BUG-09, silent mock-provider fallback (S-03), env-borne sandbox root (S-04).
No exploitable path found that crosses machine boundary under LOCAL_ONLY.

## 12. Research-quality problems
RESEARCH_QUALITY_AUDIT.md: four mechanisms undercutting honesty — claim
faithfulness, aggregation-by-count, mislabeled metrics, hypothesis formula
contradicting evidence_quality module. Startup-specific: P4 constant severity,
funding→payment leak, market-size first-number parsing.

## 13. Test weaknesses
TEST_GAP_ANALYSIS.md: mutation M-1 survived entire unit suite + golden eval;
no service-conformance harness (why BUG-03/06 shipped); missing invariant
layer (idempotency would have caught BUG-02 pre-release).

## 14–15. Performance / resources
Measured hotspots: build_market_context ≈8×/completion each doing O(N) table
scans (compounds with BUG-02 duplication); FTS bloat; report regeneration
runtime scales with pipeline not rendering. No fd/thread leaks observed in
scheduler stop cycles; EventBus queues bounded (by dropping — see BUG-11).

## 16. Data integrity
Dual truth risks: project.json vs DB listing; events.jsonl vs platform_events
(no join); graph vs srepos competitor representations; legacy vs rubric score
schemas in one column. No reconciliation jobs exist anywhere.

## 17. Highest-risk technical debt
1) Legacy StartupIntelligence still in CLI/report/orchestrator-fallback paths
2) report→pipeline coupling 3) FTS append-only 4) ID counter restart hazard
5) `_startup_gates` tautology (`or True`) masking intent.

## 18. What should be REMOVED
modes/base.py (dead), duplicate NotFoundError/ConflictError defs,
StartupReportWriter.generate_all (unreferenced), seed_counter, dead loop
intelligence/startup.py:91-92, `or True` condition, unused Opportunity fields
(market_signal_evidence_ids, pricing_evidence_ids, secondary_assumptions) or
wire them, GapCategory.COMPETITOR_GAP/VALIDATION_GAP (emit or delete).

## 19. What should be REFACTORED
BD-01..BD-06 replacements; llm_calls naming fine but add provider-failure
counters; unify event vocabularies behind one recorder API; single
opportunity-score schema (v2 dict with schema_version field).

## 20. What should be PRESERVED
Platform core exactly as is (scheduler lifecycle semantics minus BUG-01 hole),
sandbox trio, backup verify-before-touch, fakes philosophy, eval gate concept
(with honest implementations), specialist analyzers' deterministic fallbacks.

## 21. What should be REBUILT (small, targeted)
- Lease renewal mechanism (thread-per-claim).
- Market-size parser around anchored spans.
- Hypothesis confidence via aggregate_claim_strength.
- Convergence classification separating SATURATED from PROVIDER_DEGRADED.

## 22. Recommended architecture (delta, not rewrite)
Same skeleton. Enforce: services-only interface rule (lint test), read-only
report path, one startup engine, upsert discipline, fenced leases, unified
recorder for events. Net LOC change expected NEGATIVE after legacy removal.

## 23–24. Priority order & migration
P0: BUG-01 fix (+regression), BUG-02 upserts (+invariant test), BD-02
decoupling (orchestrator passes pipeline result to generator).
P1: BD-01 engine consolidation; BUG-03/04/05/09; BD-04 aggregator reuse;
BD-06 honest metrics; S-01 token default.
P2: conformance harness (all endpoints/tools), FTS delete path, event-vocab
unification, BUG-07/08/10/11/12, mutation testing for scorers/gates.
P3+: dead-code purge list §18, S-03/S-04, readiness scoping.

Migration strategy: all P0/P1 items are additive-guards or call-site moves;
no schema migrations required except optional `schema_version` inside
score_breakdown JSON. Legacy-engine retirement is feature-flag-free because
its callers are enumerated (5 sites).

## 25. Remaining unknowns
- Whether Ollama-backed live extraction changes claim-truncation frequency in practice [needs live corpus study]
- Real-world syndication rate in target corpora (severity inflation magnitude)
- SQLite contention profile under genuine multi-job load (max_jobs>1 never exercised locally)
- Prompt-injection survival rate once claim-span validation exists

---

# 88. Final answers

**Q1 — If we keep building features without fixing identified problems, what breaks first?**
The scheduler double-execution (BUG-01). It is load-, time-, and
config-dependent rather than input-dependent: every deep-research run longer
than lease_seconds (default 120s — i.e., essentially all real runs) with more
than one worker thread is a coin flip toward two orchestrators writing one
project DB concurrently. Every feature layered on jobs/scheduler/watchers
increases worker uptime and therefore collision probability. The corruption
it produces will be attributed to everything else first.

**Q2 — Single highest-leverage architectural correction before anything else?**
Restore the single-writer invariant end to end: (a) fence leases with
execution-time heartbeats + atomic attempt bumping (kills concurrent
orchestration), and (b) make reports read-only by computing the specialist
pipeline once in the orchestrator and passing results into the generator.
Together these re-establish "one process mutates a project's truth at a time"
— the precondition every other subsystem (dedup, scoring, KB seeding,
convergence) silently assumes.

**Q3 — Which existing assumption about this project is most likely wrong?**
"Verified provenance ⇒ trustworthy content." The system proves a quote exists
in a source; it never proves the claim represents that quote. All downstream
discipline (tiers, gates, critics) consumes claims as if faithful. The audit's
truncation/inversion repros show this assumption failing at the very first
pipeline hop — meaning the platform's celebrated evidence-groundedness is
currently grounded in an unchecked leap.

**Q4 — Which bug lets the system appear to work while producing incorrect research?**
Three-way tie, ranked by invisibility:
1. BUG-09 claim↔quote faithfulness — every gate stays green on inverted claims;
2. "duplicate_rate"-as-rejection-ratio driving CONVERGED (research stops and
   reports confidently precisely when extraction was hallucinating worst);
3. BUG-02 row duplication silently multiplying competitors/pains/personas so
   market maps and rankings inflate run over run.
If forced to name one: **BUG-09**, because it corrupts the primitive every
other correctness property is built on, while every dashboard, gate, and test
continues to report health.
