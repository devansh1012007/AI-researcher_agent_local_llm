# Brief — W2-REV-02 (TEST REVIEWER) · wave 2 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Independent test quality review of Wave 2 C09 changes. W2 implementers were unable to add acceptance tests (tests outside their write-set). Identify missing tests, verify existing tests still pass, and recommend test additions for egress policy enforcement.
Your role: test reviewer (READ-ONLY on source — write only your report).

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§15 test review protocol, §11 testing philosophy)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (Wave 2 tasks)
5. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/review-tests.md
6. Diff: `git diff 29112d1..HEAD -- tests/` (check if any test files changed)
7. Implementer reports: reports/w2-impl/W2-IMPL-05 through W2-IMPL-12 (look for NEED items about missing tests)
8. COMMS.md from the last WAVE-START
9. Existing test patterns: tests/invariants/test_search_failure_semantics.py (provider contract tests)

## 3. Task and acceptance criteria
Task: Test quality review of Wave 2 C09 — identify missing egress enforcement tests.
Acceptance criteria:
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- List all NEED items from W2 implementer reports (missing tests per provider)
- For each provider file changed, does a test exist that verifies policy.require() blocks non-loopback under LOCAL_ONLY?
- Check existing tests in tests/invariants/test_search_failure_semantics.py still pass (provider contract: raises on transport error)
- Mutation thinking: name 5+ plausible bugs in egress enforcement and whether tests catch each
- Missing edge cases: P1/P2/P3 prioritized list
- ORCH-DIGEST block

## 4. Ownership
WRITE-SET: none. READ-ONLY: all source/tests. FORBIDDEN: editing source.

## 5. Parallel siblings
| Agent | Role | Owns |
|---|---|---|
| W2-REV-01 | Code reviewer | all 11 provider/source files |

## 6. Skip list
- Don't edit source or tests. Don't run full suite.

## 7. Environment
Scoped: `git diff`, `git show`, `pytest tests/invariants/test_search_failure_semantics.py -v` (to verify existing tests). Do NOT: full suite.

## 8. Deliverables
Report: reports/w2-review/W2-REV-02.md. Commits: report only. Final message ≤ 8 lines.