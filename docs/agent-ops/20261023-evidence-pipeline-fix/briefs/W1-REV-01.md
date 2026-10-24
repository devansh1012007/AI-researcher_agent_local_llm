# Brief — W1-REV-01 (CODE REVIEWER) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Independent code review of all Wave 1 source changes (not tests). Blind pass first — read the diff and code in context BEFORE reading implementer reports. Verify each implementer's claims against the actual code. Try to break the fixes with concrete inputs/interleavings.
Why this matters: Per-wave reviews catch regressions the implementer missed; blind-first review prevents rubber-stamping.
Your role: code reviewer (READ-ONLY on source — write only your report).

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§15 independent review protocol, §3 No-Band-Aid doctrine)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline)
4. docs/agent-ops/20261023-evidence-pipeline-fix/01-work-ledger.md (Wave 1 tasks)
5. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/review-code.md
6. Diff: `git diff cd6b948..HEAD -- evals/metrics/eval_metrics.py scripts/mutation_check.py src/research_engine/core/config.py docs/invariants.md docs/service-boundaries.md`
7. Implementer reports (read AFTER blind pass):
   - reports/w1-impl/W1-IMPL-01-T-001.md
   - reports/w1-impl/W1-IMPL-03-T-003.md
   - reports/w1-impl/W1-IMPL-04-T-004.md
8. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task: Code review of Wave 1 diff `cd6b948..HEAD` for these files:
- `evals/metrics/eval_metrics.py` (C18: duplicate_rate fix)
- `scripts/mutation_check.py` (W5: M-19 ULID mutation)
- `src/research_engine/core/config.py` (W6: local_only wiring)
- `docs/invariants.md`, `docs/service-boundaries.md` (C19: INV-029 row + review op)

Acceptance criteria:
- VERDICT: APPROVE / APPROVE-WITH-CHANGES / REJECT
- Every finding has ID, file:line, evidence, severity (BLOCKER/MAJOR/MINOR/NIT), recommended fix
- Claims audit: each implementer claim checked against code
- Long-run test answered independently: Source / Load / Hostile / Operability / Reversal
- Band-aid hunt: swallowed errors, special-casing, suppressed types, single-call-site fixes, mocking the unit under test
- Optimization pass: list with DO NOW / DO LATER / NOT WORTH-IT verdicts
- ORCH-DIGEST block with verdict, finding counts, top 3 risks

## 4. Ownership
WRITE-SET: none (read-only on source; write only your report to `reports/w1-review/`)
READ-ONLY: all source code, all implementer reports
FORBIDDEN: editing any source file

## 5. Parallel siblings this wave
| Agent | Role | Owns |
|---|---|---|
| W1-REV-02 | Test reviewer | tests/evaluation/test_eval_framework.py, tests/unit/test_local_only_gating.py |

Known interactions: You review code; W1-REV-02 reviews tests. Cross-check: does each test change match its code change? Do code changes have corresponding tests?

## 6. Skip list and known traps
- Don't edit source — you report, implementers fix
- Don't run the full suite (orchestrator runs gates) — scoped checks OK to verify findings
- Don't commit source changes — only your report

## 7. Environment and tests
Scoped commands: `git diff cd6b948..HEAD -- <paths>`, `git show <sha>` for individual commits
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-review/W1-REV-01.md
Commits: report only (docs-only commit)
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Code reviewer: blind pass first, then claims audit. Read the diff before the implementer reports. Dimensions: correctness, root cause vs symptom, regression/compat, concurrency, error handling, security/abuse, performance, migration/rollback, observability, maintainability, docs impact.
