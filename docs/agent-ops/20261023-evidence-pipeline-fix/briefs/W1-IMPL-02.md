# Brief — W1-IMPL-02 (IMPL) · wave 1 · run 20261023-evidence-pipeline-fix

## 1. Role and mission
Mission: Add the missing `INV-029` row to `docs/invariants.md` and add the review operation to `docs/service-boundaries.md` canonical operations list. This is C19 from the plan; the invariant table has INV-026/027/028 but not INV-029, and the service-boundaries doc doesn't list the review decision operation.
Why this matters: INV-029 closes the gap on "no route leg resolves to a provider that does not exist and is not explicitly marked optional." Without it, the invariant set doesn't cover route-leg honesty. The service-boundaries doc must list `record review decision` as a canonical operation since C15 added it.

Your role: implementer.

## 2. Required reading (in this order)
1. docs/agent-ops/20261023-evidence-pipeline-fix/templates/STANDING-ORDERS.md (binding)
2. AGENTS.md (§5 invariants, §15 documentation discipline)
3. docs/agent-ops/20261023-evidence-pipeline-fix/00-mission.md (commands, baseline, hotspots)
4. Plan: docs/plans/2026-10-22-evidence-pipeline-and-analyst-review.md — items C19
5. Investigation findings: `docs/invariants.md` has INV-023/026/027/028 but not INV-029; `docs/service-boundaries.md` lines 21-24 list canonical operations without review
6. Template: docs/agent-ops/20261023-evidence-pipeline-fix/templates/report-implementation.md
7. COMMS.md from the last WAVE-START

## 3. Task and acceptance criteria
Task T-002 (C19):
1. Add INV-029 row to the invariant table in `docs/invariants.md`
2. Add `record review decision` to the canonical operations list in `docs/service-boundaries.md`

Acceptance criteria (measurable):
- INV-029 row states: "No route leg resolves to a provider that does not exist and is not explicitly marked optional. Every leg is either resolved, explicitly optional-and-unconfigured, or misconfigured (naming a provider not in the registry vocabulary at all). Zero legs in the third state."
- INV-029 names enforcing module: `pipeline/routing.py` (`route_for`, `ROUTE_LEGS/_LEGS`), `core/orchestrator.py` (`build_default_registry`)
- INV-029 names test: `tests/unit/test_stage1_dead_legs.py` (or a new test) — the test asserts zero misconfigured legs under default `AppConfig()`
- `docs/service-boundaries.md` canonical operations list includes `record review decision`
- No other content in either doc changes
- Both docs render as valid markdown (no broken table syntax)

Commands that must pass (scoped): `.venv/bin/python -m pytest tests/invariants/test_system_invariants.py -v` (to confirm nothing breaks)

## 4. Ownership
WRITE-SET (may edit):
- `docs/invariants.md` (invariant table only — add one row after INV-028)
- `docs/service-boundaries.md` (canonical operations list — add one operation)
READ-ONLY: everything else, including source code
FORBIDDEN: `src/` files (no code changes needed for this task)

Need something outside? Post `NEED`; report `DEFERRED-DEPENDENCY`.

## 5. Parallel siblings this wave
| Agent | Task | Owns | Contracts it changes |
|---|---|---|---|
| W1-IMPL-01 | C18 (duplicate_rate fix) | evals/metrics/ | None affecting your docs |
| W1-IMPL-03 | W5 (ULID mutation) | scripts/mutation_check.py | None affecting your docs |
| W1-IMPL-04 | W6 (local_only field) | core/config.py | None affecting your docs |

Known interactions: none — four disjoint file sets. You cannot see their uncommitted work.

## 6. Skip list and known traps
Already fixed (don't redo): INV-026/027/028 rows already exist; don't duplicate them
False leads: don't add a new test file unless needed — INV-029 can reference `tests/unit/test_stage1_dead_legs.py` which already tests route legs
Flaky/pre-existing failures: none identified at baseline
Gotchas: invariant table uses `|` markdown table syntax — preserve alignment; INV numbering must not collide with reserved range INV-015..INV-025 (phase-7 branch)

## 7. Environment and tests
Scoped commands: `.venv/bin/python -m pytest tests/invariants/test_system_invariants.py -v`
Unique test resources: none needed
Do NOT: full suite, container restarts, shared-DB migrations, fixed ports

## 8. Deliverables
Report: docs/agent-ops/20261023-evidence-pipeline-fix/reports/w1-impl/W1-IMPL-02-T-002.md
Commits: code first, then report (docs-only), trailers: Task / Agent / Wave / Report
Final message (≤ 8 lines): STATUS | agent | task | report path | commit SHAs | blockers

## 9. Role-specific notes
- Implementer: root cause only (documentation gap); tests not required for doc-only change but verify existing tests still pass
- Long-run test: Reversal — if INV-029 were removed, which test would fail? Answer: none directly (it's a documentation invariant), but `tests/unit/test_stage1_dead_legs.py` enforces the behavior it describes
