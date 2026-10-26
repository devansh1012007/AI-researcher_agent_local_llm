# ARCHITECTURE AUDIT

## Intended architecture (per docs/AGENTS.md)

```
CLI ─┐
API ─┼→ services/* ─→ Orchestrator ─→ repos (SQLite per project)   [only orchestrator mutates state]
MCP ─┘                                        ├─ platform.sqlite (jobs/events)
                                              ├─ _global caches
                                              └─ specialists consume via services
Reports = derived, regenerable, side-effect-free
```

## Actual architecture (reconstructed from code; file:line in BUG_AUDIT/DECISION_HISTORY)

```
CLI  ──┬─→ services/*            (some commands)
       ├─→ Orchestrator directly (~20 sites), incl. sm.transition from cmd_pause
       ├─→ Repositories/ReasoningRepos/GraphStore direct construction
       └─→ legacy StartupIntelligence engine (writes opportunities/graph/prices)

API  ──┬─→ services/*            (project/knowledge/experiments)
       ├─→ ctx.platform_db + ctx.scheduler directly (jobs endpoints)
       └─→ StartupResearchService constructed off raw ctx closure (BUG-08)

MCP  ──┬─→ services/*            (most tools)
       └─→ Orchestrator.load + ReasoningRepos + methodologies.save (design_methodology,
           startup_get_assumptions) — one tool TypeErrors on invocation

Orchestrator synthesize (startup)
       └─→ StartupResearchService.run_full_pipeline          [execution #1]
            └─ ReportGenerator.generate_all
                 ├─ write_startup_research → run_full_pipeline AGAIN   [#2]
                 ├─ intelligence_reports.write_opportunity_map → LEGACY discover+score (writes!)
                 ├─ write_validation_candidates → AssumptionEngine writes falsification_tests
                 └─ _write_opportunity_reports (3rd readiness/recommend pass)

build_market_context executed ≈8× per startup completion;
each execution duplicates domain rows (BUG-02).
```

## Drift register

| # | Drift | Evidence | Severity |
|---|-------|----------|----------|
| A-01 | Service-seam invariant bypassed by CLI/API/MCP | DECISION_HISTORY D17 list | High (two+ business paths diverge) |
| A-02 | Two live startup engines sharing `opportunities` table with incompatible score_breakdown schemas (5-factor vs 13-dim+gate); consumers of `.gate` on legacy rows get `{}` semantics | intelligence/startup.py vs specialists/startup/opportunities.py | High |
| A-03 | "Markdown is derived" violated: report generation performs primary-state writes (pipeline runs, decision rows, falsification_tests, graph persists) | generator.py:387-389, intelligence_reports.py:145-177 | High |
| A-04 | Dual event stores with different vocabularies and no join/replay bridge (events.jsonl vs platform_events) | storage/events.py vs platform/events.py+persister | Medium |
| A-05 | project.json treated as listing source while SQLite is truth | research_service.py:71-83 vs get/status | Medium |
| A-06 | Dead mode layer (modes/base.py) — intended "mode" abstraction never wired; mode behavior actually lives in planning.py hints + specialist | zero importers | Low |
| A-07 | Legacy pain/pricing extractors duplicate specialist analyzers with weaker guards (BUG-04) | intelligence/startup.py | High |
| A-08 | Graph entities vs srepos JSON tables = two representations of competitors/pains that can disagree | graph_store vs competitor_profiles | Medium |
| A-09 | FTS index has no delete/update lifecycle | repositories.py | Medium |
| A-10 | `StartupReportWriter.generate_all` dead; its logic re-implemented in generator `_write_opportunity_reports` | grep: no callers | Low |

## Boundary violations (domain leakage)

- Scheduler knows runner semantics for deep_research/experiment/report/watchers via job_runners wiring — acceptable; but lease/heartbeat design leaks task-duration assumptions into correctness (BUG-01).
- reports layer imports specialist service and reasoning stores (A-03) — inverted dependency.
- eval runner imports tests/conftest fakes (documented hack) — acceptable debt, pinned.

## Over-engineering observed

- EventBus bounded queues + drop-oldest for a single-process, ≤4 subscribers workload whose real requirement is *never lose audit events* (BUG-11 shows the chosen semantic is the opposite of the requirement).
- Dual extraction stacks (A-02/A-07) — the cost of keeping legacy is now higher than migration.
- modes/base.py abstraction never consumed.

## Under-engineering observed

- Idempotency/upsert discipline for specialist entities (BUG-02).
- Liveness model for leases (BUG-01).
- Claim-faithfulness validation (BUG-09).
- Reconciliation between dual event stores / project.json vs DB (no job exists).

## Future risk projection

| Scale | First things to break |
|-------|----------------------|
| 10 projects | KB duplication pollutes seeds; global ID counters reset across restarts collide with existing ids if workspaces shared |
| 100 projects | project.json ghost listings multiply; FTS bloat slows retrieval; events.jsonl vs platform_events reconciliation impossible manually |
| 1,000 projects / 100k evidence | FTS rebuild cost, full-table `all(project_id)` scans in analyzers (O(N) each context build ×8), report regeneration runtime explodes via pipeline re-runs |
| long-running jobs | BUG-01 double-execution probability → ~1 per run |
| many models/providers | router per-instance cache fine; unknown-provider silent mock fallback becomes a footgun at scale (silent quality collapse) |

## Recommended target architecture (minimal moves)

1. One startup engine: delete legacy paths from CLI/reports/orchestrator-fallback (keep module for data migration only).
2. Reports strictly read-only: precompute pipeline result once in orchestrator, pass to generator via context object.
3. Upsert-by-natural-key discipline in StartupRepos (+ invariant tests).
4. Lease fencing: renewal thread inside `_execute` + reclaim bumps attempts atomically.
5. Single interface rule enforced by test: forbid `Orchestrator.load` outside services/specialists/cli-new/run (lint-level guard).
6. Event bus: unbounded audit lane for persister (or blocking put w/ timeout + metric).
