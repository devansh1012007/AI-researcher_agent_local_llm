# Baseline Record — GAR Configurable Research Engines (2026-10-26)

- **Base Commit**: `c574989caeb6fb89ef00181c13aa767f0e629447`
- **Branch**: `agent/configurable-research-engines`
- **Python Environment**: `/tmp/gar_venv/bin/python` (Python 3.11)

## Pre-Phase-0 Verification Gate Results
- `pytest -q`: 465 passed (note: `tests/scheduler/test_scheduler.py::TestSchedulingPolicy::test_pause_resume_cancel` exhibited intermittent race failure under load when a worker claimed the second queued task of a `PAUSING` job before `_advance_jobs` transitioned it to `PAUSED`).
- `pytest tests/invariants -q`: 62 passed.
- `python scripts/mutation_check.py`: 26/26 mutations caught (`M-1` through `M-26`).
- `python scripts/reaudit.py`: 14/14 original audit reproductions verified fixed.
- `python scripts/check_dist.py`: 22 prompt template files verified in wheel.
- `python evals/runners/run_eval.py --offline`: 17/17 PASS.
- `python evals/runners/run_goldset.py`: 3 benchmark suites evaluated, calibration report generated (`gate_ready: true`).

## Confirmed Phase 0 Findings
1. **Review Gates Resume Defect**:
   - `Orchestrator._review_gate(AFTER_PROBLEM_DEFINITION)` transitions `CLARIFYING -> PAUSED` before `_phase_plan()` executes.
   - `Orchestrator.resume()` transitioned `PAUSED -> PLANNED` on `AFTER_PROBLEM_DEFINITION`, skipping `_phase_plan()` and leaving `iteration 1` with zero branches and zero queries.
   - At `BEFORE_FINAL_SYNTHESIS`, `Orchestrator.resume()` checked `p.state in (ProjectState.CONVERGED,)` while `p.state == ProjectState.PAUSED`, which was always false and fell back to `ProjectState.SEARCHING`.
   - `ALLOWED[ProjectState.PAUSED]` in `core/state_machine.py` lacked `ProjectState.CONVERGED` and `ProjectState.SYNTHESIZING`.
   - `_review_gate()` did not track already-approved gates (`approved_gates`), causing re-entry into `run()` to re-trigger the same gate.
2. **Scheduler Pause Race (`test_pause_resume_cancel`)**:
   - `PlatformDB.claim_next_task()` did not filter out tasks belonging to jobs in `PAUSING`, `PAUSED`, `CANCELLED`, `BLOCKED`, or `WAITING_FOR_USER`.
   - When Worker 2 claimed Task 2 while the job was `PAUSING` and then called `release_task()`, `_worker_loop` did not call `_advance_one(task.job_id)`, leaving the job stuck in `PAUSING` if Worker 1 finished Task 1 during that window.
3. **Cosmetic Duplicate Decorator**:
   - `Orchestrator._research_gain` had a duplicate `@staticmethod` decorator at lines 369–370 of `src/research_engine/core/orchestrator.py`.
