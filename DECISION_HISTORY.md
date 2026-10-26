# DECISION HISTORY

Reconstructed from code, docs, AGENTS.md, and session history. Status classes:
VALID / VALID-BUT-REFINE / CONTEXT-DEPENDENT / PREMATURE / UNNECESSARY /
OVER-ENGINEERED / UNDER-ENGINEERED / CONTRADICTORY / HARMFUL / INVALID.
Every claim is FACT (code/exec-proven) unless marked INFERENCE/HYPOTHESIS.

| ID | Decision | Phase | Original reason | Key assumption | Affected components | Current status | Evidence |
|----|----------|-------|-----------------|----------------|--------------------|----------------|----------|
| D01 | Centralized orchestrator; workers propose, harness decides | P1 | determinism, budget control | one process runs one project | core/orchestrator.py | **BROKEN IN PRACTICE**: scheduler lease steal runs two orchestrators on one project DB (BUG-01) | scheduler.py `_worker_loop`; repro in BUG_AUDIT |
| D02 | SQLite per project = source of truth; Markdown derived | P1 | durability + regenerability | regeneration is side-effect-free | reports/* | **CONTRADICTED**: startup report regeneration mutates primary state (runs full specialist pipeline) | generator.py:387-389 |
| D03 | Quote verification gates every evidence item | P1 | anti-hallucination | verifying quote∈chunk implies claim faithfulness | pipeline/evidence.py | **WEAK**: claim↔quote faithfulness never checked; truncated claims flip meaning silently | evidence.py:62-97,157 |
| D04 | Claim-level confidence computed, never asserted | P1/P2 | auditability | aggregate_claim_strength used everywhere | reasoning/evidence_quality.py vs hypothesis_engine.py | **CONTRADICTED**: score_hypothesis sums tiers (10×tier-5 > 1×tier-1), ignoring the platform's own max-based aggregator | hypothesis_engine.py:433-461 |
| D05 | Sequential per-prefix IDs (`ev_000001`) via process-global counter | P1 | human-readable provenance | single writer process | core/ids.py | **FRAGILE at scale**: restart resets counters; collision only avoided by fresh-workspace convention; `seed_counter` dead | ids.py:9-23 |
| D06 | Recursive loop stops on new-evidence-rate / dup-rate thresholds | P1 | stop wasting money | metrics reflect information gain | convergence.py | **INVALID METRICS**: "duplicate_rate" is actually rejection ratio; dead-provider silence triggers CONVERGED | orchestrator.py:581, convergence.py:52-57 |
| D07 | Budget exhaustion routes to synthesis as success-shape | P1 | always deliver a report | user reads caveats | orchestrator.py:397-410 | VALID-BUT-REFINE (stop_reason preserved, but state=COMPLETED indistinguishable downstream) | |
| D08 | Global fetch/search caches under `<data_dir>/_global` | P2 | laptop-friendly dedup | cache key captures result-relevant inputs | fetching.py, retrieval.py | CONTEXT-DEPENDENT; documented purge ritual is operational debt | AGENTS.md gotcha |
| D09 | Evidence FTS append-only index on every save | P2 | fast recall | evidence rows are write-once | repositories.py:176-179 | **VIOLATED**: re-saves duplicate FTS rows (3 hits for 1 doc verified); no delete path | BUG-07 |
| D10 | Competing-hypothesis families mandatory (+null/artifact links) | P3 | scientific hygiene | academic path uses lifecycle machine | hypothesis_engine.py | VALID for academic; **bypassed**: RefinementLoop sets `.status` directly (AGENTS-forbidden pattern) | hypothesis_engine.py:552 |
| D11 | Business hypotheses as fixed 4-statement chain | P3 | structure for validation | chain covers viability dims | generate_business_hypotheses | UNDER-ENGINEERED: no assumptions existed until P5; no alternative_of linkage | falsification gap fixed late |
| D12 | Platform state in platform.sqlite; jobs absorbing terminal states | P4 | crash safety | leases renewed during execution | platform_db.py, scheduler.py | **HOLE**: heartbeats only run between tasks; any task > lease_seconds double-executes despite cap=1 (verified) | BUG-01 |
| D13 | Event-driven finalization + SQL-absorbing terminals | P4 | kill flaky finalization | stale objects can't resurrect jobs | save_job guard | VALID | chaos-tested |
| D14 | Experiment sandbox via sys audit-hook + RLIMIT + env scrub | P4 | local code exec containment | guard precedes user code | experiments/runner.py | VALID (tested network/subproc/fs escapes; ssl import safe) | tests/experiments |
| D15 | API auth token only for non-local binds | P4 | dev ergonomics | localhost = trusted | cmd_serve, api auth | CONTEXT-DEPENDENT/**RISK**: any local process can drive research API unauthenticated; token optional by default | security note S-03 |
| D16 | Hand-rolled MCP stdio JSON-RPC; downward-only permission implication | P4 | zero-dep adapter | tools stay thin | mcp_server/server.py | **DRIFTED**: handlers construct Orchestrator/ReasoningRepos directly; two tools crash when invoked (TypeError) | server.py:452, research_service.py:204 |
| D17 | Service layer as sole interface seam (CLI/API/MCP→services) | P4 | one business path | interfaces don't touch stores | services/* | **WIDELY BYPASSED**: ~20 CLI sites construct Orchestrator/repos directly; CLI mutates state machine itself | ARCHITECTURE_AUDIT §1 |
| D18 | Startup specialist consumes platform via services; own repos bundle | P5 | domain isolation | entities upserted idempotently | specialists/startup | **BROKEN**: every context build duplicates domain rows (markets ×4 per run verified) | BUG-02 |
| D19 | Legacy StartupIntelligence retained alongside specialist engine | P5 | back-compat for old CLI/reports | one engine wins eventually | intelligence/startup.py vs specialists/* | **CONTRADICTORY**: two opportunity engines, two pain/pricing extractors, different scoring, same tables; legacy `$10M→$1` regex still live in production paths | ARCHITECTURE_AUDIT §2 |
| D20 | Opportunity identity = problem text prefix | P5 | dedup across runs | statements stable | service.py by_problem | FRAGILE: truncation-boundary edits fork identities; unrelated engines share table with different score_breakdown schemas | |
| D21 | Cross-project KB seeds projects pre-research | P5 | reuse | seeding is idempotent | kb.py seed_project | **INVALID assumption**: clones with fresh IDs each call → KB and project rows grow unbounded | BUG-02 |
| D22 | Freshness labels computed from policies; watchers refresh | P5 | time-aware research | observed_at populated | policies.freshness_state | PARTIAL: many entities persist empty observed_at → 'unknown' forever; freshness_summary has zero callers | |
| D23 | Offline-first fakes: ScriptedLLM extracts real chunk sentences | P5 evals | quotes must verify | claims derive from chunks | tests/fakes.py | VALID but masks claim-faithfulness hole (D03) because scripted claims are honest substrings | |
| D24 | Eval quality gates incl. startup failure scenarios | P5 | skeptical behavior enforced | gates detect regressions | run_eval._startup_gates | **PARTIAL**: gate-priority formula mutation survives entire unit suite + golden eval (mutation experiment logged in TEST_GAP_ANALYSIS) | |
| D25 | Prompt templates versioned files vN + meta.yaml | P1..P5 | prompt change control | prompts hold promptable logic | prompts/templates | VALID; some Python-side regex logic duplicates what prompts claim to do (mode hints unused) | modes/base.py dead |

## Dependency chains that propagate flaws

```
D03 (quote-only verification)
  └→ D23 (fakes emit honest substrings) ⇒ tests can't catch claim-truncation
     └→ BUG-09: meaning-flipping truncations pass everywhere

D06 (gain metrics)
  └→ D08 (caches amplify syndication) ⇒ severity/frequency inflation
     └→ startup rubric inputs (pains rows) inherit inflation ⇒ bad rankings

D12 (leases) ← D01 (single-writer assumption)
  └→ BUG-01 double execution corrupts D02's source-of-truth DBs concurrently

D17 (service seam) bypassed ⇒
  D19 dual engines coexist ⇒ D20 shared-table schema clash ⇒
  decisions.readiness misreads legacy breakdowns ({gate:{}} semantics)

D18 (idempotency assumption) untested ⇒ BUG-02 duplication compounds
  every later feature built on build_market_context
```
