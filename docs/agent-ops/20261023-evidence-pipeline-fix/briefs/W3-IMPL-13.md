# Brief — W3-IMPL-13 (IMPL) · wave 3 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Add an override-write regression test for the sandbox guard. The test verifies that experiment code rebinding `globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"` cannot escape the sandbox write containment — it must get `PermissionError` and the file must not exist.
Why this matters: P0-5 regression test — proves the sandbox guard fix (W3-IMPL-12) actually prevents write-root rebinding.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items W4, P0-5
5. Investigation findings: `tests/experiments/test_experiments.py` has `TestSandbox` class with `test_write_outside_workdir_denied` (uses `runner` fixture, `tmp_path`, `runner.execute()`); `LocalExperimentRunner` at `experiments/runner.py`; `runner.execute("proj_sbx", {"code": ..., "timeout_seconds": ...})` returns `ExperimentExecution` with `.status`, `.stderr`, `.exit_code`
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-014 (W4 part B):
1. Create `tests/unit/test_sandbox_override_write.py` with a test that:
   - Creates experiment code that does `globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"` then writes to `/tmp/escape_test.txt`
   - Executes via `LocalExperimentRunner`
   - Asserts `ex.status == "FAILED"` and `"sandbox" in ex.stderr` or `PermissionError` in stderr
   - Asserts `/tmp/escape_test.txt` does NOT exist after execution

Acceptance criteria (measurable):
- Test file `tests/unit/test_sandbox_override_write.py` exists
- Test `test_sandbox_override_write_cannot_rebind_write_root` exists
- Experiment code rebinds `_ALLOWED_WRITE_ROOT` to `/tmp` and attempts write
- Asserts execution fails with sandbox-related error
- Asserts the target file outside workdir does not exist
- Test passes after W3-IMPL-12's fix is applied
- Test FAILS before W3-IMPL-12's fix (verify by running against unfixed code, or reason through it)
- Scoped command: `.venv/bin/python -m pytest tests/unit/test_sandbox_override_write.py -v` passes

Tests that must exist and fail without the fix:
- `test_sandbox_override_write_cannot_rebind_write_root` — fails before fix (rebinding works), passes after fix (PermissionError raised)

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/test_sandbox_override_write.py -v`

## 4. Ownership
WRITE-SET (may edit):
- `tests/unit/test_sandbox_override_write.py` (NEW file)
READ-ONLY: everything else
FORBIDDEN: `src/research_engine/experiments/runner.py` (owned by W3-IMPL-12), `_sandbox_guard.py` (owned by W3-IMPL-12)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W3-IMPL-12 | W4 part A (sandbox guard fix) | experiments/_sandbox_guard.py, experiments/runner.py | Your test depends on their fix |

Known interactions: W3-IMPL-12 fixes the sandbox guard; your test verifies it. Your test should FAIL against the unfixed code and PASS after the fix. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: existing sandbox tests (`test_network_denied_by_default`, `test_subprocess_denied`, `test_write_outside_workdir_denied`)
False leads: don't test against the old inline `_SANDBOX_GUARD` — test against the fixed `_sandbox_guard.py`
Flaky/pre-existing failures: none
Gotchas: The test needs to verify that rebinding `globals()["_ALLOWED_WRITE_ROOT"]` inside experiment code does NOT affect the guard. Since the guard now uses default argument values bound at definition time, rebinding the global has no effect.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/test_sandbox_override_write.py -v`
Unique test resources: none needed (offline sandbox tests)
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w3-impl/W3-IMPL-13-T-013.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: Try to confirm the test fails before the fix (by running against the current code where `_ALLOWED_WRITE_ROOT` is still rebindable), then passes after W3-IMPL-12's fix. If you can't run against unfixed code (W3-IMPL-12 hasn't committed yet), reason through it and note it as `[ASSUMED]`.
