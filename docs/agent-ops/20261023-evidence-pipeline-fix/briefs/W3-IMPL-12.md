# Brief — W3-IMPL-12 (IMPL) · wave 3 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Fix the sandbox guard rebindable write-root vulnerability in `experiments/runner.py`. The `_ALLOWED_WRITE_ROOT` is a module global read from `GAR_EXPERIMENT_WORKDIR` env var at line 37, and `_guard(event, args)` reads it at call time (line 62). User code executed via `exec()` can rebind `globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"` to escape the sandbox. Fix: bind the root and deny-net flag into the guard's closure/default arguments at definition time, in a dedicated module the user code cannot rebind.
Why this matters: P0-5 — experiment sandbox write-root is rebindable from user code, allowing writes to any filesystem path.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items W4, P0-5
5. Investigation findings: `experiments/runner.py:33-68` `_SANDBOX_GUARD` string; `:37` `_ALLOWED_WRITE_ROOT = _os.environ.get(...)` (module global); `:40` `def _guard(event, args):` reads global at call time; `:62` `root = _os.path.abspath(_ALLOWED_WRITE_ROOT)` re-reads global; `:161-163` guard is inlined into exec namespace; FIX_PLAN P0-5 fix: move guard into dedicated module with `def _guard(event, args, _root=..., _deny_net=...)` defaults captured at definition time
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-013 (W4):
1. Create `src/research_engine/experiments/_sandbox_guard.py` with a guard function whose root and deny-net values are bound as default argument values at definition time: `def _guard(event, args, _root=..., _deny_net=...)`. The values are captured from the parent scope (env vars read once at module import) and cannot be rebound by user code.
2. Update `experiments/runner.py` to import and use the guard from `_sandbox_guard.py` instead of the inlined `_SANDBOX_GUARD` string. The `_guard` function is passed to `sys.addaudithook`.
3. The guard must still: deny network (socket.connect/getaddrinfo/bind) when `_deny_net`; deny subprocess.Popen; deny file writes outside `_root`; allow reads/imports.

Acceptance criteria (measurable):
- `experiments/_sandbox_guard.py` exists with `_guard(event, args, _root=..., _deny_net=...)` signature
- `_root` and `_deny_net` are default argument values (bound at definition time, not read from globals at call time)
- `experiments/runner.py` imports `_guard` from `_sandbox_guard` instead of inlining `_SANDBOX_GUARD`
- User code doing `globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"` cannot escape — `_root` is already bound
- All existing sandbox tests still pass: `tests/experiments/test_experiments.py`, `tests/security/test_security.py`
- Scoped command: `.venv/bin/python -m pytest tests/experiments/ tests/security/ -v` passes

Tests that must exist and fail without the fix:
- W3-IMPL-13 adds the override-write regression test (separate agent). Your fix must make that test pass.

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/experiments/ tests/security/ -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/experiments/_sandbox_guard.py` (NEW file)
- `src/research_engine/experiments/runner.py` (import from _sandbox_guard instead of inline)
READ-ONLY: everything else
FORBIDDEN: `tests/experiments/test_experiments.py` (owned by W3-IMPL-13)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W3-IMPL-13 | W4 part B (override-write regression test) | tests/unit/test_sandbox_override_write.py | Depends on your fix — test verifies `globals()["_ALLOWED_WRITE_ROOT"] = "/tmp"` → `PermissionError` |

Known interactions: W3-IMPL-13 writes a test that exercises your sandbox guard. The test constructs experiment code that rebinds `_ALLOWED_WRITE_ROOT` and expects `PermissionError`. Your fix must make this test pass. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed: network deny, subprocess deny, RLIMITs, env scrub — all already in the guard
False leads: don't keep `_ALLOWED_WRITE_ROOT` as a module global read at call time; don't rely on env var re-read
Flaky/pre-existing failures: none identified at baseline
Gotchas: The guard must be importable and passable to `sys.addaudithook`. Default argument values `_root=...` and `_deny_net=...` are evaluated at function definition time (module import), capturing the env var values. User code cannot rebind default arguments of a function defined in a module they don't control.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/experiments/ tests/security/ -v`
Unique test resources: none needed (offline sandbox tests)
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w3-impl/W3-IMPL-12-T-012.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: The key insight is that default argument values are bound at function definition time, not call time. User code executed via `exec()` in the child process can rebind module globals but cannot rebind default argument values of functions defined in a separate module. `_root` should be captured from `os.environ.get("GAR_EXPERIMENT_WORKDIR", "")` at module import time in `_sandbox_guard.py`, then used as `_root=_root` default in `_guard`.
