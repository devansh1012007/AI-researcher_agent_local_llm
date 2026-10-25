# Work ledger — 20261023-evidence-pipeline-fix

Orchestrator-owned; source of truth for resume. Updated at every wave boundary.

## Plan coverage

| Plan item | Summary | Disposition |
|---|---|---|
| C09 | Route all httpx call sites through EgressPolicy; router.build_provider policy param; fetching.py redirect validation | W1 (partial → W2 completion) |
| W4 | Sandbox guard rebindable write-root; override-write regression test | W3 |
| C18 | Fix duplicate_rate wiring in eval_metrics.py:75 | W1-A1 |
| C19 | Add INV-029 row; update service-boundaries.md | W1-A2 |
| W5 | Add ULID mutation to mutation_check.py | W1-A3 |
| W6 | Wire local_only field; add LOCAL_ONLY gating test | W1-A4 |
| W7-W10 | P1/P2/P3 batch | Deferred — out of scope for this run |

## Tasks

| Task | Plan items | Domain | Class | Root cause (1 line) | Write-set | Contract-set | Depends on | Wave | Agent | Status | Code commits | Report |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T-001 | C18 | evals/metrics | SURFACE | `eval_metrics.py:75` sets `duplicate_rate = rejected_ratio`, not true `duplicate_ratio` | `evals/metrics/eval_metrics.py` | `EvalScores.duplicate_rate` semantics | — | W1 | W1-IMPL-01 | DONE | 8f5b667 / 979e6ae | reports/w1-impl/W1-IMPL-01-T-001.md |
| T-002 | C19 | docs | SURFACE | INV-029 missing from invariants table; review op missing from canonical ops list | `docs/invariants.md`, `docs/service-boundaries.md` | INV table, service-boundaries ops list | — | W1 | W1-IMPL-02 | DONE | f77eff4 / 1628632 | reports/w1-impl/W1-IMPL-02-T-002.md |
| T-003 | W5 | scripts/mutation_check | SURFACE | No ULID mutation; M-1..M-18 don't cover `core/ids.py` | `scripts/mutation_check.py` | MUTATIONS list | T-001 (mutation harness pattern known) | W1 | W1-IMPL-03 | DONE | 1d78e04 / 1e54457 | reports/w1-impl/W1-IMPL-03-T-003.md |
| T-004 | W6 | core/config | SURFACE | `local_only` field defined but never read; no LOCAL_ONLY gating test | `src/research_engine/core/config.py`, new test file | `effective_environment()` contract | — | W1 | W1-IMPL-04 | DONE | 8380eaa / 1cc443d | reports/w1-impl/W1-IMPL-04-T-004.md |
| T-005 (impr) | W1-REV-02 P1 | evals/metrics (test) | SURFACE | C18 missing "rejections present, no duplicates" edge case | `tests/evaluation/test_eval_framework.py` | None | T-001 | W1 | W1-IMPR-01 | DONE | 0d1636b / fa68a91 | reports/w1-improve/W1-IMPR-01-T-005.md |
| T-005 | C09 part A | providers/llm/router.py | SURFACE | `build_provider` takes no `policy` param | `src/research_engine/providers/llm/router.py` | `build_provider(cfg, policy)` signature | — | W2 | W2-IMPL-05 | pending | | |
| T-006 | C09 part B | providers/academic/* | SURFACE | 4 academic `httpx.get` sites don't consult EgressPolicy | `providers/academic/openalex.py`, `crossref.py`, `arxiv.py`, `semantic_scholar.py` | None (internal call sites) | T-005 | W2 | W2-IMPL-06 | pending | | |
| T-007 | C09 part C | providers/search/duckduckgo.py | SURFACE | 3 `httpx.get/post` sites don't consult EgressPolicy | `providers/search/duckduckgo.py` | None | T-005 | W2 | W2-IMPL-07 | pending | | |
| T-008 | C09 part D | providers/llm/ollama.py, openai_compat.py | SURFACE | 3 `httpx.post/get` sites don't consult EgressPolicy | `providers/llm/ollama.py`, `providers/llm/openai_compat.py` | None | T-005 | W2 | W2-IMPL-08 | pending | | |
| T-009 | C09 part E | providers/embeddings/base.py | SURFACE | 4 `httpx.post/get` sites don't consult EgressPolicy | `providers/embeddings/base.py` | None | T-005 | W2 | W2-IMPL-09 | pending | | |
| T-010 | C09 part F | pipeline/fetching.py | SURFACE | `httpx.Client(follow_redirects=True)` bypasses per-hop host validation | `pipeline/fetching.py` | None | T-005 | W2 | W2-IMPL-10 | pending | | |
| T-011 | C09 part G | core/orchestrator.py | SURFACE | `build_default_registry` doesn't pass EgressPolicy into provider construction | `core/orchestrator.py` | `build_default_registry` internals | T-005 | W2 | W2-IMPL-11 | pending | | |
| T-012 | W4 | experiments/runner.py | SURFACE | `_ALLOWED_WRITE_ROOT` rebindable module global in sandbox guard | `experiments/runner.py`, new test | Sandbox guard contract | — | W3 | W3-IMPL-12 | pending | | |
| T-013 | W4 | tests/experiments/ or tests/security/ | SURFACE | No override-write regression test exists | new test file | None | T-012 | W3 | W3-IMPL-13 | pending | | |

## Waves

### Wave 1 — Small issues (4 agents, parallel)
- WAVE_BASE_SHA: cd6b948
- Agents: W1-IMPL-01 (T-001), W1-IMPL-02 (T-002), W1-IMPL-03 (T-003), W1-IMPL-04 (T-004), W1-IMPR-01 (improvement)
- Ownership file: ownership/W1.tsv
- Pre-mortem: All four tasks touch disjoint files; no conflicts occurred. T-004 `effective_environment()` change did not affect provider registration tests (mitigated by fail-closed design).
- Gate results: full pytest 385 passed/1 skipped (baseline 378/1 → +7 tests), mutation_check M-1..M-19 DETECTED exit 0, reaudit 14/14 fixed. All green.
- Review findings → dispositions: W1-REV-01 (code) APPROVE, no findings; W1-REV-02 (test) APPROVE-WITH-CHANGES — P1 missing C18 edge case → FIXED by W1-IMPR-01 (added `test_duplicate_rate_zero_when_rejections_no_duplicates`); P2/P3 W6 cases → DEFERRED (additive coverage, not defects)
- Review/improve cycles used: 1/2
- Status: COMPLETE

### Wave 2 — C09 egress enforcement (8 agents, parallel)
- WAVE_BASE_SHA: 29112d1
- Agents: W2-IMPL-05..12 (T-005..T-012), W2-IMPR-01 (improvement), W2-DREV-01/02 (delta review)
- Ownership file: ownership/W2.tsv
- Pre-mortem: T-005 changes `build_provider` signature (contract change). All other W2 agents depend on T-005's new `policy` param. C2 contract risk mitigated by `policy: EgressPolicy | None = None` convention.
- Gate results: full pytest 409 passed/1 skipped (baseline 378/1 → +31 tests incl. 24 egress), mutation_check M-1..M-19 DETECTED exit 0, reaudit 14/14 fixed (with conftest LOCAL_ONLY=false pin). All green.
- Review findings → dispositions: W2-REV-01 APPROVE-WITH-CHANGES — F-1 (unused import, MINOR) FIXED by W2-IMPR-01; F-2 (dead HTTPStatusError/lost 429-503 retry, MAJOR) FIXED; F-3 (duckduckgo follow_redirects=True bypasses per-hop validation, MAJOR) FIXED. W2-REV-02 APPROVE-WITH-CHANGES — test gap BLOCKER FIXED by W2-IMPR-01 (24 egress enforcement tests). Delta reviews W2-DREV-01/02: APPROVE.
- Review/improve cycles used: 1/2
- Status: COMPLETE

### Wave 3 — W4 sandbox guard (2 agents, parallel)
- WAVE_BASE_SHA: 46cea2e
- Agents: W3-IMPL-12 (T-013), W3-IMPL-13 (T-014)
- Ownership file: ownership/W3.tsv
- Pre-mortem: T-013 rewrites the sandbox guard; T-014 adds a test that exercises it. Risk: T-014's test may not run without the shared env (needs `exec()` sandbox); mark NOT-RUN if needed.
- Gate results: <pending>
- Review findings → dispositions: <pending>
- Review/improve cycles used: 0/2
- Status: pending dispatch

### Wave 4 — Verification & independent review (1 reviewer agent)
- WAVE_BASE_SHA: <to be set at dispatch>
- Agent: W4-REV-01 (independent review of complete diff)
- Gate: full pytest + mutation_check + reaudit
- Status: pending dispatch

### Deep dives
None in this run — all tasks are SURFACE class.

### Deferred / open items
- W7-W10 batch (P1/P2/P3): unknown provider hard fail, dedicated templates, conformance harness, property layer, silent except blocks, assert-for-runtime, dead code purge, doc drift, events observability, P3-1..P3-9 metric honesty. Deferred because out of scope for this run (user confirmed W7-W10 not in this batch).

### Out-of-plan discoveries
None yet.

### Assumptions → see 00-mission.md §6

## Phase 0–6 Roadmap Completion (2026-10-25)
- **Phases 0–1**: Restored canonical user-facing `README.md`, removed `apply_ci_stabilization.py`, made `scripts/mutation_check.py` interpreter-portable via `sys.executable`, and added `M-20` (`duplicate_rate`).
- **Phase 2 (W7)**: Completed `P1-1` through `P1-16` (unknown provider hard-fail, config knob wiring/cleanup, JSON env overrides, CLI `--config`, 3 new specialist prompt templates bringing wheel template files to 22, `structured()` failure contract + `last_outcome`, safe `PromptSpec.render()`, numeric prompt version sorting, canonical API error envelope, `list_projects` DTO sorting, `EventLog` redaction, and DuckDuckGo challenge vs no-results parsing).
- **Phase 3 & Phase 4 (W8–W9)**: Dynamic 43-route API and 30-tool MCP conformance + `docs/api.md` & `docs/mcp.md` parity (`P2-1`), property-style invariants (`P2-2`), silent-exception and `assert` cleanup (`P2-3`, `P2-4`), canonical money parser consolidation (`P2-5`), documentation reconciliation (`P2-6`), `/health` events degradation reporting (`P2-7`), and analyst review overlay verification (`C13`–`C16`).
- **Phase 5 (W10)**: Implemented `report_citation_coverage` (`P3-1`, `M-21`), deduplicated `research_gain` (`P3-2`, `M-22`), `dup_count` persistence (`P3-3`, `M-23`), unsupported hypothesis cap `<=0.25` (`P3-4`), `RefinementLoop` lifecycle transitions (`P3-5`), vendor funding vs customer payment separation (`P3-6`, `M-24`), evidence-derived P4 strength (`P3-7`, `M-25`), deterministic hypothesis ranking tie-breaker (`P3-8`), and opportunity-scoped `Experiment.opportunity_id` + `DecisionEngine.readiness()` (`P3-9`, `M-26`), plus `run_eval.py --offline` (17/17 PASS) and `run_goldset.py`.
- **Phase 6**: Enforced 1 MiB max stdio line length in `mcp_server/server.py` (`6.1`) and wired `freshness_summary`/`observed_at` and `ReportRepo` (`6.2`).
- **Full Gate Verification**: `pytest` (465 passed, 1 skipped), `mutation_check.py` (`M-1`..`M-26` all DETECTED), `reaudit.py` (14/14 fixed), `check_dist.py` (passed), `run_eval.py --offline` (17/17 PASS), `run_goldset.py` (passed).
