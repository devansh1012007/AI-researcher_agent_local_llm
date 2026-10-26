# Brief — W1-IMPL-04 (IMPL) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Wire the `local_only` field into `effective_environment()` so it actually affects the resolved environment, and add a dedicated LOCAL_ONLY gating test. This is W6 from the plan; `local_only: bool = True` is defined at `core/config.py:139` but never read anywhere — it's a dead field.
Why this matters: The privacy guarantee (`local_only` ⇒ no external calls) is unimplemented. With `local_only` wired, `effective_environment()` returns `LOCAL_ONLY` when `local_only=True`, which makes `build_default_registry()` return an empty registry under LOCAL_ONLY — enforcing S2.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§11 testing philosophy, §12 data/concurrency/security)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items W6, C10
5. Investigation findings: `core/config.py:139` `local_only: bool = True` is defined but never read (grep confirmed zero readers); `effective_environment()` at `config.py:165-192` handles `privacy_mode` → LOCAL_ONLY but not `local_only`; `build_default_registry()` at `orchestrator.py:650-658` already returns empty registry under LOCAL_ONLY
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-004 (W6):
1. Wire `local_only` into `effective_environment()`: if `self.security.local_only` is True, return `LOCAL_ONLY` (fail-closed, with logged message)
2. Add a dedicated test: LOCAL_ONLY ⇒ no network providers registered; unknown mode ⇒ LOCAL_ONLY

Acceptance criteria (measurable):
- `effective_environment()` returns `LOCAL_ONLY` when `security.local_only=True` regardless of `platform.mode`
- `effective_environment()` logs an error when an unknown `platform.mode` is used and returns `LOCAL_ONLY` (fail closed)
- A test `test_local_only_forces_local_only()` asserts: `AppConfig(security=SecurityConfig(local_only=True)).effective_environment() == "LOCAL_ONLY"` even with `mode: online`
- A test `test_unknown_mode_resolves_to_local_only()` asserts: unknown mode → `LOCAL_ONLY` with error logged
- `build_default_registry(AppConfig(security=SecurityConfig(local_only=True)))` returns empty registry (no network providers)
- No existing test behavior changes (default `mode: local` with `local_only: True` should still resolve consistently)

Tests that must exist and fail without the fix:
- `test_local_only_forces_local_only()` — fails before fix (returns HYBRID/ONLINE based on mode), passes after
- `test_unknown_mode_resolves_to_local_only()` — fails before fix (returns HYBRID for unknown mode), passes after

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/unit/ -k "local_only or unknown_mode or effective_environment" -v`

## 4. Ownership
WRITE-SET (may edit):
- `src/research_engine/core/config.py` (wire `local_only` into `effective_environment()`)
- New or existing test file under `tests/unit/` for LOCAL_ONLY gating (your choice)
READ-ONLY: everything else
FORBIDDEN: `core/orchestrator.py` (already handles LOCAL_ONLY correctly — do not touch), `core/http_policy.py` (already correct — do not touch)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W1-IMPL-01 | C18 (duplicate_rate fix) | evals/metrics/ | None affecting your code |
| W1-IMPL-02 | C19 (INV-029 + service-boundaries.md) | docs/ | None affecting your code |
| W1-IMPL-03 | W5 (ULID mutation) | scripts/mutation_check.py | None affecting your code |

Known interactions: W1-IMPL-04 is the ONLY agent touching `core/config.py`. W1-IMPL-03 adds a mutation to `scripts/mutation_check.py` (disjoint file). You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed (don't redo): `privacy_mode` → LOCAL_ONLY already works at `config.py:178-179`; `build_default_registry` already returns empty registry under LOCAL_ONLY at `orchestrator.py:657-658`
False leads: don't change `privacy_mode` handling — it's already correct
Flaky/pre-existing failures: none identified at baseline
Gotchas: `local_only` defaults to `True` in `SecurityConfig` — this means DEFAULT configs already have `local_only=True`. Wire it carefully so the default behavior doesn't change unexpectedly. If `local_only=True` by default and `mode: local` (default), the resolved environment should remain `HYBRID` (today's behavior) unless `local_only` is meant to override. Decision: `local_only=True` forces `LOCAL_ONLY` — this is fail-closed and matches the field's name. Verify this doesn't break existing tests that use default `AppConfig()`.

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/unit/ -k "local_only or unknown_mode or effective_environment" -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-impl/W1-IMPL-04-T-004.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: write failing tests BEFORE the fix, confirm they fail, then apply the fix, confirm they pass
- Check `tests/conftest.py` for the `cfg` fixture — it may set `local_only` or `mode` in ways that interact with your change
- Default `AppConfig()` has `local_only=True` and `mode: local` — verify existing tests that use `AppConfig()` still pass (they may expect `effective_environment()` to return `HYBRID`)
