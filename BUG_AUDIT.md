# BUG AUDIT

Severity: P0 (corruption/catastrophic correctness) · High · Medium · Low · Suspected.
Every FACT finding includes a reproduction performed on this working tree.
Classification per finding: [FACT] verified by execution/code-trace; [INFERENCE];
[HYPOTHESIS].

---

## BUG-01 [FACT][P0] Scheduler double-executes long tasks despite profile caps

- **Component**: platform/scheduler.py (`_worker_loop`, `claim_next_task`), storage/platform_db.py
- **Trigger**: task execution time > lease_seconds, ≥2 worker threads, heartbeat renewal never fires during `_execute` (renewal branch runs only at loop top between tasks).
- **Repro** (performed): 1 job, 1 DEEP_RESEARCH task (LLM_LARGE, cap=1), 2 workers, lease=2s, heartbeat=9999s, task sleeps 4s → **executions = 2**, attempts = 2, status SUCCEEDED.
- **Why wrong**: an expired lease means "worker may be dead"; but the owner may be alive and blocked. Reclaim must be fenced against liveness. Consequence in production: any deep-research run >120s (default lease) with default worker_threads=4 → two concurrent `Orchestrator.run()` on the same project SQLite → interleaved evidence/claims/state transitions, doubled LLM spend. Phase-4 recovery tests passed only because their sleeps < lease window.
- **Root cause**: liveness signal (heartbeat) is architecturally misplaced — it can only run when the worker isn't executing; cap counting in the claim query does not fence reclaimed leases either.
- **Fix**: pump heartbeats from within `_execute` via a renewal thread tied to the claim; additionally require reclaim SQL to bump `attempts` atomically and reject `finish_task` from stale `(task_id, worker_id)` pairs (partially exists). Regression test: slow task (sleep > lease) with heartbeat_seconds > sleep must execute exactly once; with renewal thread, exactly once regardless.
- **Impact**: silent research corruption + cost doubling under completely standard config.

## BUG-02 [FACT][P0] Startup domain rows duplicate on every context build

- **Component**: specialists/startup/{market,customers,competitors,signals}.py + service.build_market_context + kb.py
- **Trigger**: any call to `build_market_context()` / `run_mode()` / `run_full_pipeline()`. All analyzers mint fresh IDs (`ensure_id()`) then save; no natural-key upsert except markets/opportunities.
- **Repro** (performed): seeded project → run_full_pipeline ×2:
  - startup_markets 1→4→(grows again), competitor_profiles 4→11, personas 8→16, alternatives 12→24, jtbd 8→16, opportunity_decisions 1→2; KB competitor/pricing rows 1→2 each run.
- **Why wrong**: reports read `all(project_id)` → duplicated competitors/pains/personas render N times; scoring aggregates that count rows inflate; "one market per project" invariant broken; KB pollutes future projects with duplicates.
- **Root cause**: write model treats derived snapshots as append-only facts. D18's idempotency assumption was never tested.
- **Fix**: upsert by natural key (competitor: lower(name); pricing plan: (name_lower, price_raw, period, observed_at); persona: segment+role; alternative: name; decision: dedupe identical (opp, decision, reason-day)); make seed_project skip existing names. Add invariant test: two consecutive build_market_context calls leave row counts unchanged.

## BUG-03 [FACT][High] `ResearchService.ask` crashes on every invocation

- **Location**: services/research_service.py:204 — `GroundedQA(orch.router.reasoning, orch.repos)`; actual ctor `(repos, retriever, provider)` (memory/qa.py:44).
- **Effect**: TypeError always → API `POST /projects/{id}/query` and MCP `ask_research_memory` are dead endpoints. No test covers the service path (CLI builds GroundedQA correctly itself), which is why 231 tests stayed green.
- **Fix**: construct with repos + build_retriever(cfg, orch.repos) + router.reasoning; add API-level test for /query.

## BUG-04 [FACT][High] Legacy `$10M` price regex still live: parses as `$1`

- **Location**: intelligence/startup.py:32-36 `_PRICE_RE` — negative lookahead backtracks into the digit string (verified: "$10M funding" → "$1", "$1.2B" → "$1.").
- **Production paths still using it**: cmd_map/cmd_opportunities/cmd_generate_hypotheses (cli/main.py:201-230,285-300,430), market_map.md + opportunity_map.md writers (intelligence_reports.py), orchestrator fallback (:534-536). The AGENTS.md-documented fix exists only in specialists/startup/competitors.py.
- **Why wrong**: fabricated $1 prices enter PriceObservation rows, wtp scoring of the legacy engine, and rendered pricing sections.
- **Fix**: route legacy extractor through `_is_magnitude_price` post-filter or delete legacy engine (see BAD_DECISIONS BD-01).

## BUG-05 [FACT][High] Market-size parser attributes first number in sentence

- **Location**: specialists/startup/market.py `_parse_value` (+ gate `size_rx AND money_rx` anywhere).
- **Verified false attributions**:
  - "In 2024, vendors raised $12M while the CRM market reached $80B" → value=2024.0
  - "Acme raised $50M funding to capture a share of the $2B market" → value=5e7 (funding as market size)
  - "The market grew 15 percent to $5 billion" → value=15.0
