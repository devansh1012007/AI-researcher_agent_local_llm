# Brief — W4-REV-01 (REV) · wave 4 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Independent final review of the complete diff from `BASE_SHA` (`cd6b948`) to `HEAD` after all waves complete. Review the whole branch for cross-wave interactions, regressions, and whether tests genuinely prove correctness. You are a fresh reviewer with no prior context on the individual changes.
Why this matters: Per-wave reviews miss cross-wave interactions. This is the final gate before the run is considered complete.

Your role: final reviewer (READ-ONLY on source — you write only your report).

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§2.4 mandatory final review, §15 independent review protocol)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (scope, baseline, commands)
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (all tasks, waves, dispositions)
5. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — full scope
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/review-code.md and templates/review-tests.md
7. COMMS.md from the last WAVE-START
8. All agent reports in `reports/w1-impl/`, `reports/w2-impl/`, `reports/w3-impl/`, `reports/w1-review/`, `reports/w2-review/`, `reports/w3-review/`

## 3. Task and acceptance criteria
Task: Review the complete branch diff `BASE_SHA..HEAD` excluding `docs/agent-ops/`.

Acceptance criteria (measurable):
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- All BLOCKER and MAJOR findings have dispositions (FIXED/REJECTED/DEFERRED with reasoning)
- Cross-wave interactions checked (e.g., W2-IMPL-05 `build_provider` signature change + W2-IMPL-09 ollama/openai_compat constructor changes)
- All C09 call sites verified to route through EgressPolicy
- W4 sandbox guard fix verified (no rebindable globals)
- C18 duplicate_rate fix verified
- C19 INV-029 row and service-boundaries.md update verified
- W5 ULID mutation M-19 added and detected
- W6 local_only field wired and tested
- Full test suite passes relative to baseline
- `scripts/mutation_check.py` all mutations DETECTED, exit 0
- `scripts/reaudit.py` 14/14 fixed

## 4. Ownership
WRITE-SET: none (read-only on source; write only your report to `reports/final/`)
READ-ONLY: all source code, all agent reports, COMMS.md, 00-mission.md, 01-work-ledger.md
FORBIDDEN: editing any source file

Need something outside? Post `QUERY` to ORCH.

## 5. Parallel siblings this wave
None — you are the sole reviewer for the final integration review.

Known interactions: You review cross-wave interactions that per-wave reviewers may have missed.

## 6. Skip list and known traps
- Don't edit source code — you report, others fix
- Don't run the full suite (orchestrator runs gates) — but you may run scoped checks to verify your findings
- Don't commit source changes — only your report

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest <specific-test-file> -v` (only to verify your findings)
Full suite, mutation_check, reaudit are run by the orchestrator as gates
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/final/W4-REV-01-FINAL.md
Commits: report only (docs-only commit)
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Final reviewer: blind pass first (read diff before agent reports), then claims audit. Apply the long-run test independently. List optimization/simplification opportunities. Severity: BLOCKER/MAJOR/MINOR/NIT. Each finding needs file:line, evidence, recommended fix.
