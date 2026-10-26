# Brief — W1-IMPL-01 (IMPL) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Fix `duplicate_rate` wiring in `eval_metrics.py:75` so it uses the true `duplicate_ratio()` instead of the rejection ratio `rejected_ratio()`. This is C18 from the plan; `duplicate_rate` is mislabeled in the eval scorer even though runtime metrics are correct.
Why this matters: `EvalScores.duplicate_rate` feeds quality gates and benchmark metrics; reporting the rejection ratio as "duplicate rate" makes the metric meaningless for detecting actual duplication. A green suite currently passes with a mislabeled metric.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §16 completion checklist)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C18
5. Investigation findings: verified that `src/research_engine/storage/repositories.py:193-206` has a working `duplicate_ratio()` method; `eval_metrics.py:75` calls `rejected_ratio(project_id)` instead
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-001 (C18): Change `eval_metrics.py:75` from `rejected_ratio(project_id)` to `duplicate_ratio(project_id)`.

Acceptance criteria (measurable):
- `EvalScores.duplicate_rate` equals `repos.evidence.duplicate_ratio(project_id)` after the change
- The test for duplicate_rate distinguishes duplicate_ratio from rejected_ratio (i.e., a fixture where they differ produces different values)
- No other behavior of `score_project` changes
- Scoped command: `.venv/bin/python -m pytest tests/evaluation/ -v` must pass
- A mutation M-19 (added by W1-IMPL-03 in `scripts/mutation_check.py`) that reverts eval_metrics.py:75 to `rejected_ratio` must be DETECTED by the mutation gate

Tests that must exist and fail without the fix:
- A test that constructs evidence where `rejected_ratio != duplicate_ratio` and asserts `score_project(...).duplicate_rate == duplicate_ratio(...)`

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/evaluation/ -v`

## 4. Ownership
WRITE-SET (may edit):
- `evals/metrics/eval_metrics.py` (line 75 only)
- `tests/evaluation/test_eval_framework.py` or a new test file under `tests/` for duplicate_rate (your choice of location)
READ-ONLY: everything else
FORBIDDEN: `scripts/mutation_check.py` (owned by W1-IMPL-03), `src/research_engine/storage/repositories.py` (already correct, do not touch)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W1-IMPL-02 | C19 (INV-029 + service-boundaries.md) | docs/ | None affecting your code |
| W1-IMPL-03 | W5 (ULID mutation in mutation_check.py) | scripts/mutation_check.py | Will add M-19 targeting eval_metrics.py:75 reversal |
| W1-IMPL-04 | W6 (local_only field + LOCAL_ONLY test) | core/config.py | None affecting your code |

Known interactions: W1-IMPL-03 will add a mutation M-19 that changes eval_metrics.py:75 back to `rejected_ratio`; your fix + that mutation together prove the gate detects the regression. You do NOT need to add the mutation yourself — W1-IMPL-03 does. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed (don't redo): `duplicate_ratio()` itself exists and is correct at `repositories.py:193-206`; `rejected_ratio()` is correct for what it measures
False leads: don't change `rejected_ratio` — it's correct for rejection rate
Flaky/pre-existing failures: none identified at baseline
Gotchas: `EvalScores` dataclass field `duplicate_rate` must keep its name; only the source of the value changes

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/evaluation/ -v`
Unique test resources: none needed (offline fakes)
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-impl/W1-IMPL-01-T-001.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: root cause only; tests first-class; long-run test answered. Write a failing test BEFORE the fix, confirm it fails, then apply the fix, confirm it passes.
- Add the test in the same commit as the fix or a separate commit immediately after — both must be in this wave.