- **Consequence**: MarketSizeEstimate rows + cross-validation conflicts computed on garbage; MARKET_SIZE_CONFLICT noise or false consensus.
- **Fix**: anchor parse to money-pattern nearest the size keyword; reject year-shaped tokens (\b19|20\d{2}\b adjacent); reuse magnitude guard; record value_span provenance.

## BUG-06 [FACT][Medium-High] MCP tool `design_methodology` TypeErrors when invoked

- **Location**: mcp_server/server.py:452 — `MethodologyDesigner(orch.router.reasoning, orch.repos).design(h)` vs real signature `(repos, rrepos, provider)` + `design(project_id, h)`.
- **Effect**: registered RESEARCH tool fails 100% at call time. No test invokes it end-to-end.

## BUG-07 [FACT][Medium] Evidence FTS index duplicates rows on re-save

- Verified: saving one evidence 3× yields evidence=1 row, evidence_fts=3 rows; fts_search returns 3 hits. No delete/update path exists (repositories.py:176-179).
- **Impact**: retrieval ranking pollution; unbounded index growth under watcher/incremental re-extraction.

## BUG-08 [FACT][Medium] `/startup/*` API breaks under default `create_app()`

- api/app.py:308 `_svc()` closes over constructor arg `ctx` instead of lazily-resolved `get_ctx()`; verified AttributeError 'NoneType' has no 'cfg'. `cmd_serve` passes ctx so production serve works — library/default construction path is broken and contradicts the function's own comment ("resolved lazily").

## BUG-09 [FACT][High — research quality] Claim↔quote faithfulness unchecked

- verify_quote only checks quote∈chunk (pipeline/evidence.py:157). Nothing compares claim_text semantics to quote. Truncations (claim_text[:120] pattern exists even in our fakes) can invert meaning while passing all gates; eval re-verifies quotes only (eval_metrics.py:77-89).
- **Fix direction**: store claim span offsets; require extractor to emit quote-span; validator checks claim keywords ⊂ span window; flag partial-sentence claims (no terminal punctuation alignment).

## BUG-10 [FACT][Medium] MARKET_SIZE_CONFLICT rows are un-analyzable by design

- market.py writes Contradiction(statement_a=value_raw…) with claim_a_id=""; contradiction_analyzer._claim_evidence("")→[] ⇒ every dimension empty ⇒ verdict UNRESOLVED "insufficient context", which orchestrator then suppresses from explanations (orchestrator.py:349). The analyzer's temporal/geographic/measurement classification can never fire for exactly the rows where it matters most.

## BUG-11 [FACT][Medium] EventBus drops audit events silently under backpressure

- Verified: queue_size=4, publish 20, slow/no consumer → 16 dropped; no counter/log/return signal. EventPersister and SSE subscribers share this fate; audit trail silently incomplete under load. Violates "major events log twice" spirit (AGENTS.md).

## BUG-12 [FACT][Low-Medium] Project list/show drift

- list_projects scans project.json files; get/status read SQLite. Orphan file (verified) appears in list, 404s on get. Crash between file write and DB save creates permanent ghosts; delete of DB row leaves ghost listing.

## BUG-13 [FACT][Low] Duplicate class definitions & dead code cluster

- services/research_service.py defines NotFoundError/ConflictError twice (shadowing, harmless today, confusing tomorrow). Dead loop intelligence/startup.py:91-92. Tautological eval condition run_eval.py:38 (`... or True`). StartupReportWriter.generate_all unreferenced. modes/base.py module entirely unimported. GapCategory.COMPETITOR_GAP/VALIDATION_GAP never emitted. Opportunity fields market_signal_evidence_ids/pricing_evidence_ids/secondary_assumptions have zero writers. CompetitorProfile.features never populated (landscape x_guess always "unknown"). ReportRepo/table unused. ids.seed_counter uncalled.

## BUG-14 [SUSPECTED][Medium] Hypothesis ranking tie-bias toward generation order

- rank_hypotheses sorts stably over insertion-order SQL (no ORDER BY). Equal scores rank first-generated highest. Combined with fixed 4-chain generation (D11), CUSTOMER always outranks peers at parity. [INFERENCE from code; not yet empirically demonstrated with equal scores.]

## BUG-15 [SUSPECTED][Medium] Funding vocabulary leaks into payment-class demand evidence

- pain_evidence_class actual_payment regex matches bare `invoice/payment`; verified "Invoice-automation startup raises $20M" classifies as actual_payment (weight 1.0). That evidence enters P4 support lists → economic_value 0.5 → demand_ok True → high priority from a funding headline alone — precisely what spec #81 forbids. Vendor-price guard doesn't cover this phrasing family.

## BUG-16 [SUSPECTED][Low] `decisions.readiness` counts experiments across opportunities

- readiness queries rrepos.experiments.all(project_id) without opp scoping → another opportunity's validation inflates this one's VALIDATION_READY. Gate dict passed in mitigates when present.

## Cleared suspicions (investigated, NOT bugs)

- PathSandbox: `.resolve()` defeats symlink + `..` escapes (verified blocked).
- Budget llm_calls includes synthesis via getattr (verified line 589-592).
- save_job terminal-absorbing guard blocks resurrection (verified).
- Experiment sandbox blocks network/subprocess/fs-escape, allows ssl import (existing suite).
