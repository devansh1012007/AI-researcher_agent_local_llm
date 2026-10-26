# Brief — W1-REV-02 (TEST REVIEWER) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Independent test quality review of all Wave 1 test changes. Judge tests as work product: do they assert behavior (not implementation), fail without the fix, deterministic/isolated, not over-mocked, cover error paths and boundaries.
Why this matters: Missing tests for behavior changes are an automatic MAJOR finding per AGENTS.md §15.
Your role: test reviewer (READ-ONLY on source — write only your report).

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§15 test review protocol, §11 testing philosophy)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline)
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (Wave 1 tasks)
5. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/review-tests.md
6. Diff: `git diff cd6b948..HEAD -- tests/evaluation/test_eval_framework.py tests/unit/test_local_only_gating.py`
7. Implementer reports (read AFTER blind pass):
   - reports/w1-impl/W1-IMPL-01-T-001.md (C18 test)
   - reports/w1-impl/W1-IMPL-04-T-004.md (W6 test)
8. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task: Test quality review of Wave 1 test diff `cd6b948..HEAD` for:
- `tests/evaluation/test_eval_framework.py` (C18: duplicate_rate test)
- `tests/unit/test_local_only_gating.py` (W6: local_only gating tests)

Acceptance criteria:
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- Per test: asserts behavior? fails without fix? deterministic/isolated? over-mocked?
- Coverage of changed lines/branches, error paths, boundaries
- Mutation thinking: name 5+ plausible bugs and whether tests catch each
- Flakiness evidence from repeated runs
- Missing edge cases: prioritized P1/P2/P3 list with case tables
- Changed behavior without tests: flag any
- ORCH-DIGEST block with verdict, findings, missing edge cases

## 4. Ownership
WRITE-SET: none (read-only on source; write only your report to `reports/w1-review/`)
READ-ONLY: all source code, all implementer reports
FORBIDDEN: editing any source file

## 5. Parallel siblings this wave
| Agent | Role | Owns |
|---|---|---|
| W1-REV-01 | Code reviewer | eval_metrics.py, mutation_check.py, config.py, docs |

Known interactions: You review tests; W1-REV-01 reviews code. Cross-check: does each test change match its code change? Do code changes have corresponding tests?

## 6. Skip list and known traps
- Don't edit source — you report, implementers fix
- Don't run the full suite (orchestrator runs gates) — scoped checks OK to verify findings
- Don't commit source changes — only your report

## 7. Environment and tests
Scoped commands: `git diff cd6b948..HEAD -- tests/evaluation/test_eval_framework.py tests/unit/test_local_only_gating.py`, `pytest tests/evaluation/test_eval_framework.py tests/unit/test_local_only_gating.py -v` (to verify your findings)
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-review/W1-REV-02.md
Commits: report only (docs-only commit)
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Test reviewer: blind pass first on the test diff. Check: does each test fail without the fix (reversal)? Mutation thinking: off-by-one, inverted condition, missing await, dropped error, wrong default. Edge cases: boundaries, empty/null/duplicate, unicode/encoding, oversized payloads, hostile input, concurrency, idempotency, partial failure, authz bypass, backward compatibility, clock/timezone.
