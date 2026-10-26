# Brief — W1-IMPL-03 (IMPL) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Add mutation M-19 to `scripts/mutation_check.py` targeting `core/ids.py` `next_id()` monotonicity. This is W5 from the plan; the ULID migration (C07) has no mutation coverage (M-1..M-18 don't target `core/ids.py`).
Why this matters: Mutation testing proves the test suite detects regressions. Without a ULID mutation, a future change that breaks id monotonicity or uniqueness would not be caught by `mutation_check.py`.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy — "add the mutation first")
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items W5, C07
5. Investigation findings: `scripts/mutation_check.py` has M-1..M-18; none target `core/ids.py`; `core/ids.py:67-105` implements `next_id()` with monotonic ULID; `tests/unit/test_stage1_dead_legs.py::TestUlidIds` tests ULID properties
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-003 (W5): Add mutation M-19 to `scripts/mutation_check.py`.

Acceptance criteria (measurable):
- M-19 entry added to `MUTATIONS` list in `scripts/mutation_check.py` with format `(id, file, old_snippet, new_snippet, targeted_tests)`
- M-19 mutates `src/research_engine/core/ids.py` `next_id()` to break monotonicity (e.g., remove the `_last_random += 1` monotonic increment, or replace with a random component reset)
- M-19 targeted tests: `tests/unit/test_stage1_dead_legs.py::TestUlidIds` (or a ULID monotonicity test)
- Running `.venv/bin/python scripts/mutation_check.py M-19` reports M-19 as DETECTED
- Running `.venv/bin/python scripts/mutation_check.py` (all mutations) reports all 19 DETECTED, exit code 0
- All mutated source files are restored byte-identically after each mutation

Tests that must exist and fail without the fix:
- M-19's target test (`TestUlidIds` or equivalent) must fail when the mutation is applied (monotonicity broken) and pass when reverted

Commands that must pass (scoped): `.venv/bin/python scripts/mutation_check.py M-19` then `.venv/bin/python scripts/mutation_check.py`

## 4. Ownership
WRITE-SET (may edit):
- `scripts/mutation_check.py` (add M-19 entry to MUTATIONS list)
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/core/ids.py` (do not modify — only mutate it temporarily via the mutation harness), `tests/unit/test_stage1_dead_legs.py` (read-only; M-19 targets it but doesn't modify it)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W1-IMPL-01 | C18 (duplicate_rate fix) | evals/metrics/ | None affecting your mutation script |
| W1-IMPL-02 | C19 (INV-029 + service-boundaries.md) | docs/ | None affecting your mutation script |
| W1-IMPL-04 | W6 (local_only field) | core/config.py | None affecting your mutation script |

Known interactions: W1-IMPL-03 is the ONLY agent touching `scripts/mutation_check.py`. W1-IMPL-01's fix (eval_metrics.py:75) is a potential future mutation target but not in this wave. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed (don't redo): `core/ids.py` ULID implementation is correct; `TestUlidIds` test exists
False leads: don't modify `ids.py` directly — the mutation harness applies/reverts mutations automatically
Flaky/pre-existing failures: `mutation_check.py` mutates source files and restores them; if a restore fails, the gate fails (by design)
Gotchas: mutation format is a 5-tuple `(id, file, old_snippet, new_snippet, targeted_tests)`; `old_snippet` must match the current source exactly (verify with grep before adding)

## 7. Environment and tests
Scoped commands: `.venv/bin/python scripts/mutation_check.py M-19` then `.venv/bin/python scripts/mutation_check.py`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-impl/W1-IMPL-03-T-003.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: verify `old_snippet` matches current `ids.py` exactly before adding M-19; the mutation harness applies the mutation, runs targeted tests, reverts, and checks restoration
- M-19 should break monotonicity: e.g., change `_last_random += 1` to `_last_random = 0` (reset random component each call within a millisecond), which would produce non-unique IDs within the same millisecond
