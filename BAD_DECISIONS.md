# BAD DECISIONS

Only decisions with demonstrated damage. No softening.

---

## BD-01 — Keeping two startup engines in production paths
- **Chosen because**: Phase-5 specialist was additive; legacy CLI/report callers kept working.
- **Why wrong**: the "temporary" coexistence became permanent. Two opportunity engines write one table with incompatible score schemas; two pain extractors disagree on taxonomy; legacy price regex fabricates `$1` prices (BUG-04); CLI `opportunities`/`map`/`competitors` answer differently than the specialist for the same project; report generation invokes BOTH.
- **Evidence**: ARCHITECTURE_AUDIT §2/§A-02/A-07; BUG-04 repro; cmd_map vs run_mode outputs.
- **Damage**: every consumer picks a different truth; fixes applied to one engine silently miss the other (already happened once).
- **Replacement**: single engine = specialists/startup; legacy module demoted to data-migration reader only; CLI commands delegate to service modes.
- **Migration path**: 1) point cli map/opportunities/competitors/generate-hypotheses at StartupResearchService; 2) intelligence_reports writers read srepos/graph instead of running discover+score; 3) delete orchestrator fallback block; 4) keep StartupIntelligence.extract_all as thin adapter over specialist analyzers during transition.
- **Priority**: P1. **Reversal cost if deferred**: grows — new features keep landing on both.

## BD-02 — Report regeneration executes research pipelines
- **Chosen because**: convenient — generator had cfg access, so it rebuilt everything.
- **Why wrong**: violates the platform's own core invariant ("Markdown is a derived view"); regeneration now duplicates decisions rows, KB writes, and full analyzer passes ×2 per completion (×N per regenerate), and made reports capable of mutating state mid-render.
- **Evidence**: generator.py:387-389 trace; side-effect table in ARCHITECTURE_AUDIT §3.
- **Replacement**: orchestrator computes pipeline result once → stores on project context → generator renders from persisted entities read-only.
- **Migration path**: move run_full_pipeline call out of write_startup_research into _phase_synthesize (already called there); pass result dict through ReportGenerator ctor.
- **Priority**: P1.

## BD-03 — Lease/heartbeat liveness split across loop phases
- **Chosen because**: simplest place to renew was loop top; tasks were assumed short.
- **Why wrong**: deep-research tasks are long by definition; renewal never runs during execution → cap=1 does not fence reclaim → double orchestration on the source-of-truth DB (BUG-01). The crash-safety story Phase-4 was built around has a hole exactly where it matters.
- **Replacement**: renewal thread scoped to the claim inside `_execute`; reclaim bumps attempts atomically; stale-owner finish_task already no-ops (keep).
- **Priority**: P0.

## BD-04 — Count-based aggregation everywhere severity/confidence matter
- **Chosen because**: sums are simple and monotone.
- **Why wrong**: contradicts documented tier-invariance; syndication inflates pains/severity/frequency; hypothesis confidence lets weak evidence outvote strong; gain metrics count rows not information; "duplicate_rate" isn't duplication.
- **Replacement**: route hypothesis scoring through aggregate_claim_strength (max + independence-capped boost); frequency counts distinct underlying sources/domains (SignalAnalyzer already knows how); rename/reimplement dup-rate honestly; domain-diversity bonus capped.
- **Priority**: P1 (research validity is the product).

## BD-05 — Unverified idempotency assumption for specialist writes
- **Chosen because**: ensure_id()+save mirrored existing repo patterns.
- **Why wrong**: those patterns were append-only facts (evidence), while market/personas/competitors are derived snapshots needing upsert-by-natural-key; every re-render multiplies rows (BUG-02), compounding into KB and future projects.
- **Replacement**: natural-key upserts + invariant test (row-count stability across double build).
- **Priority**: P0 (cheap fix, currently corrupting every startup project).

## BD-06 — Metrics named for what we wish they measured
- "duplicate_rate"=rejection ratio; "citation_coverage"=plumbing tautology; "new_information_rate"=row churn.
- **Why wrong**: gates and humans steer by these names; false CONVERGED and hollow coverage signals follow.
- **Replacement**: honest implementations (dup rate via quote_hash/similarity; citation coverage from rendered citations; information rate via independence-adjusted claim delta).
- **Priority**: P1.

## Honorable mentions (context-dependent, not condemned)
- Localhost-open API (D15): right for dev, wrong as silent default — flip default, keep flag.
- Global caches: fine at laptop scale; need key-versioning before multi-config use.
- Hand-rolled MCP: correct zero-dep instinct; needs conformance tests more than rewrite.
