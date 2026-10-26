# Brief — W1-IMPR-01 (IMPROVER) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Address Wave 1 review findings by improving code AND tests. Specifically: add the P1 missing C18 edge case test ("rejections present, no duplicates") to `tests/evaluation/test_eval_framework.py` — the most discriminating scenario for the duplicate_rate/rejected_ratio mislabeling. Also consider P2/P3 W6 env-override/boundary cases from W1-REV-02.
Why this matters: The test reviewer flagged a real coverage gap — without the "rejections present, no duplicates" case, the C18 fix isn't fully proven against the mislabeling bug.
Your role: improvement agent (may edit test files owned by W1-IMPL-01 and W1-IMPL-04).

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §15 improvement step)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline)
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (Wave 1 tasks, dispositions)
5. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-improvement.md
6. Reviewer finding: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-review/W1-REV-02.md (read the P1 missing edge case section)
7. Implementer report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-impl/W1-IMPL-01-T-001.md
8. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task: Address W1-REV-02 findings:

**P1 (must add):** Add test `test_duplicate_rate_zero_when_rejections_no_duplicates` to `tests/evaluation/test_eval_framework.py`:
- Scenario: rejections > 0, duplicates = 0 → duplicate_rate should be 0.0 (not equal to rejected_ratio)
- This is the most discriminating case for the old `duplicate_rate = rejected_ratio` mislabeling
- Must fail without the C18 fix, pass with it

**P2/P3 (should/nice):** W6 env-override/boundary cases in `tests/unit/test_local_only_gating.py` (optional, additive coverage)

Acceptance criteria:
- P1 test added to tests/evaluation/test_eval_framework.py
- P1 test fails against pre-fix code (confirm by reasoning, or by running against stashed fix if feasible)
- P1 test passes with current code
- Scoped command: `pytest tests/evaluation/test_eval_framework.py -v` passes
- All dispositions recorded in report: FIXED / REJECTED-with-evidence / DEFERRED-with-reason
- Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-improve/W1-IMPR-01-T-005.md

## 4. Ownership
WRITE-SET (may edit):
- `tests/evaluation/test_eval_framework.py` (add P1 edge case test)
- `tests/unit/test_local_only_gating.py` (optional: add P2/P3 cases)
READ-ONLY: everything else
FORBIDDEN: source files (eval_metrics.py, config.py, etc.)

## 5. Parallel siblings this wave
None — you are the sole improvement agent for Wave 1.

Known interactions: Your test change is in a file owned by W1-IMPL-01, but as the improvement step you are authorized to edit it to address the review finding.

## 6. Skip list and known traps
- Don't edit source files — only test files
- Don't weaken or delete existing tests
- The P1 test must actually discriminate between `duplicate_ratio()` and `rejected_ratio()` — make sure rejections > 0 and duplicates = 0 produces different results under the two formulas

## 7. Environment and tests
Scoped commands: `pytest tests/evaluation/test_eval_framework.py -v`, `pytest tests/unit/test_local_only_gating.py -v`
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-improve/W1-IMPR-01-T-005.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Improver: address every BLOCKER/MAJOR (none here) and P1 coverage gap (the missing edge case). Each finding ends FIXED/REJECTED-with-evidence/DEFERRED-with-reason. Improve code AND tests. Record dispositions in the report.
